"""Non-learned jump physics: takeoff/landing, air time, height = g*t^2/8, rotation speed.

Input positions must be canonical (y-up) and in metres: apply_canonical(pos, R, scale) * scale.

Two air-phase detectors:
  - "feet": both ankles above the local ice level by > foot_thr (needs a global trajectory)
  - "rotation": longest run with |yaw rate| > rot_thr (fallback when the skeleton is
    root-relative, i.e. the pelvis never moves - VideoPose3D outputs are often root-relative)
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .data.features import yaw_angle
from .data.skeleton import L_ANKLE, L_HIP, L_SHOULDER, PELVIS, R_ANKLE, R_HIP, R_SHOULDER

G = 9.81


def has_global_trajectory(pos_m: np.ndarray, min_std: float = 0.02) -> bool:
    return float(pos_m[:, PELVIS].std(0).max()) > min_std


def is_2d(pos: np.ndarray) -> bool:
    """MMFS / 2D-keypoint input has z == 0 everywhere."""
    return float(np.abs(pos[..., 2]).max()) < 1e-6


def flip_signal(pos_c: np.ndarray) -> np.ndarray:
    """Signed projected width of hips + shoulders (x axis). Each sign change = half a turn in 2D."""
    w = (pos_c[:, L_HIP, 0] - pos_c[:, R_HIP, 0]) + (pos_c[:, L_SHOULDER, 0] - pos_c[:, R_SHOULDER, 0])
    k = np.ones(3) / 3
    return np.convolve(w, k, mode="same") if len(w) >= 3 else w


def count_half_turns(w: np.ndarray, hyst: float) -> np.ndarray:
    """Cumulative half-turn count with hysteresis (ignores jitter around zero)."""
    out = np.zeros(len(w))
    state, n = 0, 0
    for i, v in enumerate(w):
        s = 1 if v > hyst else -1 if v < -hyst else 0
        if s and state and s != state:
            n += 1
        if s:
            state = s
        out[i] = n
    return out


def _runs(mask: np.ndarray, max_gap: int = 2):
    """Contiguous True runs [s, e) after closing gaps <= max_gap."""
    m = mask.copy()
    idx = np.flatnonzero(m)
    for a, b in zip(idx[:-1], idx[1:]):
        if 1 < b - a <= max_gap + 1:
            m[a:b] = True
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def analyze_jump(pos_m: np.ndarray, start: int, end: int, fps: float = 25.0,
                 foot_thr: float = 0.08, rot_thr: float = 2.0, pad: int = 12, max_air_s: float = 1.2,
                 method: Optional[str] = None) -> Dict:
    T = pos_m.shape[0]
    s0, e0 = max(0, start - pad), min(T, end + pad)
    seg = pos_m[s0:e0]
    if len(seg) < 3:
        return {"valid": False}
    two_d = is_2d(pos_m)
    if two_d:  # revolutions from half-turn flips of the projected hip/shoulder axis
        w = flip_signal(seg)
        body = np.median(np.abs(w)) + 1e-6
        yaw = count_half_turns(w, 0.15 * body) * np.pi   # -> "angle" so revs = d(yaw)/2pi
    else:
        yaw = yaw_angle(seg)
    yaw_rate = np.gradient(yaw) * fps / (2 * np.pi)  # rev/s
    if method is None:
        method = "feet" if has_global_trajectory(pos_m) else "rotation"

    if method == "feet":
        ctx = pos_m[max(0, start - 2 * int(fps)):min(T, end + 2 * int(fps))]
        ground = np.percentile(np.minimum(ctx[:, L_ANKLE, 1], ctx[:, R_ANKLE, 1]), 10)
        low_foot = np.minimum(seg[:, L_ANKLE, 1], seg[:, R_ANKLE, 1]) - ground
        air = low_foot > foot_thr
    else:
        air = np.abs(yaw_rate) > rot_thr
    # physically plausible flight only: 0.12 s .. max_air_s (elite jumps ~0.5-0.9 s)
    runs = [r for r in _runs(air) if 0.12 * fps <= r[1] - r[0] <= max_air_s * fps]
    if not runs:
        return {"valid": False, "method": method}
    a, b = max(runs, key=lambda r: r[1] - r[0])
    t_air = (b - a) / fps
    revs = abs(yaw[min(b, len(yaw) - 1)] - yaw[a]) / (2 * np.pi)
    return {"valid": True, "method": method + ("_2d" if two_d else ""),
            "takeoff_frame": int(s0 + a), "landing_frame": int(s0 + b),
            "air_time_s": float(t_air),
            "height_m": float(G * t_air ** 2 / 8.0),
            "revolutions": float(revs),
            "rot_speed_rps": float(revs / max(t_air, 1e-6)),
            "peak_rot_speed_rps": float(np.abs(yaw_rate[a:b]).max()) if b > a else 0.0}


def detect_air_phases(pos_m: np.ndarray, fps: float = 25.0, foot_thr: float = 0.08,
                      min_air_s: float = 0.25, max_air_s: float = 1.0, min_revs: float = 0.75,
                      min_rise: float = 0.10) -> List[Dict]:
    """Unsupervised takeoff/landing detection over a whole program (needs global trajectory)."""
    if not has_global_trajectory(pos_m):
        return []
    T = pos_m.shape[0]
    low = np.minimum(pos_m[:, L_ANKLE, 1], pos_m[:, R_ANKLE, 1])
    win = int(4 * fps)
    ground = np.array([np.percentile(low[max(0, t - win):t + win], 10) for t in range(0, T, int(fps))])
    ground = np.repeat(ground, int(fps))[:T]
    out = []
    for a, b in _runs(low - ground > foot_thr):
        t = (b - a) / fps
        if min_air_s <= t <= max_air_s:
            r = analyze_jump(pos_m, int(a), int(b), fps, foot_thr, pad=3, max_air_s=max_air_s, method="feet")
            if not r.get("valid"):
                continue
            # pelvis must rise above its pre-takeoff level, and the body must rotate (real jumps >= 1 rev)
            pre = pos_m[max(0, a - int(0.5 * fps)):a, PELVIS, 1]
            rise = pos_m[a:b, PELVIS, 1].max() - (np.median(pre) if len(pre) else pos_m[a, PELVIS, 1])
            r["pelvis_rise_m"] = float(rise)
            if r["revolutions"] >= min_revs and rise >= min_rise:
                out.append(r)
    return out
