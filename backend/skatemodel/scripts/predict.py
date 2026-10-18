"""Run a trained model on one skeleton (.npz in FineFS format, e.g. produced by ../convert).

    python scripts/predict.py --ckpt runs/x/best.pt --npz clip.npz --program-type fs [--out pred.json]
    python scripts/predict.py --ckpt runs/mmfs_h100/final_model.pt --npz nXX_pYY.npy --format mmfs
    python scripts/predict.py --ckpt runs/thunder_l40/final_model.pt --npz clip.raw.npz --format mediapipe
        (clip.raw.npz from convert --save-raw on a video already at the model fps, e.g. 30)
"""
import argparse
import json
import os
import sys

import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skatemodel.data import finefs_io  # noqa: E402
from skatemodel.inference import predict_program  # noqa: E402
from skatemodel.models import build_model  # noqa: E402
from skatemodel.train import class_codes_for  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--ckpt", required=True)
ap.add_argument("--npz", required=True)
ap.add_argument("--program-type", default="fs", choices=["sp", "fs", "unk"])
ap.add_argument("--fps", type=float, default=None, help="default: training fps from the checkpoint")
ap.add_argument("--format", choices=["finefs", "mmfs", "h36m", "mediapipe"], default="finefs",
                help="finefs: .npz (H36M 3D); mmfs: raw COCO-17 2D+conf .npy; h36m: (T,17,3) .npy; mediapipe: convert --save-raw .raw.npz "
                     "(2D, use with MMFS-trained checkpoints)")
ap.add_argument("--out", default=None)
ap.add_argument("--threshold", type=float, default=None, help="min element score (default: checkpoint's final_thr)")
ap.add_argument("--save-frame-probs", action="store_true", help="keep frame_probs (T,5) in the output JSON")
a = ap.parse_args()

dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
st = torch.load(a.ckpt, map_location="cpu", weights_only=False)
model = build_model(st["cfg"]).to(dev)
model.load_state_dict(st["model"])
if st["cfg"]["data"].get("format") == "mmfs" and a.format in ("finefs", "h36m"):
    print(f"warning: checkpoint was trained on 2D MMFS skeletons; --format {a.format} feeds 3D input "
          "and gives near-constant output. Use --format mediapipe or mmfs.", file=sys.stderr)
if a.format == "finefs":
    pos = finefs_io.load_skeleton(a.npz)
elif a.format == "mediapipe":
    from skatemodel.data.mmfs import coco2d_to_h36m, mediapipe_raw_to_coco2d
    pos = coco2d_to_h36m(mediapipe_raw_to_coco2d(a.npz))
else:
    import numpy as np
    from skatemodel.data.mmfs import coco2d_to_h36m
    raw = np.load(a.npz, allow_pickle=False).astype("float32")
    pos = coco2d_to_h36m(raw) if a.format == "mmfs" else raw
fps = a.fps or float(st["cfg"]["data"].get("fps", 25))
infer = {**(st["cfg"].get("infer") or {}), **({"final_thr": a.threshold} if a.threshold is not None else {})}
res = predict_program(model, pos, a.program_type, dev, fps, infer, st.get("priors"),
                      class_codes=class_codes_for(st["cfg"]))
if a.save_frame_probs:
    res["frame_probs"] = [[round(float(v), 3) for v in row] for row in res["frame_probs"]]
else:
    res.pop("frame_probs")
print(f"predicted TES {res['tes']:.2f}")
for e in res["elements"]:
    ph = e.get("physics", {})
    extra = (f" air={ph['air_time_s']:.2f}s h={ph['height_m']:.2f}m rev={ph['revolutions']:.1f}"
             if ph.get("valid") else "")
    print(f"  {e['start_s']:6.1f}-{e['end_s']:6.1f}s {e['code']:<16s} bv={e['bv']:5.2f} goe={e['goe']:+.2f}{extra}")
if a.out:
    with open(a.out, "w") as f:
        json.dump(res, f, indent=1)
