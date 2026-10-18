"""Sanity-check rendering: python -m convert.viz out.npz [--video v.mp4] -o viz.mp4

Modes: overlay (2D skeleton on the video; needs --video), 3d (matplotlib 3D
plot), both (side by side; needs --video). Masked (long-gap) joints are drawn grey.
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from . import config as C


def _edges(names):
    idx = {n: i for i, n in enumerate(names)}
    return [(idx[p], idx[c]) for p, c in C.BONES if p in idx and c in idx]


def _side_color(name):
    if name.startswith("l_"):
        return (255, 128, 0)   # BGR blue-ish
    if name.startswith("r_"):
        return (0, 128, 255)   # orange-ish
    return (0, 220, 0)


def draw_overlay(frame, j2d, mask, names, edges):
    import cv2
    h, w = frame.shape[:2]
    pts = (j2d * np.array([w, h])).astype(int)
    for a, b in edges:
        ok = mask[a] and mask[b]
        col = _side_color(names[b]) if ok else (128, 128, 128)
        cv2.line(frame, tuple(pts[a]), tuple(pts[b]), col, 2, cv2.LINE_AA)
    for i, p in enumerate(pts):
        cv2.circle(frame, tuple(p), 4, _side_color(names[i]) if mask[i] else (128, 128, 128), -1)
    return frame


def render_3d_frame(fig, ax, pose, mask, names, edges, lim, elev, azim, fps_text=""):
    ax.clear()
    # plot with y/z permuted so that the displayed up axis is visually up
    xs, ys, zs = pose[:, 0], pose[:, 2], -pose[:, 1]
    for a, b in edges:
        col = np.array(_side_color(names[b]))[::-1] / 255.0 if (mask[a] and mask[b]) else "gray"
        ax.plot([xs[a], xs[b]], [ys[a], ys[b]], [zs[a], zs[b]], color=col, lw=2)
    ax.scatter(xs, ys, zs, c="k", s=8)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_zlim(-lim, lim)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=elev, azim=azim)
    ax.set_xlabel("x"); ax.set_ylabel("z (depth)"); ax.set_zlabel("-y (up)")
    ax.set_title(fps_text)
    fig.canvas.draw()
    return np.asarray(fig.canvas.buffer_rgba())[..., :3][..., ::-1].copy()


def main(argv=None):
    import cv2
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("npz")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--video")
    ap.add_argument("--mode", choices=["overlay", "3d", "both"], default=None)
    ap.add_argument("--elev", type=float, default=15)
    ap.add_argument("--azim", type=float, default=-70)
    a = ap.parse_args(argv)

    d = np.load(a.npz, allow_pickle=False)
    skel, mask, j2d = d["skeleton"], d["mask"].astype(bool), d["joints_2d"]
    names = [str(n) for n in d["joint_names"]]
    fps = float(d["fps"])
    T = skel.shape[0]
    edges = _edges(names)
    mode = a.mode or ("both" if a.video else "3d")
    if mode in ("overlay", "both") and not a.video:
        ap.error("--video required for overlay/both")

    cap = None
    if a.video:
        cap = cv2.VideoCapture(a.video)
        times = d["times"]
        meta = json.loads(str(d["metadata_json"]))
        # we resampled to 25 fps from t0 = first frame timestamp (usually 0)

    lim = float(np.nanmax(np.abs(skel))) * 1.1 + 1e-3
    fig = plt.figure(figsize=(5, 5), dpi=100)
    ax = fig.add_subplot(111, projection="3d")
    writer = None
    for t in range(T):
        panels = []
        if mode in ("overlay", "both"):
            cap.set(cv2.CAP_PROP_POS_MSEC, float(times[t]) * 1000.0)
            ok, frame = cap.read()
            if not ok:
                frame = np.zeros((480, 640, 3), np.uint8)
            panels.append(draw_overlay(frame, j2d[t], mask[t], names, edges))
        if mode in ("3d", "both"):
            panels.append(render_3d_frame(fig, ax, skel[t], mask[t], names, edges, lim,
                                          a.elev, a.azim, f"t={t / fps:.2f}s"))
        if len(panels) == 2:
            h = panels[0].shape[0]
            p3 = cv2.resize(panels[1], (int(panels[1].shape[1] * h / panels[1].shape[0]), h))
            frame_out = np.hstack([panels[0], p3])
        else:
            frame_out = panels[0]
        if writer is None:
            hh, ww = frame_out.shape[:2]
            writer = cv2.VideoWriter(a.output, cv2.VideoWriter_fourcc(*"mp4v"), fps, (ww, hh))
        writer.write(frame_out)
    writer.release()
    print(f"wrote {a.output} ({T} frames, mode={mode})")


if __name__ == "__main__":
    sys.exit(main())
