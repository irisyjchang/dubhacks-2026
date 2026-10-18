"""Resampling, gap filling, smoothing and bone-length consistency."""
from __future__ import annotations

import numpy as np
from scipy.interpolate import CubicSpline, PchipInterpolator
from scipy.signal import savgol_filter

from . import config as C


# ----------------------------------------------------------------- resampling
def resample(times, X, fps=25.0, vis=None):
    """Linearly resample (T,...) data with NaN-preserving interpolation.

    A target sample is NaN if either bracketing source sample is NaN (so gaps
    stay gaps instead of being smeared). ``times`` in seconds, increasing.
    Returns (t_out, X_out[, vis_out]).
    """
    times = np.asarray(times, float)
    X = np.asarray(X, float)
    if len(times) < 2:
        raise ValueError("need at least 2 frames to resample")
    t0, t1 = times[0], times[-1]
    n = int(np.floor((t1 - t0) * fps + 1e-6)) + 1
    t_out = t0 + np.arange(n) / fps
    hi = np.clip(np.searchsorted(times, t_out, side="left"), 1, len(times) - 1)
    lo = hi - 1
    dt = times[hi] - times[lo]
    w = np.where(dt > 0, (t_out - times[lo]) / np.where(dt > 0, dt, 1), 0.0)
    w = np.clip(w, 0, 1)
    wshape = (-1,) + (1,) * (X.ndim - 1)
    snap_lo = (w < 1e-9).reshape(wshape)
    snap_hi = (w > 1 - 1e-9).reshape(wshape)
    w_ = w.reshape(wshape)
    out = (1 - w_) * X[lo] + w_ * X[hi]
    # exact hits must not be poisoned by the NaN neighbour
    out = np.where(snap_lo, X[lo], out)
    out = np.where(snap_hi, X[hi], out)
    if vis is None:
        return t_out, out
    vis = np.asarray(vis, float)
    vw = w.reshape((-1,) + (1,) * (vis.ndim - 1))
    vout = (1 - vw) * vis[lo] + vw * vis[hi]
    return t_out, out, vout


# ---------------------------------------------------------------- gap filling
def _runs(invalid):
    """Yield (start, end_exclusive) of True runs."""
    d = np.diff(np.concatenate([[0], invalid.astype(int), [0]]))
    starts = np.where(d == 1)[0]
    ends = np.where(d == -1)[0]
    return list(zip(starts, ends))


def fill_gaps(X, max_gap=8, method="pchip"):
    """Fill NaN gaps in X (T,J,C).

    Gaps of <= max_gap frames with valid neighbours on both sides are
    interpolated (linear / pchip / cubic spline); short gaps at the sequence
    edges are held. Longer gaps are bridged linearly (or held at edges) so the
    output is finite, but flagged False in the returned mask.
    Returns (X_filled, mask (T,J) bool: True = observed or short-gap-filled).
    """
    X = np.asarray(X, float).copy()
    T, J = X.shape[:2]
    mask = np.ones((T, J), bool)
    t = np.arange(T)
    for j in range(J):
        bad = np.isnan(X[:, j]).any(axis=-1)
        if not bad.any():
            continue
        good_idx = np.where(~bad)[0]
        if good_idx.size == 0:
            X[:, j] = 0.0
            mask[:, j] = False
            continue
        interp = None
        if method != "linear" and good_idx.size >= 3:
            gx = X[good_idx, j]
            interp = (CubicSpline if method == "cubic" else PchipInterpolator)(good_idx, gx, axis=0)
        for s, e in _runs(bad):
            n = e - s
            interior = s > 0 and e < T
            idx = np.arange(s, e)
            if interior:
                if n <= max_gap and interp is not None:
                    X[idx, j] = interp(idx)
                else:
                    a, b = X[s - 1, j], X[e, j]
                    w = ((idx - (s - 1)) / (n + 1))[:, None]
                    X[idx, j] = (1 - w) * a + w * b
                    if n > max_gap:
                        mask[idx, j] = False
            else:
                ref = X[e, j] if s == 0 else X[s - 1, j]
                X[idx, j] = ref
                if n > max_gap:
                    mask[idx, j] = False
    return X, mask


# ------------------------------------------------------------------ smoothing
def one_euro(x, fps, min_cutoff=1.0, beta=1.5, d_cutoff=1.0):
    """Zero-lag-ish One Euro filter: forward and backward passes averaged.

    x (T,...) finite. Adaptive cutoff = min_cutoff + beta*|speed| keeps fast
    motion sharp while smoothing slow jitter.
    """
    x = np.asarray(x, float)

    def alpha(cutoff):
        tau = 1.0 / (2 * np.pi * cutoff)
        return 1.0 / (1.0 + tau * fps)

    def run(seq):
        out = np.empty_like(seq)
        out[0] = seq[0]
        dx_hat = np.zeros_like(seq[0])
        prev_hat = seq[0]
        a_d = alpha(d_cutoff)
        for i in range(1, len(seq)):
            dx = (seq[i] - prev_hat) * fps
            dx_hat = a_d * dx + (1 - a_d) * dx_hat
            speed = np.abs(dx_hat)
            a = alpha(min_cutoff + beta * speed)
            prev_hat = a * seq[i] + (1 - a) * prev_hat
            out[i] = prev_hat
        return out

    if len(x) < 2:
        return x.copy()
    return 0.5 * (run(x) + run(x[::-1])[::-1])


def smooth(X, method="one_euro", fps=25.0, cfg=None):
    if method in (None, "none"):
        return X
    if method == "one_euro":
        g = lambda k, d: getattr(cfg, k, d) if cfg is not None else d
        return one_euro(X, fps, g("one_euro_min_cutoff", 2.5), g("one_euro_beta", 5.0),
                        g("one_euro_d_cutoff", 1.0))
    if method == "savgol":
        w = getattr(cfg, "savgol_window", 7) if cfg is not None else 7
        p = getattr(cfg, "savgol_polyorder", 3) if cfg is not None else 3
        w = min(w, X.shape[0] - (1 - X.shape[0] % 2))  # odd and <= T
        if w % 2 == 0:
            w -= 1
        if w <= p:
            return X
        return savgol_filter(X, w, p, axis=0, mode="interp")
    raise ValueError(f"unknown smoothing {method!r}")


# ----------------------------------------------------------- bone consistency
def bone_lengths(X, mask, order=None, bones=None, symmetric=True):
    """Median length per bone over frames where both joints are valid."""
    order = order or C.JOINT_ORDER
    bones = bones or C.BONES
    idx = {n: i for i, n in enumerate(order)}
    L = {}
    for p, c in bones:
        ok = mask[:, idx[p]] & mask[:, idx[c]]
        d = np.linalg.norm(X[:, idx[c], :3] - X[:, idx[p], :3], axis=-1)
        L[(p, c)] = float(np.median(d[ok])) if ok.any() else float("nan")
    if symmetric:
        for a, b in C.SYMMETRIC_BONES:
            if a in L and b in L:
                v = np.nanmean([L[a], L[b]]) if not (np.isnan(L[a]) and np.isnan(L[b])) else np.nan
                L[a] = L[b] = float(v)
    return L


def enforce_bone_lengths(X, lengths, order=None, bones=None):
    """Rescale each bone to its target length, walking the tree from the root.

    Keeps the root and every bone direction; only the lengths change. X (T,J,C):
    only xyz (channels 0..2) are modified.
    """
    order = order or C.JOINT_ORDER
    bones = bones or C.BONES
    idx = {n: i for i, n in enumerate(order)}
    out = X.copy()
    for p, c in bones:
        L = lengths.get((p, c))
        if L is None or not np.isfinite(L) or L <= 0:
            continue
        d = X[:, idx[c], :3] - X[:, idx[p], :3]          # original direction
        n = np.linalg.norm(d, axis=-1, keepdims=True)
        ok = n[:, 0] > 1e-6
        newd = np.where(ok[:, None], d / np.where(n > 1e-6, n, 1) * L, d)
        out[:, idx[c], :3] = out[:, idx[p], :3] + newd
    return out
