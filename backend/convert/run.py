"""CLI: python -m convert.run video.mp4 -o out.npz   (or a folder for batch mode)."""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from . import config as C
from .extract import RawLandmarks, extract_landmarks
from .pipeline import raw_to_coco2d, raw_to_output, save_npz

VIDEO_EXT = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def build_parser():
    p = argparse.ArgumentParser(prog="python -m convert.run", description=__doc__)
    p.add_argument("input", help="video file, or a folder of videos (batch mode)")
    p.add_argument("-o", "--output", help="output .npz (file) or directory (batch)")
    p.add_argument("--model", default="heavy", help="lite|full|heavy or path to .task")
    p.add_argument("--format", default="finefs", choices=["finefs", "coco2d"],
                   help="finefs: 3D .npz (default); coco2d: (T,17,3) 2D pixel .npy for MMFS-trained models")
    p.add_argument("--fps", type=float, default=None, help="default 25 (finefs) / 30 (coco2d)")
    p.add_argument("--min-visibility", type=float, default=0.4)
    p.add_argument("--max-gap", type=int, default=8, help="max gap (frames) to interpolate")
    p.add_argument("--gap-method", default="pchip", choices=["linear", "pchip", "cubic"])
    p.add_argument("--smoothing", default="one_euro", choices=["one_euro", "savgol", "none"])
    p.add_argument("--min-cutoff", type=float, default=2.5)
    p.add_argument("--beta", type=float, default=5.0)
    p.add_argument("--savgol-window", type=int, default=7)
    p.add_argument("--savgol-order", type=int, default=3)
    p.add_argument("--no-swap-fix", action="store_true")
    p.add_argument("--no-bone-fix", action="store_true")
    p.add_argument("--axes", default="camera", choices=list(C.AXIS_PRESETS))
    p.add_argument("--scale", type=float, default=1.0, help="1=metres, 1000=mm")
    p.add_argument("--mirror-x", action="store_true")
    p.add_argument("--no-root-relative", action="store_true")
    p.add_argument("--save-raw", metavar="DIR", help="also cache raw MediaPipe output (.raw.npz)")
    p.add_argument("--from-raw", action="store_true",
                   help="input is a cached .raw.npz (skip MediaPipe)")
    p.add_argument("--skip-existing", action="store_true")
    return p


def make_config(a) -> C.PipelineConfig:
    return C.PipelineConfig(
        model=a.model, target_fps=a.fps, min_visibility=a.min_visibility,
        max_gap=a.max_gap, gap_method=a.gap_method, smoothing=a.smoothing,
        one_euro_min_cutoff=a.min_cutoff, one_euro_beta=a.beta,
        savgol_window=a.savgol_window, savgol_polyorder=a.savgol_order,
        fix_swaps=not a.no_swap_fix, fix_bones=not a.no_bone_fix, axes=a.axes,
        scale=a.scale, mirror_x=a.mirror_x, root_relative=not a.no_root_relative)


def convert_one(src: Path, dst: Path, cfg, args):
    t0 = time.time()
    if args.from_raw:
        raw = RawLandmarks.load(src)
    else:
        raw = extract_landmarks(src, cfg.model, cfg.min_detection_confidence,
                                cfg.min_tracking_confidence, progress=True)
        if args.save_raw:
            Path(args.save_raw).mkdir(parents=True, exist_ok=True)
            raw.save(Path(args.save_raw) / (src.stem + ".raw.npz"))
    det = float((raw.visibility.max(axis=1) > 0).mean())
    if args.format == "coco2d":
        out = raw_to_coco2d(raw, cfg.target_fps)
        dst.parent.mkdir(parents=True, exist_ok=True)
        np.save(dst, out)
        print(f"{src.name} -> {dst}  T={len(out)} @ {cfg.target_fps:g} fps detected={det:.0%} "
              f"mean-conf={out[..., 2].mean():.2f} ({time.time() - t0:.1f}s)")
        return
    out = raw_to_output(raw, cfg)
    save_npz(dst, out)
    print(f"{src.name} -> {dst}  T={out['skeleton'].shape[0]} "
          f"detected={det:.0%} valid-joints={out['mask'].mean():.0%} "
          f"({time.time() - t0:.1f}s)")


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.fps is None:
        args.fps = 30.0 if args.format == "coco2d" else 25.0
    ext = ".npy" if args.format == "coco2d" else ".npz"
    cfg = make_config(args)
    src = Path(args.input)
    if src.is_dir():
        out_dir = Path(args.output or (src / "skeletons"))
        out_dir.mkdir(parents=True, exist_ok=True)
        pattern = ".raw.npz" if args.from_raw else None
        files = sorted(f for f in src.iterdir() if (f.name.endswith(".raw.npz") if pattern
                       else f.suffix.lower() in VIDEO_EXT))
        if not files:
            print("no input files found", file=sys.stderr)
            return 1
        fails = 0
        for f in files:
            stem = f.name[:-len(".raw.npz")] if pattern else f.stem
            dst = out_dir / (stem + ext)
            if args.skip_existing and dst.exists():
                continue
            try:
                convert_one(f, dst, cfg, args)
            except Exception as e:  # keep batch going
                fails += 1
                print(f"FAILED {f.name}: {e}", file=sys.stderr)
        return 1 if fails else 0
    dst = Path(args.output) if args.output else src.with_suffix(ext)
    convert_one(src, dst, cfg, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
