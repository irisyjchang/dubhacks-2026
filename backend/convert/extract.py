"""Run the MediaPipe Pose Landmarker (Tasks API) over a video."""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import config as C


@dataclass
class RawLandmarks:
    times: np.ndarray        # (T,) seconds
    world: np.ndarray        # (T,33,3) metres, hip-centred, NaN if no detection
    image: np.ndarray        # (T,33,3) normalised x,y (+z), NaN if no detection
    visibility: np.ndarray   # (T,33) 0 if no detection
    width: int
    height: int
    src_fps: float
    source: str = ""

    def save(self, path):
        np.savez_compressed(path, times=self.times, world=self.world, image=self.image,
                            visibility=self.visibility, width=self.width,
                            height=self.height, src_fps=self.src_fps, source=self.source)

    @staticmethod
    def load(path):
        d = np.load(path, allow_pickle=False)
        return RawLandmarks(d["times"], d["world"], d["image"], d["visibility"],
                            int(d["width"]), int(d["height"]), float(d["src_fps"]),
                            str(d["source"]))


def resolve_model(model: str) -> Path:
    """Return a local .task path, downloading lite/full/heavy if needed."""
    if model in C.MODEL_URLS:
        path = C.MODELS_DIR / f"pose_landmarker_{model}.task"
        if not path.exists():
            C.MODELS_DIR.mkdir(parents=True, exist_ok=True)
            print(f"downloading {model} model -> {path}")
            urllib.request.urlretrieve(C.MODEL_URLS[model], path)
        return path
    p = Path(model)
    if not p.exists():
        raise FileNotFoundError(f"model file not found: {model}")
    return p


def extract_landmarks(video_path, model="heavy", min_det=0.5, min_track=0.5,
                      progress=False) -> RawLandmarks:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    model_path = resolve_model(model)
    opts = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
        running_mode=vision.RunningMode.VIDEO,
        num_poses=1,
        min_pose_detection_confidence=min_det,
        min_pose_presence_confidence=min_det,
        min_tracking_confidence=min_track,
    )
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise IOError(f"cannot open video {video_path}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if not np.isfinite(src_fps) or src_fps <= 0:
        src_fps = 30.0
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    n_total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0

    times, world, image, vis = [], [], [], []
    last_ms = -1
    i = 0
    with vision.PoseLandmarker.create_from_options(opts) as lm:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
            # prefer container timestamps (handles VFR); fall back to index/fps
            if not t_ms or t_ms <= 0 and i > 0:
                t_ms = i * 1000.0 / src_fps
            ts = int(round(t_ms))
            if ts <= last_ms:
                ts = last_ms + 1
            last_ms = ts
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb), ts)
            times.append(ts / 1000.0)
            if res.pose_world_landmarks and res.pose_landmarks:
                w = res.pose_world_landmarks[0]
                p = res.pose_landmarks[0]
                world.append([[l.x, l.y, l.z] for l in w])
                image.append([[l.x, l.y, l.z] for l in p])
                vis.append([l.visibility for l in w])
            else:
                world.append(np.full((33, 3), np.nan))
                image.append(np.full((33, 3), np.nan))
                vis.append(np.zeros(33))
            i += 1
            if progress and i % 50 == 0:
                print(f"  frame {i}/{n_total or '?'}", flush=True)
    cap.release()
    if i == 0:
        raise IOError(f"no frames read from {video_path}")
    times = np.array(times)
    return RawLandmarks(times - times[0], np.array(world, float), np.array(image, float),
                        np.array(vis, float), W, H, float(src_fps), str(video_path))
