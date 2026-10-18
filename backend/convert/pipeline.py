"""Raw landmarks -> cleaned FineFS-format skeleton arrays."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import config as C
from . import skeleton, swaps, temporal
from .extract import RawLandmarks


def process_landmarks(times, world, image, visibility, cfg: C.PipelineConfig | None = None,
                      width=0, height=0, source="", src_fps=0.0) -> dict:
    """Run mapping, swap fix, resample, gap fill, smoothing, bone fix, axes.

    Inputs may contain NaN (undetected frames). Returns dict of output arrays.
    """
    cfg = cfg or C.PipelineConfig()
    order = C.JOINT_ORDER
    J = len(order)

    X, vis = skeleton.map_landmarks(world, image, visibility)          # (T,J,5), (T,J)

    # low-visibility joints become missing
    X[vis < cfg.min_visibility] = np.nan
    X[np.isnan(X).any(axis=-1)] = np.nan

    swap_info = {}
    if cfg.fix_swaps:
        X, swap_info = swaps.fix_lr_swaps(X, order, penalty=cfg.swap_penalty,
                                          prior=cfg.swap_prior,
                                          bone_weight=cfg.swap_bone_weight)
        # visibility follows the joints
        idx = {n: i for i, n in enumerate(order)}
        for name, path in swap_info.items():
            for r, l in C.SWAP_GROUPS[name]["pairs"]:
                ri, li = idx[r], idx[l]
                tmp = vis[path, ri].copy()
                vis[path, ri] = vis[path, li]
                vis[path, li] = tmp

    # resample to target fps (gaps preserved as NaN)
    t_out, X, vis = temporal.resample(times, X, cfg.target_fps, vis=vis)
    observed = ~np.isnan(X).any(axis=-1)
    vis = np.where(observed, vis, 0.0)

    # gap fill
    X, mask = temporal.fill_gaps(X, cfg.max_gap, cfg.gap_method)

    # smooth
    X = temporal.smooth(X, cfg.smoothing, cfg.target_fps, cfg)

    # bone-length consistency
    bl = None
    if cfg.fix_bones:
        bl = temporal.bone_lengths(X, mask, order, symmetric=cfg.symmetric_bones)
        X = temporal.enforce_bone_lengths(X, bl, order)

    # axes / units (last: rigid + scale commute with all steps above)
    skel = skeleton.convert_axes(X[..., :3], cfg.axes, cfg.scale, cfg.mirror_x,
                                 cfg.root_relative, order)
    joints_2d = X[..., 3:5]

    # global trajectory features from image coords
    pelvis_2d = joints_2d[:, order.index("pelvis")]
    m = mask[..., None]
    ys = np.where(m[..., 0], joints_2d[..., 1], np.nan)
    with np.errstate(all="ignore"):
        body_h = np.nanmax(ys, axis=1) - np.nanmin(ys, axis=1)
    body_h = _ffill_1d(body_h)

    frame_mask_any = mask.any(axis=1)
    jconf = np.where(mask, vis, 0.0)
    confidence = jconf.mean(axis=1)
    confidence[~frame_mask_any] = 0.0

    meta = {
        "source": str(source), "width": int(width), "height": int(height),
        "src_fps": float(src_fps), "joint_order": list(order),
        "config": cfg.to_dict(), "axes_note": _axes_note(cfg),
        "bone_lengths": None if bl is None else {f"{p}-{c}": v for (p, c), v in bl.items()},
        "swapped_frames": {k: int(v.sum()) for k, v in swap_info.items()},
        "joint_spec": C.JOINT_SPEC,
        "joint_order_confirmed_finefs": False,
    }
    return {
        "skeleton": skel.astype(np.float32),
        "mask": mask.astype(np.uint8),
        "confidence": confidence.astype(np.float32),
        "pelvis_2d": pelvis_2d.astype(np.float32),
        "body_height": body_h.astype(np.float32),
        "joints_2d": joints_2d.astype(np.float32),
        "joint_confidence": jconf.astype(np.float32),
        "times": (t_out - t_out[0]).astype(np.float32),
        "fps": np.float32(cfg.target_fps),
        "joint_names": np.array(order),
        "metadata_json": np.array(json.dumps(meta)),
    }


def _ffill_1d(x):
    x = x.copy()
    ok = ~np.isnan(x)
    if not ok.any():
        return np.zeros_like(x)
    idx = np.where(ok, np.arange(len(x)), 0)
    np.maximum.accumulate(idx, out=idx)
    x = x[idx]
    x[: np.argmax(ok)] = x[np.argmax(ok)]
    return x


def _axes_note(cfg):
    return (f"axes preset '{cfg.axes}': " + {
        "camera": "x right, y down, z away from camera (OpenCV/H3.6M camera-like)",
        "camera_y_up": "x right, y up, z toward camera",
    }.get(cfg.axes, "custom") +
        f"; units = metres * {cfg.scale}; pelvis-centred={cfg.root_relative}; mirror_x={cfg.mirror_x}")


def raw_to_output(raw: RawLandmarks, cfg=None) -> dict:
    return process_landmarks(raw.times, raw.world, raw.image, raw.visibility, cfg,
                             raw.width, raw.height, raw.source, raw.src_fps)


MEDIAPIPE_TO_COCO = [0, 2, 5, 7, 8, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]


def raw_to_coco2d(raw: RawLandmarks, fps: float = 30.0) -> np.ndarray:
    """(T,17,3) COCO-17 [x, y, conf] in pixels at ``fps`` -- the MMFS input format
    (load with skatemodel ``predict.py --format mmfs``). Undetected frames get conf 0."""
    img = raw.image[:, MEDIAPIPE_TO_COCO, :2] * np.array([raw.width, raw.height], float)
    _, img, vis = temporal.resample(raw.times, img, fps, vis=raw.visibility[:, MEDIAPIPE_TO_COCO])
    out = np.concatenate([img, vis[..., None]], -1)
    out[~np.isfinite(out).all(-1)] = 0
    return out.astype(np.float32)


def save_npz(path, out: dict):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **out)
