"""CSV + TensorBoard scalar logging (rank 0 only)."""
from __future__ import annotations

import csv
import json
import logging
import os
import time
from typing import Dict


def setup_logging(log_dir: str, rank: int):
    fmt = f"%(asctime)s [rank{rank}] %(levelname)s %(name)s: %(message)s"
    handlers = [logging.StreamHandler()]
    if rank == 0:
        os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(os.path.join(log_dir, "train.log")))
    logging.basicConfig(level=logging.INFO if rank == 0 else logging.WARNING, format=fmt,
                        handlers=handlers, force=True)


class ScalarLogger:
    def __init__(self, log_dir: str, enabled: bool = True, tensorboard: bool = True):
        self.enabled = enabled
        self.log_dir = log_dir
        self.tb = None
        if not enabled:
            return
        os.makedirs(log_dir, exist_ok=True)
        if tensorboard:
            try:
                from torch.utils.tensorboard import SummaryWriter
                self.tb = SummaryWriter(os.path.join(log_dir, "tb"))
            except Exception as e:  # tensorboard not installed
                logging.getLogger(__name__).warning("TensorBoard disabled: %s", e)

    def log(self, split: str, step: int, scalars: Dict[str, float]):
        if not self.enabled:
            return
        path = os.path.join(self.log_dir, f"{split}.csv")
        row = {"step": step, "time": round(time.time(), 1), **{k: _num(v) for k, v in scalars.items()}}
        exists = os.path.exists(path)
        if exists:  # extend header if new keys appear
            with open(path) as f:
                header = next(csv.reader(f), [])
            if set(row) - set(header):
                with open(path) as f:
                    old = list(csv.DictReader(f))
                header = header + [k for k in row if k not in header]
                with open(path, "w", newline="") as f:
                    w = csv.DictWriter(f, header)
                    w.writeheader()
                    w.writerows(old)
        else:
            header = list(row)
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, header)
            if not exists:
                w.writeheader()
            w.writerow(row)
        if self.tb is not None:
            for k, v in scalars.items():
                if isinstance(v, (int, float)):
                    self.tb.add_scalar(f"{split}/{k}", v, step)
            self.tb.flush()

    def dump_json(self, name: str, obj):
        if self.enabled:
            with open(os.path.join(self.log_dir, name), "w") as f:
                json.dump(obj, f, indent=1, default=_num)


def _num(v):
    try:
        return round(float(v), 6)
    except (TypeError, ValueError):
        return str(v)
