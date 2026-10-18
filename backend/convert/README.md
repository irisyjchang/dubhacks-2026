# convert: video -> MediaPipe Pose -> FineFS-format skeletons

Produces 17-joint, 25 fps skeleton `.npz` files from video.

## Setup
```
cd convert
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
(Use Python 3.12; mediapipe wheels lag the newest Python.) The heavy model is
auto-downloaded to `convert/models/` on first use (`--model lite|full|heavy|path.task`).

## Usage (run from the directory CONTAINING `convert/`)
```
convert/.venv/bin/python -m convert.run video.mp4 -o out.npz
convert/.venv/bin/python -m convert.run videos_dir/ -o out_dir/ [--skip-existing]   # batch
convert/.venv/bin/python -m convert.run video.mp4 -o out.npz --save-raw raw/        # cache raw MediaPipe output
convert/.venv/bin/python -m convert.run raw/video.raw.npz --from-raw -o out.npz     # re-tune without re-running MediaPipe
convert/.venv/bin/python -m convert.run video.mp4 -o out.npy --format coco2d       # 2D COCO-17 px @ 30 fps for MMFS-trained models (predict.py --format mmfs)
convert/.venv/bin/python -m convert.viz out.npz --video video.mp4 -o viz.mp4        # overlay + 3D (--mode overlay|3d|both)
convert/.venv/bin/python -m pytest convert/tests
```
Key flags: `--max-gap`, `--min-visibility`, `--smoothing one_euro|savgol|none`,
`--min-cutoff/--beta`, `--no-swap-fix`, `--no-bone-fix`, `--axes`, `--scale`, `--mirror-x`.

## Output `.npz`
| key | shape | notes |
|---|---|---|
| `skeleton` | (T,17,3) float32 | metres by default, pelvis-centred, see axes below |
| `mask` | (T,17) uint8 | 1 = observed or short-gap-filled; 0 = long gap (value is a linear/hold placeholder) |
| `confidence` | (T,) float32 | mean MediaPipe visibility over valid joints; 0 if nothing valid |
| `pelvis_2d` | (T,2) float32 | mid-hip in normalised image coords (x/width, y/height) |
| `body_height` | (T,) float32 | vertical extent of valid 2D joints as fraction of frame height |
| `joints_2d` | (T,17,2) float32 | all joints in normalised image coords (used by viz) |
| `joint_confidence` | (T,17) | per-joint visibility (0 where filled) |
| `fps` | scalar | 25 |
| `times`, `joint_names`, `metadata_json` | | metadata has config, bone lengths, swap counts, joint spec |

Load with `np.load(path)` (no pickle needed).

## Joint mapping (single table: `config.py`)
`JOINT_ORDER` (output index order) + `JOINT_SPEC` (how each joint is built from
the 33 MediaPipe landmarks). Default is Human3.6M order: 0 pelvis, 1 R hip, 2 R knee,
3 R ankle, 4 L hip, 5 L knee, 6 L ankle, 7 spine, 8 thorax, 9 neck/nose, 10 head top,
11 L shoulder, 12 L elbow, 13 L wrist, 14 R shoulder, 15 R elbow, 16 R wrist.
**FineFS's real order is unconfirmed**: to change it, edit `JOINT_ORDER` only; bones, L/R
pairs, swap groups and viz are name-based. Head top = ear midpoint + 0.55*(ear mid - thorax)
(falls back to the nose when ears are unavailable); spine = midpoint(pelvis, thorax).

## Axes / units
MediaPipe world landmarks are metres, mid-hip origin, x = image right, y = image down,
z = depth (smaller = closer to camera, i.e. +z away). That is already camera-like
(OpenCV / H3.6M camera: x right, y down, z forward), so the default preset `camera`
is identity. `camera_y_up` gives x right, y up, z toward camera. `--scale 1000` for mm,
`--mirror-x` to flip. Applied as the last step (rigid + scale commute with the rest).
Note: no global 3D translation is available from MediaPipe; use `pelvis_2d`/`body_height`.

## Pipeline order
1. map 33 -> 17 joints (5 channels: world xyz + image uv)
2. joints with visibility < `min_visibility` -> missing
3. L/R swap fix at source rate (Viterbi per group hips/legs/shoulders/arms: temporal
   continuity + bone-length term + switch penalty; partial swaps are handled)
4. resample to 25 fps (linear, gaps stay gaps)
5. gap fill: <= `max_gap` frames via PCHIP/linear/cubic, edges held; longer gaps masked
6. smoothing: One Euro (forward+backward averaged, speed-adaptive) or Savitzky-Golay
7. bone-length consistency: per-bone median length (L/R averaged), re-imposed from the pelvis outward
8. axes/units conversion

## Limitations
- A video where the skater is consistently mirrored (e.g. facing away the entire clip) is
  not detectable by temporal swap logic.
- Single person only (`num_poses=1`); with several people MediaPipe may jump between them.
- Inverted poses (spins, handstands) are weak spots for MediaPipe.
