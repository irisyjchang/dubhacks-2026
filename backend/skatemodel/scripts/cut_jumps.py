"""Physics jump cutter: detect takeoff/landing in a program and export each jump as its own clip.

Inputs: MMFS raw program (nXX_pYY.npy, COCO-17 2D + conf), a FineFS-format .npz (H36M 3D), or
an H36M-layout .npy (T,17,3). Detection: both ankles above the local ice level (pelvis/ankle
height) for a plausible flight time; revolutions from rotation velocity (3D yaw or 2D half-turns).
RECOMMENDED: --ckpt (model finds jump segments; physics refines takeoff/landing/air time).
Physics-only on 2D MMFS keypoints is weak (60 programs: jump recall 0.31, precision 0.47, revolution
count MAE 0.84) because camera motion and 2D projection make ankle height / rotation noisy.

    python scripts/cut_jumps.py --input prog.npy --format mmfs --out jumps/ [--ckpt best.pt] [--pre 0.6 --post 0.6]
"""
import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skatemodel.data import finefs_io  # noqa: E402
from skatemodel.data.features import apply_canonical, canonical_transform  # noqa: E402
from skatemodel.data.mmfs import coco2d_to_h36m  # noqa: E402
from skatemodel.inference import BODY_M_2D  # noqa: E402
from skatemodel.physics import analyze_jump, detect_air_phases, is_2d  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--input", required=True)
ap.add_argument("--format", choices=["mmfs", "finefs", "h36m"], default="mmfs")
ap.add_argument("--fps", type=float, default=None)
ap.add_argument("--out", required=True)
ap.add_argument("--pre", type=float, default=0.6, help="seconds kept before takeoff")
ap.add_argument("--post", type=float, default=0.6, help="seconds kept after landing")
ap.add_argument("--foot-thr", type=float, default=0.08, help="metres above ice for 'airborne'")
ap.add_argument("--ckpt", default=None, help="optional model: only keep jumps inside detected jump segments")
a = ap.parse_args()

if a.format == "finefs":
    raw = finefs_io.load_skeleton(a.input)
    pos = raw
    fps = a.fps or finefs_io.FPS
else:
    raw = np.load(a.input, allow_pickle=False).astype(np.float32)
    pos = coco2d_to_h36m(raw) if a.format == "mmfs" else raw
    fps = a.fps or (30.0 if a.format == "mmfs" else finefs_io.FPS)

R, scale = canonical_transform(pos)
pos_c = apply_canonical(pos, R, scale)
pos_m = pos_c * (BODY_M_2D if is_2d(pos) else scale)

if a.ckpt:
    import torch
    from skatemodel.inference import predict_program
    from skatemodel.models import build_model
    from skatemodel.train import class_codes_for
    st = torch.load(a.ckpt, map_location="cpu", weights_only=False)
    model = build_model(st["cfg"])
    model.load_state_dict(st["model"])
    res = predict_program(model, pos, "unk", torch.device("cpu"), fps, st["cfg"].get("infer"),
                          st.get("priors"), class_codes=class_codes_for(st["cfg"]))
    jumps = []
    for e in res["elements"]:
        if e["kind"] == "jump":
            ph = analyze_jump(pos_m, int(e["start_s"] * fps), int(e["end_s"] * fps), fps, a.foot_thr)
            if ph.get("valid"):
                ph["model_code"] = e["code"]
                jumps.append(ph)
else:
    jumps = detect_air_phases(pos_m, fps, a.foot_thr)

os.makedirs(a.out, exist_ok=True)
stem = os.path.splitext(os.path.basename(a.input))[0]
meta = []
for k, j in enumerate(jumps):
    s = max(0, j["takeoff_frame"] - int(a.pre * fps))
    e = min(len(raw), j["landing_frame"] + int(a.post * fps))
    path = os.path.join(a.out, f"{stem}_jump{k:02d}.npy")
    np.save(path, raw[s:e])
    meta.append({**j, "clip": os.path.basename(path), "clip_start": s, "clip_end": e, "fps": fps})
    print(f"jump {k:2d}: t={j['takeoff_frame'] / fps:7.2f}s air={j['air_time_s']:.2f}s "
          f"h={j['height_m']:.2f}m rev={j['revolutions']:.1f} {j.get('model_code', '')}")
with open(os.path.join(a.out, f"{stem}_jumps.json"), "w") as f:
    json.dump(meta, f, indent=1)
print(f"{len(meta)} jumps -> {a.out}")
