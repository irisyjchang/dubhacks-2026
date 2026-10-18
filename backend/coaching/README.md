# DubHacks 2026: figure-skating spin coach

A local prototype that tracks the main skater, measures joint geometry, and produces an annotated video plus a written coaching report. A minimal upload page exercises the same pipeline without a production frontend.

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

On macOS/Linux, add `--detach` to keep the server running in the background after the launching terminal closes:

```sh
.video-venv/bin/python webapp.py --ask-key --detach
```

To add whole-person boxes from [Perceptron Mk1.5](https://docs.perceptron.inc/perceptron-mk1.5/capabilities/video-tracking), start with both hidden key prompts:

```sh
.video-venv/bin/python webapp.py --ask-key --ask-perceptron-key --detach
```

Alternatively configure `PERCEPTRON_API_KEY` in the server environment or use the optional password field. Enable **Perceptron whole-person bounding box** on the upload form. In NVIDIA mode this sends the prepared video to Perceptron during inspection, then matches MediaPipe poses to the main-person boxes. There is at most one format-correction retry within a 60-second request budget; no tracking request is repeated after element confirmation. Cyan boxes show model observations, labelled interpolation between nearby observations (maximum 0.8-second gaps), or body-point refinement. Missing/long-gap regions use grey, labelled pose-derived boxes when a pose is available. API failures disclose the local fallback and do not discard the upload. Local-only mode never calls either provider.

The downloadable `person_tracking.json` records original model anchors, pixel dimensions, native frame timestamps, per-frame boxes and sources (`perceptron`, `interpolated`, `fused`, `mediapipe`), timing and any provider warning. Confident matched body points expand boxes when needed to include extended hands or skates; these boxes are labelled `fused` and retain the pre-refinement box and anchor times in their evidence. Interpolation and fusion are local estimates, not additional model observations; fast motion or occlusion can make them inaccurate. The actual Mk1.5 response can use a single-object collection of timestamped track leaves; the parser accepts this observed variant as well as the documented point-box track grammar, rejecting ambiguous identities and invalid geometry.

Background logs go to `outputs/web_server.log`; the launch command prints its process ID. The key stays in memory. If the page reports that the server is offline, start the server and refresh the page. After a restart, expired job links reset to allow a new upload.

Enter your NVIDIA API key at the hidden prompt, then open **http://127.0.0.1:8000**. Alternatively, run without `--ask-key` and enter a key in the form, or configure `NVIDIA_API_KEY` in the server environment. Credentials are used in memory and passed to the worker environment, not saved in project files or returned in job results.

### Gemini primary, NVIDIA fallback

```sh
.video-venv/bin/python webapp.py --ask-gemini-key --ask-key --ask-perceptron-key --detach
```

Configure `GEMINI_API_KEY` or use the hidden `--ask-gemini-key` prompt. When configured, the AI mode uses **Gemini Flash first**, including the independent position readings and the final visual assessment. The configured alias is `gemini-3.5-flash`; the live service returned `gemini-3.6-flash`, and the actual returned model is recorded and displayed. It receives the compact video, phase close-ups, measurements and the same ISU criteria as NVIDIA. Low thinking is requested, JSON output is requested, and the same phase, evidence, caption, paragraph and coaching-score checks apply. No additional Python SDK is required.

If Gemini rejects the key, has a disabled API, runs out of quota, times out or cannot return a valid assessment, the saved video and tracking are reused by the existing NVIDIA Nemotron pipeline. Gemini gets at most 30 seconds when NVIDIA fallback is configured, within the overall report time budget. The result records the actual provider/model, fallback reason and separate API-call counts; the page discloses fallback use. Local-only mode disables both providers even when keys are configured in the server environment.

Temporary HTTP 500/502/503/504 failures retry the same Gemini request up to twice, with approximately one- and two-second delays plus jitter, within that same time budget. Completed phase requests are not repeated during these retries. Authentication and quota failures go straight to fallback. HTTP 503 has no fixed request-count threshold or published reset time; it indicates service availability rather than a project quota.

The [Gemini API](https://console.cloud.google.com/apis/library/generativelanguage.googleapis.com) must be enabled in the key's Google Cloud project. Listing models alone does not confirm generation access. API credentials remain in memory and are removed from worker logs and public errors. Diagnostic Gemini responses are saved without keys in the ignored job directory.

A live 3.34-second clip completed through Gemini, including tracking, the annotated video and short scored report, in 14.67 seconds excluding user confirmation time. A real Gemini model-not-found response also exercised the NVIDIA fallback, completing the same clip in 16.34 seconds. These are observed examples, not latency guarantees.

Upload a MOV, MP4, M4V, WebM or AVI clip up to 30 seconds / 200 MB. The toy page first tracks the skater and asks Gemini to identify the dominant movement from the compact video and timestamped tracked-person views. NVIDIA Nemotron vision is used if Gemini is unavailable or returns an invalid identification. Confirm or correct the suggested element, optionally mark phase times using the preview, then generate feedback. Tracking and identification are reused after confirmation and report retries.

The result shows a one-line **Good / Improve** takeaway without angles, a video with qualitative phase captions, and a short expandable coaching report: three paragraphs covering what went well, what needs work and how to improve, followed by a **coaching score out of 10** and a short reason. Each paragraph is limited to 50 words. The model generates this review in the same assessment request, using the same phase findings as the captions; detailed measurements and phase evidence stay in the JSON.

The score is a subjective prototype execution rating, not an official ISU/GOE score: 0–3 indicates major visible execution problems, 4–6 inconsistent control, 7–8 mostly controlled execution with specific improvements, and 9–10 consistently strong execution. It rates visible skating rather than tracking coverage or model confidence. If execution cannot be seen well enough, or the report uses local-only rules, the score is explicitly not rated. Completed job URLs can be refreshed while the server is running.

Supported labels: upright, sit and camel spins; generic spin; waltz jump; generic jump; and unknown/general skating. Automatic suggestions use **Gemini video understanding first, NVIDIA vision second**, with a disclosed local pose heuristic only if both services fail. The UI shows the actual provider/model, self-reported confidence and timestamped observations. General skating, partial entries and ambiguous combinations can return unknown; unsupported jump subtypes use the broad jump label. Clips shorter than one second skip remote recognition and require manual selection because they lack reliable movement context. Suggestions always require confirmation and do not constitute official technical calls.

Recognition has a separate 25-second request/preparation budget; Gemini receives up to 12 seconds when NVIDIA fallback is configured. The NVIDIA fallback first receives video and tracked-person views. If that request fails, a second request uses the timestamped frame sequence and discloses the reduced input. Local-only mode does not prepare or send remote recognition media. Recognition calls and timing are saved separately and included once in total provider costs. Gemini is asked to sample video at up to five frames per second to retain fast motion, following the [video sampling documentation](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding#custom-frame-rate). This adds one model request when Gemini succeeds.

### ISU-based review

The versioned reference set in `spincoach/isu_rules.py` selects relevant **2026–27 singles** criteria from the [Referees and Judges Handbook](https://isu-d8g8b4b7ece7aphs.a03.azurefd.net/isudamcontainer/CMS/Corporate-Site/Sports-Rules/Figure-Skating-Rules/Handbooks-Single-%26-Pair-Skating/Handbook-for-Referees-and-Judges-2026-27-1779278300-9402.pdf) (19 May 2026) and the [Singles Technical Panel Handbook](https://isu-d8g8b4b7ece7aphs.a03.azurefd.net/isudamcontainer/CMS/Corporate-Site/Sports-Rules/Figure-Skating-Rules/Handbooks-Single-%26-Pair-Skating/TP-HandbookSingles-26-27-15-July-2026-1784641784-3364.pdf) (15 July 2026), listed on the [official handbook page](https://www.isu.org/en/figure-skating-rules/figure-skating-rule/handbooks-single-and-pair-skating).

This is a curated subset, not the full rulebooks or a complete GOE scoring rubric. Basic-position definitions come from technical handbook p. 14. Judging clarifications cover position quality, missing revolutions, sit-side boot contact, difficult exits, arm variation and jump takeoff/landing. Each check stores its source page, required evidence, applicability, status, supporting measurements and optional conditional reduction range. Full PDFs are not bundled or fetched during uploads.

The model receives phase-relevant criteria alongside a compact full video, timestamped close-ups and measured evidence. Separate perception requests first describe each phase’s arm/free-leg shapes and apparent sit depth from a larger close-up panel. Coaching is checked against those position readings: a folded leg must not become an extension behind, and an already-low sit must not receive an automatic deepen-the-sit instruction. These readings are model observations, not human-verified ground truth.

The report and toy UI show linked visual judgments as **Looks good**, **Needs work** or **Limited view**, with concrete reasons and frame evidence. They no longer display every unimplemented technical check as the main feedback. Numeric scoring, invented measurements, unknown rule IDs and cross-phase evidence are rejected. Detailed technical calls requiring verified revolutions, blade contact, exact takeoff edges or difficult-exit context stay unassessed in the JSON. Torso verticality is not the definition of an upright spin.

No official GOE, base value, spin level or program-component score is calculated. Reference reduction ranges explain what could apply **if** a specified mistake were established; no deduction is applied. Program/category requirements are unspecified, and waltz jumps receive developmental feedback rather than a listed-jump score. Pair and choreographic-spin rules are not applied to these supported single-skater elements. Source versions are pinned and need explicit review when ISU updates the rules.

For jumps, optional takeoff/landing markers define preparation, user-marked flight and landing/recovery. Without markers, phase boundaries remain unresolved. For spins, optional hold-start/end markers define entry, intended hold and later position; sit-spin clips can use the detected lower-posture candidate if unmarked. The app does not invent phase boundaries by dividing the clip into equal thirds. Original frame rate is retained for analysis.

- **NVIDIA mode:** local pose tracking and measurements, followed by phase position readings and a whole-clip coaching request that returns every phase together. A compact video, close-ups and pose summaries are sent to NVIDIA. If video media is rejected or times out, the report records that only the sampled frame sequence was used on retry.
- **Local-only mode:** local tracking, a phase-captioned pose video, and a disclosed local element report; no model calls.

This is a localhost development harness: one processing worker, an in-memory job queue, and artifacts saved under `outputs/web_jobs/<job-id>/`. Job records reset when the server restarts, while files remain on disk. It has no accounts, durable queue, storage service or automatic retention. It is not a public deployment.

## Command-line processing

```sh
# Entirely local measurements and report
.video-venv/bin/python run_spin_coach.py --input /path/to/spin.mov

# Add NVIDIA coaching and synchronized captions
.video-venv/bin/python run_spin_coach.py --input /path/to/spin.mov --element sit_spin --nvidia-report

# Also use whole-person boxes (requires PERCEPTRON_API_KEY in the environment)
.video-venv/bin/python run_spin_coach.py --input /path/to/spin.mov --element sit_spin --nvidia-report --perceptron-track

# Gemini first, with NVIDIA fallback (keys from environment or hidden prompts)
.video-venv/bin/python run_spin_coach.py --input /path/to/spin.mov --element sit_spin --gemini-report --nvidia-report
```

The CLI uses `NVIDIA_API_KEY` or a hidden key prompt in NVIDIA mode. Use `--output` to choose an output directory, `--report-timeout` to change the model-generation time budget (default 75 seconds), and `--llm-model` to override the default `nvidia/nemotron-3.5-super-vl-120b-a12b`. An override must support the supplied image inputs and be accessible to your NVIDIA account. Output files in a selected directory are overwritten on rerun; input files are preserved.

The measured whole-clip visual test processed an approximately seven-second clip with three phase reports and the annotated video in 55.13 seconds, excluding time spent confirming the element. Position reading and coaching took 45.54 seconds across five API calls, including a corrective rewrite. Tracking was reused after confirmation. This is an observed example, not a runtime guarantee; longer clips, hardware and endpoint limits change processing time.

## What the pipeline does

1. FFmpeg normalizes orientation and resolution, retaining the native frame rate and available audio.
2. Optional Perceptron tracking identifies the main skater and whole-person box anchors. MediaPipe estimates poses and body segmentation, associating the torso and visible joints to those boxes. When model boxes are unavailable, foreground size and temporal proximity select the main skater. Neither method guarantees identity tracking.
3. Confidence-filtered image coordinates calculate knee, elbow, shoulder, hip and ankle angles, screen-relative torso lean, and torso-normalized limb relationships. Background optical flow estimates camera motion.
4. Per-second and confirmed-phase summaries record medians, interquartile ranges and usable-frame counts. At least half an interval's frames, and at least four frames, must support a metric before it is used for model advice.
5. The optional NVIDIA mode uses Nemotron 3.5 Super VL: a separate position-reading request for each phase sees a close-up panel, then one request assesses all phases together using the full clip, four timestamped crops per phase, position readings, geometry and applicable ISU criteria. Each phase supplies a strength, improvement, actionable correction, mental cue, qualitative caption and evidence frame IDs. Model confidence is self-reported, not calibrated.
6. Structured responses are checked for full phase coverage, valid frame/rule references, actual supplied numerical values, qualitative summaries/captions and consistency with the position readings. Invalid reports trigger a bounded rewrite; raw model text is retained separately from locally inserted measurements. Source video and frame hashes/IDs provide provenance.
7. OpenCV and FFmpeg render the skeleton, qualitative phase captions (legacy runs can include per-frame numeric overlays) with original audio.

For example, a measured elbow median near 171 degrees does not justify automatically telling the skater to straighten it further. A wide knee-angle range instead prompts a check of whether the skater intended to hold one position or deliberately change it. Thresholds prioritize review, not technique deductions.

Repeatability comparisons use disjoint frames at least 0.4 seconds apart, within two seconds, with similar signed projected shoulder/hip vectors inside a detected lower-posture phase. These are candidate review pairs, not verified identical poses or an ideal-technique baseline.

The whole-clip model response must cover every phase and pass evidence validation; failures are reported instead of silently filling missing sections with local template coaching. Repeated primary-model service failures switch to `google/diffusiongemma-26b-a4b-it` using sampled frames within the same request budget. Actual model identity and fallback use are recorded in the report. Authentication failures are reported without retrying a different model. If recovery is exhausted, the page shows the NVIDIA error and offers **Retry report using saved tracking**, reusing the existing upload and landmarks. Retry credentials remain in memory, not in artifacts. Legacy per-second reports can be partial, with failed intervals disclosed. Manual review notes from older runs are not automatically reused for new uploads.

## Output files

CLI results default to `outputs/local_coach/<input-stem>/`; web jobs use separate result folders.

| File | Contents |
| --- | --- |
| `feedback.mp4` | Annotated video, timed coaching captions when available, and original audio |
| `coaching_report.md` | Three short coaching paragraphs and a subjective execution rating out of 10 |
| `coaching_assessment.json` | Model sections, raw responses, locally formatted evidence, timing and errors |
| `video_captions.json` | Caption text, intervals and source sections |
| `analysis.json` | Tracking, rule-based findings, timings, kinematics and per-frame measurements |
| `kinematics.json` | Joint-angle definitions, per-frame geometry, per-second ranges/coverage and candidate view comparisons |
| `landmarks.json` | Image and inferred world-space pose landmarks |
| `person_tracking.json` | Whole-person box anchors and per-frame estimates, provider/source labels and tracking timing |
| `report.md` | Measurement/rule report and reliability notes |
| `evidence.jpg`, `evidence_*s.jpg` | Annotated review frames |
| `measurements.png` | Posture and tracking-quality chart |
| `coaching_frames*.jpg`, `coaching_frames.json` | Crops used for model requests and their exact timestamps |
| `judge_video.mp4`, `judge_frames.jpg`, `judge_f*.jpg`, `judge_media.json` | Compact video, close-up frames and their exact source timestamps/hash |
| `judge_positions.json`, `visual_model_attempts.json` | Separate model position reading and raw coaching response attempts, without credentials |
| `element_identification.json`, `element_gemini_attempts.json`, `element_video.mp4`, `element_frames.jpg` | Suggested move, actual recognition provider/model, timestamped observations, fallback provenance and recognition inputs |
| `gemini_positions.json`, `gemini_attempts.json`, `gemini_prompt.txt`, `provider_fallback.json` | Gemini perception, key-free generation diagnostics and provider fallback reason when applicable |
| `coaching_prompt.txt`, `timeline_requests/` | Key-free prompt records; legacy per-second model attempts |
| `input.mp4` | Normalized working video |

These outputs may contain private video frames and measurements; they remain in ignored local folders.

## Test API

1. `POST /api/jobs` with multipart `video`, `mode=nvidia|local`, `element=auto|<supported label>` and optional `api_key`, `perceptron_track=on`, `perceptron_key`. Perceptron is opt-in and disabled in local mode. Returns HTTP 202; inspection ends in `needs_confirmation` with an input-video preview and suggestion.
2. `POST /api/jobs/<id>/confirm` with JSON `{"element":"sit_spin","markers":{"hold_start_s":1.5,"hold_end_s":5.9}}`. Markers are optional; jump markers are `takeoff_s` and `landing_s`. Invalid or mismatched markers are rejected. This resumes the prepared measurements without retracking.
3. `GET /api/jobs/<id>` for status, progress, full report, timings, provenance and artifact URLs.
4. `POST /api/jobs/<id>/retry` retries a failed, retryable coaching run using saved tracking, while the server remains running.
5. `GET /api/jobs/<id>/files/<filename>` for allowlisted result files. Video responses support HTTP range requests; add `?download=1` for downloads.

## Validation

```sh
.video-venv/bin/python -m unittest discover -s tests -v
```

The suite covers joint geometry, confidence gating, missing data, posture rules, timed caption boundaries, numeric evidence validation, upload isolation, invalid files, credential redaction, failed jobs and HTTP video range responses. End-to-end local tests additionally checked completed NVIDIA reports, frame decoding, captions and preserved audio.

## Limits

All reported angles are **2D image-plane estimates**, not calibrated anatomical measurements. Rotation, occlusion, camera tilt and possible left/right label swaps affect them. Visibility/presence filtering is not an accuracy guarantee. Supporting-leg identity is not established by MediaPipe's left/right labels. An ankle-to-toe angle does not establish blade pitch, contact, edge or pressure.

The expandable coaching report stays brief and qualitative. Full phase responses, numeric evidence, coverage and comparison details remain in `coaching_assessment.json` and `analysis.json`.

The prototype does not determine official scores/GOE, legal sit depth, spin level, revolution count/RPM or ice-relative centering. High usable-frame coverage is not proof of a steady position, and a bent elbow or asymmetric shape is not automatically incorrect. The confirmed element and selected ISU references guide checks, but do not supply calibrated ideal joint angles or establish a mistake. Model coaching remains a hackathon interpretation, not a validated judging system.

MediaPipe reference: https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker/python
