"""YAML config with `_base_` inheritance and `key.sub=value` CLI overrides."""
from __future__ import annotations

import copy
import os
from typing import Any, Dict, List

import yaml


def deep_update(a: Dict, b: Dict) -> Dict:
    out = copy.deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load_config(path: str, overrides: List[str] = ()) -> Dict[str, Any]:
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    base = cfg.pop("_base_", None)
    if base:
        cfg = deep_update(load_config(os.path.join(os.path.dirname(path), base)), cfg)
    for ov in overrides:
        key, val = ov.split("=", 1)
        d = cfg
        parts = key.split(".")
        for p in parts[:-1]:
            d = d.setdefault(p, {})
        d[parts[-1]] = yaml.safe_load(val)
    return cfg
