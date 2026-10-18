"""33 MediaPipe landmarks -> 17 joints (config driven), and axis/unit conversion.

Channel layout used throughout the pipeline: last axis has 5 channels
``[x, y, z, u, v]`` = world xyz (metres, hip-centred) + normalised image uv.
"""
from __future__ import annotations

import numpy as np

from . import config as C

N_CH = 5  # x y z u v


def _eval_joint(name, P, V, cache, spec):
    """Return (values (T,5), vis (T,)) for a named joint."""
    if name in cache:
        return cache[name]
    s = spec[name]
    kind = s["type"]
    if kind == "landmarks":
        ids = s["ids"]
        out = P[:, ids].mean(axis=1)           # NaN propagates (strict mean)
        vis = V[:, ids].min(axis=1)
    elif kind == "lerp":
        a, va = _eval_joint(s["a"], P, V, cache, spec)
        b, vb = _eval_joint(s["b"], P, V, cache, spec)
        t = float(s["t"])
        out = (1 - t) * a + t * b
        vis = np.minimum(va, vb)
    elif kind == "extrapolate":
        base = P[:, s["base_ids"]].mean(axis=1)
        bvis = V[:, s["base_ids"]].min(axis=1)
        fb_ids = s.get("fallback_ids")
        if fb_ids:
            fb = P[:, fb_ids].mean(axis=1)
            fvis = V[:, fb_ids].min(axis=1)
            use_fb = np.isnan(base).any(axis=-1) | (bvis < fvis - 0.3)
            base = np.where(use_fb[:, None], fb, base)
            bvis = np.where(use_fb, fvis, bvis)
        origin, ovis = _eval_joint(s["origin"], P, V, cache, spec)
        out = base + float(s["alpha"]) * (base - origin)
        vis = np.minimum(bvis, ovis)
    else:
        raise ValueError(f"unknown joint type {kind!r} for {name}")
    cache[name] = (out, vis)
    return cache[name]


def map_landmarks(world, image, visibility, joint_order=None, joint_spec=None):
    """Map 33 landmarks to the joint order.

    world (T,33,3), image (T,33,2+) normalised, visibility (T,33).
    Returns joints (T,J,5) float64 and vis (T,J). Missing input is NaN.
    """
    joint_order = joint_order or C.JOINT_ORDER
    joint_spec = joint_spec or C.JOINT_SPEC
    P = np.concatenate([np.asarray(world, float)[..., :3],
                        np.asarray(image, float)[..., :2]], axis=-1)
    V = np.asarray(visibility, float)
    cache: dict = {}
    vals, viss = [], []
    for n in joint_order:
        v, vis = _eval_joint(n, P, V, cache, joint_spec)
        vals.append(v)
        viss.append(vis)
    return np.stack(vals, axis=1), np.stack(viss, axis=1)


def convert_axes(skel, axes="camera", scale=1.0, mirror_x=False, root_relative=True,
                 joint_order=None):
    """Convert world xyz (metres, MediaPipe axes) into the output convention.

    skel (T,J,3). Applies: optional root subtraction (pelvis), axis rotation
    preset, optional x mirror, then unit scale.
    """
    joint_order = joint_order or C.JOINT_ORDER
    out = np.asarray(skel, float).copy()
    if root_relative:
        out = out - out[:, joint_order.index("pelvis"):joint_order.index("pelvis") + 1]
    R = np.asarray(C.AXIS_PRESETS[axes], float)
    out = out @ R.T
    if mirror_x:
        out[..., 0] *= -1
    return out * scale
