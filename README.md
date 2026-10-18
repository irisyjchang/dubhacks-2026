# DubHacks 2026: figure-skating spin coach

A local prototype that tracks the main skater, measures joint geometry, and produces an annotated video plus a written coaching report. The upload page lives on the frontend branch. This server exposes the job API.

## Setup

The pipeline was tested on macOS with Python 3.9. MediaPipe provides platform-specific wheels; use a compatible Python/platform combination.

```sh
python3 -m venv .video-venv
.video-venv/bin/python -m pip install --upgrade pip
.video-venv/bin/python -m pip install -r requirements-local.txt
mkdir -p models
curl -L --fail https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task -o models/pose_landmarker_heavy.task
```

Videos, generated artifacts, virtual environments, API credentials and the downloaded model are excluded from Git. Supply your own skating clip.

## Upload test

```sh
.video-venv/bin/python webapp.py --ask-key
```

Enter your NVIDIA API key at the hidden prompt, or run without `--ask-key` and configure `NVIDIA_API_KEY` in the server environment. Credentials are used in memory and passed to the worker environment, not saved in project files or returned in job results.

`GET http://127.0.0.1:8000/` describes the API. Upload a MOV, MP4, M4V, WebM or AVI clip up to 30 seconds / 200 MB with `POST /api/jobs`. Completed job URLs can be refreshed while the server is running.

- **NVIDIA mode:** local pose tracking and measurements, followed by model-generated coaching for each roughly one-second interval and timed video captions. Timestamped video crops and pose summaries are sent to NVIDIA.
- **Local-only mode:** local tracking, a pose-overlay video, and a disclosed rule-based report; no model calls or model timeline captions.

This is a localhost development harness: one processing worker, an in-memory job queue, and artifacts saved under `outputs/web_jobs/<job-id>/`. Job records reset when the server restarts, while files remain on disk. It has no accounts, durable queue, storage service or automatic retention. It is not a public deployment.

## Command-line processing

```sh
# Entirely local measurements and report
.video-venv/bin/python run_spin_coach.py --input /path/to/spin.mov

# Add NVIDIA coaching and synchronized captions
.video-venv/bin/python run_spin_coach.py --input /path/to/spin.mov --nvidia-report
```

The CLI uses `NVIDIA_API_KEY` or a hidden key prompt in NVIDIA mode. Use `--output` to choose an output directory, `--report-timeout` to change the model-generation time budget (default 75 seconds), and `--llm-model` to override the default `google/diffusiongemma-26b-a4b-it`. An override must support the supplied image inputs and be accessible to your NVIDIA account. Output files in a selected directory are overwritten on rerun; input files are preserved.

The latest measured upload test processed a 3.3-second clip with four completed model sections in about 40 seconds, including rate-limit retries. This is an observed example, not a runtime guarantee; longer clips, hardware and endpoint limits change processing time.

## What the pipeline does

1. FFmpeg normalizes frame rate, orientation and resolution, retaining available audio.
2. MediaPipe estimates poses and body segmentation. Foreground size and temporal proximity select the main skater; this is a heuristic rather than guaranteed identity tracking.
3. Confidence-filtered image coordinates calculate knee, elbow, shoulder, hip and ankle angles, screen-relative torso lean, and torso-normalized limb relationships. Background optical flow estimates camera motion.
4. Per-second summaries record medians, interquartile ranges and usable-frame counts. At least half an interval's frames, and at least four frames, must support a metric before it is used for model advice.
5. Optional NVIDIA requests receive measurement cards and two timestamped body crops per interval. The prompt asks for an observation, a measurement-based review/practice target, a mental cue and a compact caption. Requests run serially, with bounded retries for rate limits.
6. Numeric citations are checked against supplied facts with rounding tolerance. Unknown values/tokens and unsupported full-extension/locking instructions trigger one rewrite attempt. Raw model text is retained separately from locally inserted evidence and measurements.
7. OpenCV and FFmpeg render the skeleton, per-frame knee/elbow measurements, and two-line interval captions with original audio.

For example, a measured elbow median near 171 degrees does not justify automatically telling the skater to straighten it further. A wide knee-angle range instead prompts a check of whether the skater intended to hold one position or deliberately change it. Thresholds prioritize review, not technique deductions.

Repeatability comparisons use disjoint frames at least 0.4 seconds apart, within two seconds, with similar signed projected shoulder/hip vectors inside a detected lower-posture phase. These are candidate review pairs, not verified identical poses or an ideal-technique baseline.

If a model interval fails, the report is marked partial and identifies the error. Its locally computed measurements remain available, without silently substituting template coaching for a model response. Missing model intervals have no model caption. Optional manually reviewed `visual_notes.json` files are accepted only when their source-video SHA-256 matches; new uploads do not automatically receive manual review notes.

## Output files

CLI results default to `outputs/local_coach/<input-stem>/`; web jobs use separate result folders.

| File | Contents |
| --- | --- |
| `feedback.mp4` | Annotated video, timed coaching captions when available, and original audio |
| `coaching_report.md` | Full local or model coaching report, with provenance |
| `coaching_assessment.json` | Model sections, raw responses, locally formatted evidence, timing and errors |
| `video_captions.json` | Caption text, intervals and source sections |
| `analysis.json` | Tracking, rule-based findings, timings, kinematics and per-frame measurements |
| `kinematics.json` | Joint-angle definitions, per-frame geometry, per-second ranges/coverage and candidate view comparisons |
| `landmarks.json` | Image and inferred world-space pose landmarks |
| `report.md` | Measurement/rule report and reliability notes |
| `evidence.jpg`, `evidence_*s.jpg` | Annotated review frames |
| `measurements.png` | Posture and tracking-quality chart |
| `coaching_frames*.jpg`, `coaching_frames.json` | Crops used for model requests and their exact timestamps |
| `coaching_prompt.txt`, `timeline_requests/` | Key-free prompt/request records and model-response attempts |
| `input.mp4` | Normalized working video |

These outputs may contain private video frames and measurements; they remain in ignored local folders.

## Test API

1. `POST /api/jobs` with multipart `video`, `mode=nvidia|local` and optional `api_key`. Returns HTTP 202 with a job ID and status URL.
2. `GET /api/jobs/<id>` for status, progress, full report, timings, provenance and artifact URLs.
3. `GET /api/jobs/<id>/files/<filename>` for allowlisted result files. Video responses support HTTP range requests; add `?download=1` for downloads.

## Validation

```sh
.video-venv/bin/python -m unittest discover -s tests -v
```

The suite covers joint geometry, confidence gating, missing data, posture rules, timed caption boundaries, numeric evidence validation, upload isolation, invalid files, credential redaction, failed jobs and HTTP video range responses. End-to-end local tests additionally checked completed NVIDIA reports, frame decoding, captions and preserved audio.

## Limits

All reported angles are **2D image-plane estimates**, not calibrated anatomical measurements. Rotation, occlusion, camera tilt and possible left/right label swaps affect them. Visibility/presence filtering is not an accuracy guarantee. Supporting-leg identity is not established by MediaPipe's left/right labels. An ankle-to-toe angle does not establish blade pitch, contact, edge or pressure.

The prototype does not determine official scores/GOE, legal sit depth, spin level, revolution count/RPM or ice-relative centering. High usable-frame coverage is not proof of a steady position, and a bent elbow or asymmetric shape is not automatically incorrect. Declaring a position wrong or prescribing ideal angles requires an intended spin variation and an expert reference; neither is inferred here. Model coaching remains a hackathon interpretation, not a validated judging system.

MediaPipe reference: https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python
