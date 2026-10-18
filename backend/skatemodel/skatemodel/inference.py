"""Sliding-window inference with stitching, ActionFormer-style decoding, TES, and evaluation."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import torch

from .data.augment import mediapipe_noise
from .data.dataset import IGNORE, SEG_CLASSES, ProgramStore, frame_targets
from .data.features import apply_canonical, canonical_transform, compute_features
from .metrics import f1_binary, masked_accuracy, segment_map, spearman, tiou
from .physics import analyze_jump
from .scoring.tes import score_program

DEFAULT_INFER = {"window": 640, "stride": 480, "batch_size": 8, "pre_thr": 0.1, "topk": 3000,
                 "nms_iou": 0.5, "final_thr": 0.3, "cross_nms_iou": 0.3, "max_dets": 200,
                 "same_kind_gap": 0,
                 "caps": {"sp": {"jump": 3, "spin": 3, "step": 1},
                          "fs": {"jump": 7, "spin": 3, "step": 2},
                          "unk": {"jump": 7, "spin": 3, "step": 2}}}


BODY_M_2D = 1.35  # pelvis->thorax + thigh + shin of an adult skater, metres (2D inputs have no scale)


def _taper(W: int, stride: int) -> np.ndarray:
    ramp = max(1, (W - stride) // 2)
    t = np.arange(W)
    return np.clip(np.minimum(t + 1, W - t) / ramp, 1e-3, 1.0).astype(np.float32)


@torch.no_grad()
def sliding_window(model, feats: np.ndarray, device, window=640, stride=480, batch_size=8,
                   amp_dtype=None):
    """feats (T,V,C) -> probs (T,5), dist (T,2), F (T,D) numpy (stitched by tapered averaging)."""
    model.eval()
    T = feats.shape[0]
    starts = list(range(0, max(1, T - window + 1), stride))
    if starts[-1] + window < T:
        starts.append(T - window)
    starts = [max(0, s) for s in starts]
    w = _taper(window, stride)
    acc_p = acc_d = acc_f = None
    acc_w = np.zeros(T, np.float32)
    for i in range(0, len(starts), batch_size):
        chunk = starts[i:i + batch_size]
        xb = np.zeros((len(chunk), window) + feats.shape[1:], np.float32)
        mb = np.zeros((len(chunk), window), bool)
        for k, s in enumerate(chunk):
            n = min(window, T - s)
            xb[k, :n] = feats[s:s + n]
            mb[k, :n] = True
        x = torch.from_numpy(xb).to(device)
        m = torch.from_numpy(mb).to(device)
        with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
            out = model(x, m)
        probs = out["cls"].float().softmax(-1).cpu().numpy()
        dist = out["dist"].float().cpu().numpy()
        F = out["feats"].float().cpu().numpy()
        if acc_p is None:
            acc_p = np.zeros((T, probs.shape[-1]), np.float32)
            acc_d = np.zeros((T, 2), np.float32)
            acc_f = np.zeros((T, F.shape[-1]), np.float32)
        for k, s in enumerate(chunk):
            n = min(window, T - s)
            ww = w[:n, None]
            acc_p[s:s + n] += probs[k, :n] * ww
            acc_d[s:s + n] += dist[k, :n] * ww
            acc_f[s:s + n] += F[k, :n] * ww
            acc_w[s:s + n] += w[:n]
    acc_w = np.maximum(acc_w, 1e-6)[:, None]
    return acc_p / acc_w, acc_d / acc_w, acc_f / acc_w


def nms_1d(segs: np.ndarray, scores: np.ndarray, iou_thr: float, max_keep: int) -> List[int]:
    order = np.argsort(-scores)
    keep = []
    while len(order) and len(keep) < max_keep:
        i = order[0]
        keep.append(int(i))
        if len(order) == 1:
            break
        ious = tiou(segs[i], segs[order[1:]])
        order = order[1:][ious <= iou_thr]
    return keep


def decode_segments(probs, dist, cfg=None) -> List[tuple]:
    """-> [(seg_cls, start, end, score)] with seg_cls in 0..2 (jump, spin, step)."""
    c = {**DEFAULT_INFER, **(cfg or {})}
    T = probs.shape[0]
    dets = []
    for k in range(len(SEG_CLASSES)):
        sc = probs[:, k + 1]
        cand = np.flatnonzero(sc > c["pre_thr"])
        if len(cand) == 0:
            continue
        if len(cand) > c["topk"]:
            cand = cand[np.argsort(-sc[cand])[:c["topk"]]]
        segs = np.stack([np.clip(cand - dist[cand, 0], 0, T), np.clip(cand + dist[cand, 1], 0, T)], 1)
        good = segs[:, 1] - segs[:, 0] >= 1
        cand, segs = cand[good], segs[good]
        for i in nms_1d(segs, sc[cand], c["nms_iou"], c["max_dets"]):
            dets.append((k, float(segs[i, 0]), float(segs[i, 1]), float(sc[cand[i]])))
    return dets


def select_elements(dets: List[tuple], program_type: str, cfg=None) -> List[tuple]:
    """Final element list: score threshold, cross-class suppression, per-program caps; time order."""
    c = {**DEFAULT_INFER, **(cfg or {})}
    caps = c["caps"].get(program_type, c["caps"]["unk"])
    kept, counts = [], {k: 0 for k in SEG_CLASSES}
    for d in sorted(dets, key=lambda d: -d[3]):
        if d[3] < c["final_thr"]:
            break
        kind = SEG_CLASSES[d[0]]
        if counts[kind] >= caps.get(kind, 99):
            continue
        if kept and tiou(np.array(d[1:3]), np.array([k[1:3] for k in kept])).max() > c["cross_nms_iou"]:
            continue
        # same kind overlapping or within same_kind_gap frames of a stronger one -> duplicate
        if any(k[0] == d[0] and d[1] - k[2] < c["same_kind_gap"] and k[1] - d[2] < c["same_kind_gap"]
               for k in kept):
            continue
        kept.append(d)
        counts[kind] += 1
    return sorted(kept, key=lambda d: d[1])


@torch.no_grad()
def element_head_np(model, F: np.ndarray, segs: List[tuple], device) -> Dict[str, np.ndarray]:
    m = model.module if hasattr(model, "module") else model
    if not segs:
        return {}
    ft = torch.from_numpy(F[None]).to(device)
    T = F.shape[0]
    st = torch.tensor([[0, int(np.floor(s)), min(T, max(int(np.ceil(e)), int(np.floor(s)) + 1))]
                       for s, e in segs], dtype=torch.long, device=device)
    out = m.elem_head(ft, st)
    return {k: v.float().cpu().numpy() for k, v in out.items()}


def predict_program(model, pos: np.ndarray, program_type: str, device, fps=25.0, infer_cfg=None,
                    priors=None, physics=True, amp_dtype=None, class_codes=None) -> Dict:
    """Full pipeline on a camera-space skeleton (T,17,3) -> elements with scores + TES."""
    c = {**DEFAULT_INFER, **(infer_cfg or {})}
    R, scale = canonical_transform(pos)
    pos_c = apply_canonical(pos, R, scale)
    feats = compute_features(pos_c, fps)
    probs, dist, F = sliding_window(model, feats, device, c["window"], c["stride"], c["batch_size"], amp_dtype)
    els = select_elements(decode_segments(probs, dist, c), program_type, c)
    head = element_head_np(model, F, [(s, e) for _, s, e, _ in els], device)
    kinds = [SEG_CLASSES[k] for k, *_ in els]
    res = score_program(kinds, head, program_type, priors, class_codes) if els else {"tes": 0.0, "elements": []}
    from .physics import is_2d
    pos_m = pos_c * (BODY_M_2D if is_2d(pos) else scale)  # metres (2D: assume body length)
    for (k, s, e, sc), el in zip(els, res["elements"]):
        el.update({"start_s": s / fps, "end_s": e / fps, "det_score": sc})
        if physics and el["kind"] == "jump":
            el["physics"] = analyze_jump(pos_m, int(s), int(e), fps)
    res["frame_probs"] = probs
    return res


def evaluate(model, store: ProgramStore, device, infer_cfg=None, priors=None, noise_cfg=None,
             amp_dtype=None, seed: int = 1234, class_codes=None) -> Dict[str, float]:
    c = {**DEFAULT_INFER, **(infer_cfg or {})}
    all_dets, all_gts = [], []
    tes_pred, tes_gt, tes_oracle = [], [], []
    acc = {k: ([], []) for k in ("jtype", "rot", "ur", "comb", "kind", "eclass")}
    fall_p, fall_g, goe_err, frame_acc = [], [], [], []
    for pi, p in enumerate(store.programs):
        pos = p.pos
        if noise_cfg is not None:
            pos = mediapipe_noise(pos, np.random.default_rng([seed, pi]), noise_cfg)
        R, scale = canonical_transform(pos)
        feats = compute_features(apply_canonical(pos, R, scale), store.fps)
        probs, dist, F = sliding_window(model, feats, device, c["window"], c["stride"], c["batch_size"], amp_dtype)
        dets = decode_segments(probs, dist, c)
        all_dets.append(dets)
        gts = [(int(p.elem_targets["kind"][i]), float(s), float(e)) for i, (s, e) in enumerate(p.segs)]
        all_gts.append(gts)

        if len(p.segs):
            lab, _, _ = frame_targets(p.T, p.segs, p.elem_targets["kind"], p.segs[:, 0].min(), p.segs[:, 1].max())
            for a, b in p.ann.extra.get("ignore", ()):
                lab[int(a):int(b)] = IGNORE
            frame_acc.append(masked_accuracy(probs.argmax(-1), lab, IGNORE))

        els = select_elements(dets, p.ann.program_type, c)
        head = element_head_np(model, F, [(s, e) for _, s, e, _ in els], device)
        res = (score_program([SEG_CLASSES[k] for k, *_ in els], head, p.ann.program_type, priors, class_codes)
               if els else {"tes": 0.0})
        if np.isfinite(p.ann.tes):
            tes_pred.append(res["tes"])
            tes_gt.append(p.ann.tes)

        # oracle segments: classification metrics, GOE, TES with GT base values
        if len(p.segs):
            oh = element_head_np(model, F, [tuple(s) for s in p.segs], device)
            t = p.elem_targets
            for k in acc:
                if k not in oh:
                    continue
                acc[k][0].append(oh[k].argmax(-1).reshape(-1))
                acc[k][1].append(t[k].reshape(-1))
            fk = np.isfinite(t["fall"])
            fall_p.append(oh["fall"][fk] > 0)
            fall_g.append(t["fall"][fk] > 0.5)
            goe_pred = np.clip(oh["grade"], -5, 5) / 10.0 * t["bv"]
            goe_err.append(np.abs(goe_pred - t["goe"]))
            if np.isfinite(p.ann.tes):
                tes_oracle.append((float((t["bv"] + goe_pred).sum()), p.ann.tes))

    out = {f"seg/{k}": v for k, v in segment_map(all_dets, all_gts, len(SEG_CLASSES)).items()}
    out["frame_acc"] = float(np.mean(frame_acc)) if frame_acc else float("nan")
    for k, (pr, gt) in acc.items():
        if pr:
            out[f"acc/{k}"] = masked_accuracy(np.concatenate(pr), np.concatenate(gt), IGNORE)
    if acc["jtype"][0]:  # first-slot (main jump) accuracy
        pr = np.concatenate([a.reshape(-1, 3)[:, 0] for a in acc["jtype"][0]])
        gt = np.concatenate([a.reshape(-1, 3)[:, 0] for a in acc["jtype"][1]])
        out["acc/jtype_slot0"] = masked_accuracy(pr, gt, IGNORE)
    if fall_p:
        fg = np.concatenate(fall_g)
        if len(fg):
            f = f1_binary(np.concatenate(fall_p), fg)
            out.update({f"fall/{k}": v for k, v in f.items()})
        out["goe_mae"] = float(np.concatenate(goe_err).mean())
    if tes_pred:
        tp, tg = np.array(tes_pred), np.array(tes_gt)
        out["tes/mae"] = float(np.abs(tp - tg).mean())
        out["tes/spearman"] = spearman(tp, tg)
        if tes_oracle:
            to = np.array(tes_oracle)
            out["tes/mae_oracle_seg"] = float(np.abs(to[:, 0] - to[:, 1]).mean())
            out["tes/spearman_oracle_seg"] = spearman(to[:, 0], to[:, 1])
    return out
