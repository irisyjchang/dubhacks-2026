# dubhacks-backend — figure skating video → elements + TES

Pipeline: **video → pose skeleton (MediaPipe, `convert/`) → temporal model (`skatemodel/`) → detected elements (jumps / spins / step sequences) with base value, GOE, and a predicted Technical Element Score (TES)**. `viewer/` renders the results over the video.

```
convert/     video -> MediaPipe Pose -> skeleton files (see convert/README.md)
skatemodel/  model code, configs, training scripts, inference (scripts/predict.py)
  runs/thunder_l40/final_model.pt   <- the trained model (7.1M params, 2D MMFS skeletons, 30 fps)
  runs/thunder_l40/final_metrics.json
viewer/      HTML viewer + upload UI (see viewer/README.md)
outputs/     example results on our own clips
docs/        Hyak / Thunder (GPU cluster) guides
```

Not in git (too big): `data/` (FineFS / MMFS datasets), `skatemodel/data/mmfs_cache*`, intermediate checkpoints, virtualenvs.

## Coaching prototype

The [coaching prototype](coaching/README.md) adds a simple upload interface, MediaPipe body points, optional Perceptron person boxes, Gemini move suggestions with NVIDIA fallback, concise feedback, selected ISU rule checks and annotated video. Automated tests are included.

Follow [setup and API-key instructions](coaching/README.md#setup), then run commands from `coaching/`. Videos, generated reports, model downloads, credentials and Python environments are kept outside Git.

## Setup

Python 3.12 (mediapipe wheels lag newer Pythons). Two venvs:

```bash
# pose extraction
cd convert && python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt && cd ..
# model
cd skatemodel && python3.12 -m venv .venv && .venv/bin/pip install torch && .venv/bin/pip install -r requirements.txt && cd ..
```
The MediaPipe pose model (`convert/models/pose_landmarker_heavy.task`) is included; it is re-downloaded automatically if missing.

## Running inference

Easiest: the viewer does everything (convert + predict + overlay):

```bash
python viewer/build.py my_clip.mp4 -o outputs/viewer/my_clip
open outputs/viewer/my_clip/index.html
# or the drag-and-drop UI:
convert/.venv/bin/python viewer/app.py      # http://localhost:8000
```

Manually, step by step (run from the repo root):

```bash
# 1. extract pose; the model was trained at 30 fps, so give it 30 fps video
#    (ffmpeg -i in.mov -r 30 clip_30fps.mp4 if needed)
convert/.venv/bin/python -m convert.run clip_30fps.mp4 -o outputs/clip/skel.npz --save-raw outputs/clip/

# 2. run the model on the raw MediaPipe output
cd skatemodel
.venv/bin/python scripts/predict.py \
    --ckpt runs/thunder_l40/final_model.pt \
    --npz ../outputs/clip/clip_30fps.raw.npz --format mediapipe \
    --program-type fs --out ../outputs/clip/prediction.json
```

Options:
- `--format mediapipe` — use this for videos (the shipped model is trained on **2D** skeletons; `finefs`/`h36m` 3D inputs give near-constant garbage and print a warning). `--format mmfs` takes an MMFS COCO-17 `.npy`.
- `--program-type sp|fs|unk` — short program / free skate / unknown; only changes the max number of elements of each kind kept (SP: 3 jumps, 3 spins, 1 step; FS: 7/3/2).
- `--threshold 0.3` — minimum detection score to keep an element (lower → more, less confident elements).
- `--save-frame-probs` — also write per-frame class probabilities (needed by the viewer).
- Runs on CPU fine; uses CUDA if available.

## What the output means

Console (illustrative):
```
predicted TES 2.33
     0.0-   6.6s FSSp3            bv= 2.60 goe=-0.27
     3.1-   4.0s 3Lz              bv= 5.90 goe=+0.80 air=0.52s h=0.33m rev=2.9
```

`prediction.json`:

| field | meaning |
|---|---|
| `tes` | predicted Technical Element Score = Σ (bv + goe) over all elements (ISU scale) |
| `elements[]` | detected elements in time order |
| `code` | ISU element code, e.g. `3Lz` triple Lutz, `3F+3T` combo, `2A` double Axel, `FSSp3` flying sit spin level 3, `CCoSp4` change combination spin L4, `StSq3` step sequence L3 |
| `kind` | `jump`, `spin`, or `step` |
| `bv` | base value from the ISU scale-of-values table for that code (incl. 10% second-half bonus if `bonus`) |
| `goe` | predicted Grade of Execution in points (model predicts −5…+5 grade, scaled by bv/10) |
| `fall` | model thinks the skater fell on this element |
| `bonus` | element is in the second half of the program (jump bonus) |
| `start_s`, `end_s` | element time span in seconds |
| `det_score` | detection confidence 0–1 (elements below `--threshold` are dropped) |
| `physics` (jumps only) | estimated from the skeleton: `air_time_s`, `height_m` (= g·t²/8; on 2D input this assumes a 1.35 m body length, so treat as rough), `revolutions`, `rot_speed_rps`, `takeoff_frame`/`landing_frame`. `valid: false` = couldn't find a clear flight phase |
| `frame_probs` | (with `--save-frame-probs`) per-frame probabilities for `[none, jump, spin, step, transition]` |

Caveats: it is a single-person pose model, so crowded/far shots and inverted spin positions are weak spots; codes/levels on short phone clips are a best guess and TES is only meaningful for full programs.

## Model performance (held-out MMFS test set, `runs/thunder_l40/final_metrics.json`)

| metric | value |
|---|---|
| element segmentation mAP@0.5 (jump / spin / step) | 0.72 (0.77 / 0.80 / 0.60) |
| frame accuracy | 0.84 |
| jump type / rotation accuracy | 98.5% / 97.1% |
| GOE MAE | 0.41 pts |
| TES MAE / Spearman | 2.99 pts / 0.93 |
| TES MAE with ground-truth segments | 1.10 pts |

`noisy/` = trained with MediaPipe-style noise augmentation (this is `final_model.pt`); `clean/` = without. Under-rotation (`ur`) prediction does not work (3% acc).

## Training

See `skatemodel/configs/*.yaml`, `docs/hyak_guide.md`, `docs/thunder_guide.md`, and `skatemodel/thunder/README.md`. Short version: build the cache with `skatemodel/scripts/build_mmfs_cache.py`, then `python -m skatemodel.train --config configs/mmfs_h100_30min.yaml`.
