"""Segment mAP@tIoU, classification accuracies, fall F1, TES MAE + Spearman."""
from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np


def tiou(seg: np.ndarray, segs: np.ndarray) -> np.ndarray:
    """seg (2,), segs (N,2) -> (N,)"""
    if len(segs) == 0:
        return np.zeros(0)
    inter = np.clip(np.minimum(seg[1], segs[:, 1]) - np.maximum(seg[0], segs[:, 0]), 0, None)
    union = (seg[1] - seg[0]) + (segs[:, 1] - segs[:, 0]) - inter
    return inter / np.maximum(union, 1e-6)


def average_precision(dets: List[tuple], gts: Dict[int, np.ndarray], thr: float) -> float:
    """dets: [(prog_idx, s, e, score)], gts: prog_idx -> (M,2). VOC-style (all-point interpolated)."""
    n_gt = sum(len(v) for v in gts.values())
    if n_gt == 0:
        return float("nan")
    if not dets:
        return 0.0
    dets = sorted(dets, key=lambda d: -d[3])
    used = {k: np.zeros(len(v), bool) for k, v in gts.items()}
    tp = np.zeros(len(dets))
    for i, (p, s, e, _) in enumerate(dets):
        g = gts.get(p, np.zeros((0, 2)))
        if len(g) == 0:
            continue
        ious = tiou(np.array([s, e]), g)
        ious[used[p]] = -1
        j = int(np.argmax(ious))
        if ious[j] >= thr:
            tp[i] = 1
            used[p][j] = True
    ctp = np.cumsum(tp)
    rec = ctp / n_gt
    prec = ctp / np.arange(1, len(dets) + 1)
    mrec = np.concatenate([[0], rec, [1]])
    mpre = np.concatenate([[0], prec, [0]])
    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])
    idx = np.flatnonzero(mrec[1:] != mrec[:-1])
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def segment_map(all_dets: List[List[tuple]], all_gts: List[List[tuple]], n_classes: int,
                thrs: Sequence[float] = (0.3, 0.5, 0.7)) -> Dict[str, float]:
    """all_dets[p] = [(cls, s, e, score)], all_gts[p] = [(cls, s, e)]."""
    out = {}
    for thr in thrs:
        aps = []
        for c in range(n_classes):
            dets = [(p, s, e, sc) for p, ds in enumerate(all_dets) for (cc, s, e, sc) in ds if cc == c]
            gts = {p: np.array([[s, e] for (cc, s, e) in gs if cc == c], float).reshape(-1, 2)
                   for p, gs in enumerate(all_gts)}
            ap = average_precision(dets, gts, thr)
            if not np.isnan(ap):
                aps.append(ap)
            out[f"AP@{thr}/c{c}"] = ap
        out[f"mAP@{thr}"] = float(np.mean(aps)) if aps else float("nan")
    out["mAP_avg"] = float(np.nanmean([out[f"mAP@{t}"] for t in thrs]))
    return out


def _rank(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[order] = np.arange(len(x))
    # average ties
    xs = x[order]
    i = 0
    while i < len(x):
        j = i
        while j + 1 < len(x) and xs[j + 1] == xs[i]:
            j += 1
        r[order[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return r


def spearman(a: Sequence[float], b: Sequence[float]) -> float:
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 2:
        return float("nan")
    ra, rb = _rank(a), _rank(b)
    if ra.std() == 0 or rb.std() == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def f1_binary(pred: np.ndarray, gt: np.ndarray) -> Dict[str, float]:
    pred, gt = pred.astype(bool), gt.astype(bool)
    tp = float((pred & gt).sum())
    p = tp / max(pred.sum(), 1)
    r = tp / max(gt.sum(), 1)
    return {"precision": p, "recall": r, "f1": 2 * p * r / max(p + r, 1e-9)}


def masked_accuracy(pred: np.ndarray, gt: np.ndarray, ignore: int = -100) -> float:
    m = gt != ignore
    return float((pred[m] == gt[m]).mean()) if m.any() else float("nan")
