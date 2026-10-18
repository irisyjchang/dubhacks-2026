"""CLI: python -m convert.split_clips routine.mp4 -o clips_dir [--clip-len 10 --overlap 2 --fps 2 --height 480]

Split a skating routine into short overlapping, downscaled mp4 clips for the
Perceptron Mk1.5 vision API (36,864-token context shared with output, max output 8,192).
Writes <out>/manifest.json mapping each clip to routine start/end seconds.

Token budget: the Mk1.5 docs don't publish a per-frame token cost. They say to measure
usage.prompt_tokens instead. The defaults below are assumptions (10s @ 2fps = 20 frames
at 480p). Measure one clip and tune --clip-len/--fps/--height to stay under ~28k input.
The docs do give a cap of 256 media units per request, and each frame counts as one.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path


def build_parser():
    p = argparse.ArgumentParser(prog="python -m convert.split_clips", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="routine video file")
    p.add_argument("-o", "--output", help="output dir (default: <input stem>_clips next to input)")
    p.add_argument("--clip-len", type=float, default=10.0, help="clip length, seconds")
    p.add_argument("--overlap", type=float, default=2.0, help="overlap between clips, seconds")
    p.add_argument("--fps", type=float, default=2.0, help="output frame rate")
    p.add_argument("--height", type=int, default=480, help="output height px (width keeps aspect)")
    p.add_argument("--crf", type=int, default=28, help="x264 quality (higher = smaller)")
    p.add_argument("--min-tail", type=float, default=1.0,
                   help="drop a final clip shorter than this many seconds")
    return p


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True).stdout.strip()
    return float(out)


def windows(duration: float, clip_len: float, overlap: float, min_tail: float):
    """Fixed windows [start, end) with a stride of clip_len - overlap."""
    stride = clip_len - overlap
    if stride <= 0:
        raise ValueError("--overlap must be smaller than --clip-len")
    out, start = [], 0.0
    while start < duration:
        end = min(start + clip_len, duration)
        if out and end - start < min_tail:
            break
        out.append((round(start, 3), round(end, 3)))
        if end >= duration:
            break
        start += stride
    return out


def cut(src: Path, dst: Path, start: float, end: float, fps: float, height: int, crf: int):
    vf = f"fps={fps},scale=-2:{height}"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", str(src),
         "-t", f"{end - start:.3f}", "-vf", vf, "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
        check=True)


def main(argv=None):
    a = build_parser().parse_args(argv)
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        sys.exit("ffmpeg/ffprobe not found on PATH")
    src = Path(a.input)
    out_dir = Path(a.output) if a.output else src.with_name(f"{src.stem}_clips")
    out_dir.mkdir(parents=True, exist_ok=True)

    duration = probe_duration(src)
    wins = windows(duration, a.clip_len, a.overlap, a.min_tail)
    pad = max(3, int(math.log10(len(wins))) + 1)
    clips = []
    for i, (s, e) in enumerate(wins):
        dst = out_dir / f"{src.stem}_{i:0{pad}d}.mp4"
        cut(src, dst, s, e, a.fps, a.height, a.crf)
        clips.append({"index": i, "path": dst.name, "start": s, "end": e})
        print(f"[{i + 1}/{len(wins)}] {dst.name}  {s:.1f}-{e:.1f}s")

    manifest = {
        "source": str(src.resolve()), "duration": round(duration, 3),
        "clip_len": a.clip_len, "overlap": a.overlap, "fps": a.fps, "height": a.height,
        "clips": clips,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(clips)} clips + manifest.json to {out_dir}")


if __name__ == "__main__":
    main()
