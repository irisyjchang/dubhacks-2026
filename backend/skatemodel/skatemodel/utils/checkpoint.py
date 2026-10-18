"""Atomic checkpointing with a rolling backup (latest.pt -> latest.prev.pt)."""
from __future__ import annotations

import logging
import os
import random
from typing import Any, Dict, Optional

import numpy as np
import torch

log = logging.getLogger(__name__)


def rng_state() -> Dict[str, Any]:
    s = {"python": random.getstate(), "numpy": np.random.get_state(), "torch": torch.get_rng_state()}
    if torch.cuda.is_available():
        s["cuda"] = torch.cuda.get_rng_state_all()
    return s


def set_rng_state(s: Dict[str, Any]):
    try:
        random.setstate(s["python"])
        np.random.set_state(s["numpy"])
        torch.set_rng_state(s["torch"])
        if "cuda" in s and torch.cuda.is_available():
            torch.cuda.set_rng_state_all(s["cuda"])
    except Exception as e:  # different device count after requeue, etc.
        log.warning("could not restore RNG state: %s", e)


def save_atomic(state: Dict[str, Any], path: str, backup: bool = True):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    torch.save(state, tmp)
    if backup and os.path.exists(path):
        os.replace(path, path.replace(".pt", ".prev.pt"))
    os.replace(tmp, path)


def load_latest(ckpt_dir: str, map_location="cpu") -> Optional[Dict[str, Any]]:
    for name in ("latest.pt", "latest.prev.pt"):
        p = os.path.join(ckpt_dir, name)
        if os.path.exists(p):
            try:
                return torch.load(p, map_location=map_location, weights_only=False)
            except Exception as e:
                log.warning("failed to load %s (%s); trying backup", p, e)
    return None
