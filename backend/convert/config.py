"""All tunable configuration lives here.

The joint mapping (MediaPipe 33 -> 17 joints) is ONE table: ``JOINT_SPEC`` plus
``JOINT_ORDER``. FineFS's real joint order is unconfirmed; to change it, edit
``JOINT_ORDER`` only (the output index of each named joint). Everything else
(bones, L/R pairs, viz edges) is expressed in joint *names* and re-resolved
against the order automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# Joint order (Human3.6M 17-joint order). EDIT HERE if FineFS differs.
# --------------------------------------------------------------------------
JOINT_ORDER: list[str] = [
    "pelvis",      # 0
    "r_hip",       # 1
    "r_knee",      # 2
    "r_ankle",     # 3
    "l_hip",       # 4
    "l_knee",      # 5
    "l_ankle",     # 6
    "spine",       # 7
    "thorax",      # 8
    "neck",        # 9  (neck/nose -> MediaPipe nose)
    "head_top",    # 10
    "l_shoulder",  # 11
    "l_elbow",     # 12
    "l_wrist",     # 13
    "r_shoulder",  # 14
    "r_elbow",     # 15
    "r_wrist",     # 16
]

# --------------------------------------------------------------------------
# How each named joint is built from the 33 MediaPipe landmarks.
#   landmarks   : mean of the listed MediaPipe landmark ids
#   lerp        : (1-t)*a + t*b, where a, b are other named joints
#   extrapolate : base + alpha*(base - origin); base = mean of base_ids
#                 (falls back to fallback_ids when base_ids are unavailable),
#                 origin = another named joint. Used for the head top.
# MediaPipe ids: 0 nose, 7/8 L/R ear, 11/12 L/R shoulder, 13/14 elbow,
# 15/16 wrist, 23/24 hip, 25/26 knee, 27/28 ankle.
# --------------------------------------------------------------------------
JOINT_SPEC: dict[str, dict] = {
    "pelvis":     {"type": "landmarks", "ids": [23, 24]},
    "r_hip":      {"type": "landmarks", "ids": [24]},
    "r_knee":     {"type": "landmarks", "ids": [26]},
    "r_ankle":    {"type": "landmarks", "ids": [28]},
    "l_hip":      {"type": "landmarks", "ids": [23]},
    "l_knee":     {"type": "landmarks", "ids": [25]},
    "l_ankle":    {"type": "landmarks", "ids": [27]},
    "thorax":     {"type": "landmarks", "ids": [11, 12]},
    "spine":      {"type": "lerp", "a": "pelvis", "b": "thorax", "t": 0.5},
    "neck":       {"type": "landmarks", "ids": [0]},
    "head_top":   {"type": "extrapolate", "base_ids": [7, 8], "fallback_ids": [0],
                   "origin": "thorax", "alpha": 0.55},
    "l_shoulder": {"type": "landmarks", "ids": [11]},
    "l_elbow":    {"type": "landmarks", "ids": [13]},
    "l_wrist":    {"type": "landmarks", "ids": [15]},
    "r_shoulder": {"type": "landmarks", "ids": [12]},
    "r_elbow":    {"type": "landmarks", "ids": [14]},
    "r_wrist":    {"type": "landmarks", "ids": [16]},
}

# Kinematic tree, parent -> child (parent listed before child). Root: pelvis.
BONES: list[tuple[str, str]] = [
    ("pelvis", "r_hip"), ("r_hip", "r_knee"), ("r_knee", "r_ankle"),
    ("pelvis", "l_hip"), ("l_hip", "l_knee"), ("l_knee", "l_ankle"),
    ("pelvis", "spine"), ("spine", "thorax"), ("thorax", "neck"), ("neck", "head_top"),
    ("thorax", "l_shoulder"), ("l_shoulder", "l_elbow"), ("l_elbow", "l_wrist"),
    ("thorax", "r_shoulder"), ("r_shoulder", "r_elbow"), ("r_elbow", "r_wrist"),
]

# Left/right bone pairs whose lengths are averaged when enforcing consistency.
SYMMETRIC_BONES: list[tuple[tuple[str, str], tuple[str, str]]] = [
    (("pelvis", "r_hip"), ("pelvis", "l_hip")),
    (("r_hip", "r_knee"), ("l_hip", "l_knee")),
    (("r_knee", "r_ankle"), ("l_knee", "l_ankle")),
    (("thorax", "r_shoulder"), ("thorax", "l_shoulder")),
    (("r_shoulder", "r_elbow"), ("l_shoulder", "l_elbow")),
    (("r_elbow", "r_wrist"), ("l_elbow", "l_wrist")),
]

# L/R swap groups. Each group is decided independently (keep vs swap per frame),
# so partial swaps (e.g. only knee/ankle) are repaired without touching other joints.
#   pairs: (right_joint, left_joint) swapped together
#   edges: indices into pairs forming a chain (parent_idx, child_idx); used for
#          the bone-length term of the swap cost.
SWAP_GROUPS: dict[str, dict] = {
    "hips": {"pairs": [("r_hip", "l_hip")], "edges": []},
    "legs": {"pairs": [("r_knee", "l_knee"), ("r_ankle", "l_ankle")], "edges": [(0, 1)]},
    "shoulders": {"pairs": [("r_shoulder", "l_shoulder")], "edges": []},
    "arms": {"pairs": [("r_elbow", "l_elbow"), ("r_wrist", "l_wrist")], "edges": [(0, 1)]},
}

# --------------------------------------------------------------------------
# Axis / unit conventions.
# MediaPipe world landmarks: metres, origin at mid-hip, x = image right,
# y = image DOWN, z = depth with smaller values closer to the camera (so +z
# points away from the camera). That is already an OpenCV/H3.6M-style camera
# frame (x right, y down, z forward), so the default preset is identity.
# --------------------------------------------------------------------------
AXIS_PRESETS: dict[str, list[list[float]]] = {
    "camera": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],      # x right, y down, z away (default)
    "camera_y_up": [[1, 0, 0], [0, -1, 0], [0, 0, -1]],  # x right, y up, z toward camera
}

MODEL_URLS = {
    "lite": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task",
    "full": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task",
    "heavy": "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task",
}
MODELS_DIR = Path(__file__).resolve().parent / "models"


@dataclass
class PipelineConfig:
    # extraction
    model: str = "heavy"               # lite | full | heavy | path to a .task file
    min_detection_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    # resampling
    target_fps: float = 25.0
    # clean-up
    min_visibility: float = 0.4        # joints below this are treated as missing
    max_gap: int = 8                   # frames (at target fps); longer gaps are masked
    gap_method: str = "pchip"          # linear | pchip | cubic
    fix_swaps: bool = True
    swap_penalty: float = 0.15         # cost (m) of switching label state
    swap_prior: float = 1e-3           # per-frame cost (m) of being in the swapped state
    swap_bone_weight: float = 0.5
    smoothing: str = "one_euro"        # one_euro | savgol | none
    one_euro_min_cutoff: float = 2.5   # Hz; lower = smoother when slow
    one_euro_beta: float = 5.0        # higher = less lag on fast motion
    one_euro_d_cutoff: float = 1.0
    savgol_window: int = 7             # frames (odd)
    savgol_polyorder: int = 3
    fix_bones: bool = True
    symmetric_bones: bool = True
    # output conventions
    axes: str = "camera"
    scale: float = 1.0                 # 1.0 = metres, 1000 = millimetres
    mirror_x: bool = False
    root_relative: bool = True         # subtract pelvis (MediaPipe is already hip-centred)

    def to_dict(self) -> dict:
        return asdict(self)


def joint_index() -> dict[str, int]:
    return {n: i for i, n in enumerate(JOINT_ORDER)}


def validate_config() -> None:
    assert len(JOINT_ORDER) == 17 and len(set(JOINT_ORDER)) == 17
    assert set(JOINT_ORDER) == set(JOINT_SPEC), "JOINT_ORDER and JOINT_SPEC names differ"


validate_config()
