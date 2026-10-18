"""Left/right swap detection and repair.

For each swap group (legs, arms) a 2-state Viterbi (keep / swap) runs over time.
Transition cost = how far the labelled joints move between frames (temporal
consistency) + a penalty for switching state; emission cost = deviation of the
labelled bone lengths from the sequence median (bone-length consistency) + a
small prior against being swapped. NaN joints contribute no cost.
"""
from __future__ import annotations

import numpy as np

from . import config as C


def _ffill(x):
    """Forward/back fill NaNs along axis 0 (for cost computation only)."""
    x = x.copy()
    T = x.shape[0]
    flat = x.reshape(T, -1)
    for j in range(flat.shape[1]):
        col = flat[:, j]
        ok = ~np.isnan(col)
        if not ok.any():
            col[:] = 0
            continue
        idx = np.where(ok, np.arange(T), 0)
        np.maximum.accumulate(idx, out=idx)
        col[:] = col[idx]
        first = np.argmax(ok)
        col[:first] = col[first]
    return flat.reshape(x.shape)


def _group_swap_path(X, order, group, penalty, prior, bone_w):
    idx = {n: i for i, n in enumerate(order)}
    ra = np.array([idx[r] for r, _ in group["pairs"]])
    la = np.array([idx[l] for _, l in group["pairs"]])
    A = X[:, ra, :3]  # "right" labelled
    B = X[:, la, :3]  # "left" labelled
    T = A.shape[0]
    if T < 2:
        return np.zeros(T, bool)
    states = [(A, B), (B, A)]  # (right slots, left slots) per state
    filled = [(_ffill(a), _ffill(b)) for a, b in states]

    # transition cost[t, s_prev, s]
    trans = np.zeros((T, 2, 2))
    for sp in range(2):
        for s in range(2):
            c = 0.0
            for side in range(2):
                cur = filled[s][side][1:]
                prev = filled[sp][side][:-1]
                d = np.linalg.norm(cur - prev, axis=-1)
                c = c + d.sum(-1)
            trans[1:, sp, s] = c + (penalty if sp != s else 0.0)

    # emission: bone length consistency
    emis = np.zeros((T, 2))
    emis[:, 1] += prior
    if bone_w > 0:
        for pi, ci in group.get("edges", []):
            lens = {}
            for s in range(2):
                for side in range(2):
                    p = states[s][side][:, pi]
                    c = states[s][side][:, ci]
                    lens[(s, side)] = np.linalg.norm(c - p, axis=-1)
            allL = np.concatenate([lens[(0, 0)], lens[(0, 1)]])
            allL = allL[~np.isnan(allL)]
            if allL.size == 0:
                continue
            ref_len = np.median(allL)
            if ref_len < 1e-6:
                continue
            for s in range(2):
                for side in range(2):
                    e = np.abs(lens[(s, side)] - ref_len) / ref_len
                    emis[:, s] += bone_w * np.nan_to_num(e) * 0.1

    cost = np.zeros((T, 2))
    back = np.zeros((T, 2), int)
    cost[0] = emis[0]
    for t in range(1, T):
        for s in range(2):
            cand = cost[t - 1] + trans[t, :, s]
            back[t, s] = int(np.argmin(cand))
            cost[t, s] = cand[back[t, s]] + emis[t, s]
    path = np.zeros(T, int)
    path[-1] = int(np.argmin(cost[-1]))
    for t in range(T - 1, 0, -1):
        path[t - 1] = back[t, path[t]]
    return path.astype(bool)


def fix_lr_swaps(X, order=None, groups=None, penalty=0.25, prior=1e-3, bone_weight=0.5):
    """Return (X_fixed, swapped) where swapped is dict group -> bool (T,).

    X (T,J,C>=3), world metres in channels 0..2. All channels are swapped.
    """
    order = order or C.JOINT_ORDER
    groups = groups or C.SWAP_GROUPS
    idx = {n: i for i, n in enumerate(order)}
    out = X.copy()
    info = {}
    for name, g in groups.items():
        path = _group_swap_path(out, order, g, penalty, prior, bone_weight)
        info[name] = path
        if path.any():
            for r, l in g["pairs"]:
                ri, li = idx[r], idx[l]
                tmp = out[path, ri].copy()
                out[path, ri] = out[path, li]
                out[path, li] = tmp
    return out, info
