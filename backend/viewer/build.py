#!/usr/bin/env python3
"""Build a self-contained skeleton+timeline viewer for one clip.

  python viewer/build.py VIDEO -o outdir [--ckpt CKPT] [--npy clip.npy] [--pred pred.json]
"""
import argparse, json, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CKPT = ROOT / "skatemodel/runs/thunder_l40/final_model.pt"
FPS = 30


def stage(name, t0):
    print(f"[{name}] {time.time() - t0:.1f}s", flush=True)


def run(cmd):
    print("$", " ".join(map(str, cmd)), flush=True)
    subprocess.run(list(map(str, cmd)), check=True, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("-o", "--outdir", required=True)
    ap.add_argument("--ckpt", default=str(CKPT))
    ap.add_argument("--npy", help="reuse existing coco2d .npy (skip convert)")
    ap.add_argument("--pred", help="reuse existing predict JSON (must contain frame_probs)")
    ap.add_argument("--program-type", default="unk")
    ap.add_argument("--threshold", type=float, default=0.10, help="min element score kept in the data (the page slider filters further)")
    a = ap.parse_args()
    out = Path(a.outdir).resolve(); out.mkdir(parents=True, exist_ok=True)
    video = Path(a.video).expanduser().resolve()

    t = time.time()
    if a.npy:
        npy = Path(a.npy).resolve()
    else:
        npy = out / "clip.npy"
        run([ROOT / "convert/.venv/bin/python", "-m", "convert.run", video, "-o", npy, "--format", "coco2d"])
    stage("convert", t)

    t = time.time()
    if a.pred:
        pred_path = Path(a.pred).resolve()
    else:
        pred_path = out / "pred.json"
        run([ROOT / "skatemodel/.venv/bin/python", "skatemodel/scripts/predict.py", "--ckpt", a.ckpt,
             "--npz", npy, "--format", "mmfs", "--program-type", a.program_type,
             "--out", pred_path, "--save-frame-probs", "--threshold", a.threshold])
    stage("predict", t)

    t = time.time()
    # ffmpeg autorotates (display matrix) while transcoding, so output pixels are the displayed pixels.
    run(["ffmpeg", "-y", "-v", "error", "-i", video, "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-preset", "fast", "-crf", "23", "-movflags", "+faststart", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
         out / "video.mp4"])
    stage("transcode", t)

    t = time.time()
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                         "stream=width,height", "-of", "json", out / "video.mp4"],
                        capture_output=True, text=True, check=True)
    st = json.loads(pr.stdout)["streams"][0]
    import numpy as np
    sk = np.load(npy)
    pred = json.load(open(pred_path))
    if "frame_probs" not in pred:
        sys.exit("pred JSON has no frame_probs; rerun predict with --save-frame-probs")
    data = {
        "name": video.stem, "fps": FPS, "width": st["width"], "height": st["height"],
        "skeleton": [[[round(float(v), 1), round(float(y), 1), round(float(c), 2)] for v, y, c in f] for f in sk],
        "elements": pred["elements"], "tes": pred["tes"],
        "classes": ["none", "jump", "spin", "step", "transition"],
        "frame_probs": pred["frame_probs"],
    }
    js = json.dumps(data, separators=(",", ":"))
    (out / "data.json").write_text(js)
    tpl = (Path(__file__).parent / "index.html").read_text()
    (out / "index.html").write_text(tpl.replace("/*__DATA__*/null", js.replace("</", "<\\/")))
    stage("write", t)
    print(f"video {st['width']}x{st['height']}, skeleton {sk.shape}; open {out/'index.html'}")


main()
