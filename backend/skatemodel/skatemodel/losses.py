"""Losses: focal (frames), 1D IoU + L1 (boundaries), CE (type/rot/ur/comb/kind), BCE (fall), Huber (GOE)."""
from __future__ import annotations

from typing import Dict, Optional

import torch
import torch.nn.functional as F

from .data.dataset import IGNORE


def focal_loss(logits, labels, gamma: float = 2.0, alpha: Optional[torch.Tensor] = None):
    """Softmax focal loss over valid frames. logits (B,T,C), labels (B,T) with IGNORE."""
    C = logits.shape[-1]
    lg = logits.reshape(-1, C).float()
    lb = labels.reshape(-1)
    valid = lb != IGNORE
    if valid.sum() == 0:
        return lg.sum() * 0.0
    lg, lb = lg[valid], lb[valid]
    logp = F.log_softmax(lg, -1).gather(1, lb[:, None]).squeeze(1)
    loss = -((1 - logp.exp()) ** gamma) * logp
    if alpha is not None:
        loss = loss * alpha.to(loss.device)[lb]
    return loss.mean()


def boundary_loss(dist, reg, labels, l1_weight: float = 1.0):
    """dist/reg (B,T,2) in frames; computed on foreground (jump/spin/step) frames."""
    fg = (labels >= 1) & (labels <= 3)
    if fg.sum() == 0:
        return dist.sum() * 0.0, dist.sum() * 0.0
    p, g = dist[fg].float(), reg[fg].float()
    inter = torch.minimum(p[:, 0], g[:, 0]) + torch.minimum(p[:, 1], g[:, 1])
    union = torch.maximum(p[:, 0], g[:, 0]) + torch.maximum(p[:, 1], g[:, 1])
    iou = inter / union.clamp(min=1e-6)
    l1 = (torch.log1p(p) - torch.log1p(g)).abs().mean()
    return (1 - iou).mean(), l1_weight * l1


def _ce(logits, target):
    t = target.reshape(-1)
    if (t != IGNORE).sum() == 0:
        return logits.sum() * 0.0
    return F.cross_entropy(logits.reshape(-1, logits.shape[-1]).float(), t, ignore_index=IGNORE)


def element_losses(pred: Dict[str, torch.Tensor], tgt: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
    if pred["kind"].shape[0] == 0:
        z = pred["kind"].sum() * 0.0
        return {k: z for k in ("kind", "jtype", "rot", "ur", "comb", "fall", "goe")
                + (("eclass",) if "eclass" in pred else ())}
    g = tgt["grade"]
    gm = torch.isfinite(g)
    goe = (F.huber_loss(pred["grade"][gm].float(), g[gm], delta=1.0) if gm.any()
           else pred["grade"].sum() * 0.0)
    fm = torch.isfinite(tgt["fall"])  # NaN = unknown (e.g. MMFS has no fall labels)
    fall = (F.binary_cross_entropy_with_logits(pred["fall"][fm].float(), tgt["fall"][fm]) if fm.any()
            else pred["fall"].sum() * 0.0)
    out = {"kind": _ce(pred["kind"], tgt["kind"]),
            "jtype": _ce(pred["jtype"], tgt["jtype"]),
            "rot": _ce(pred["rot"], tgt["rot"]),
            "ur": _ce(pred["ur"], tgt["ur"]),
            "comb": _ce(pred["comb"], tgt["comb"]),
            "fall": fall,
            "goe": goe}
    if "eclass" in pred:
        out["eclass"] = _ce(pred["eclass"], tgt["eclass"])
    return out


def total_loss(out, batch, w: Dict[str, float], alpha=None):
    parts = {"focal": focal_loss(out["cls"], batch["labels"], w.get("focal_gamma", 2.0), alpha)}
    parts["iou"], parts["l1"] = boundary_loss(out["dist"], batch["reg"], batch["labels"])
    if "elem" in out:
        parts.update(element_losses(out["elem"], batch["elem"]))
    total = sum(w.get(k, 1.0) * v for k, v in parts.items())
    return total, {k: float(v.detach()) for k, v in parts.items()}
