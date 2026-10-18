"""Minimal DDP helpers (torchrun env vars; falls back to single process on CPU/1 GPU)."""
from __future__ import annotations

import os
from datetime import timedelta

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # unsupported MPS ops fall back to CPU

import torch
import torch.distributed as dist


def select_device(pref: str = "auto", local_rank: int = 0, world: int = 1) -> torch.device:
    """cuda > mps > cpu (pref: auto | cuda | mps | cpu). MPS is single-process only."""
    if pref in ("auto", "cuda") and torch.cuda.is_available():
        torch.cuda.set_device(local_rank)
        return torch.device("cuda", local_rank)
    if pref in ("auto", "mps") and world == 1 and getattr(torch.backends, "mps", None) \
            and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def init_distributed(pref: str = "auto"):
    """Returns (rank, world_size, local_rank, device)."""
    world = int(os.environ.get("WORLD_SIZE", "1"))
    rank = int(os.environ.get("RANK", "0"))
    local_rank = int(os.environ.get("LOCAL_RANK", "0"))
    device = select_device(pref, local_rank, world)
    if world > 1 and not dist.is_initialized():
        backend = "nccl" if device.type == "cuda" else "gloo"
        dist.init_process_group(backend, timeout=timedelta(minutes=60))
    return rank, world, local_rank, device


def is_main() -> bool:
    return not dist.is_initialized() or dist.get_rank() == 0


def barrier():
    if dist.is_initialized():
        dist.barrier()


def any_true(flag: bool, device) -> bool:
    """True if `flag` is set on any rank (used for coordinated preemption stop)."""
    if not dist.is_initialized():
        return flag
    t = torch.tensor([1.0 if flag else 0.0], device=device)
    dist.all_reduce(t, op=dist.ReduceOp.MAX)
    return bool(t.item() > 0)


def broadcast_float(value: float, device, src: int = 0) -> float:
    """Value as seen by rank `src` (rank 0 decides time-based things; all ranks agree)."""
    if not dist.is_initialized():
        return value
    t = torch.tensor([value], device=device, dtype=torch.float64)
    dist.broadcast(t, src=src)
    return float(t.item())


def all_reduce_mean(d: dict, device) -> dict:
    if not dist.is_initialized() or not d:
        return d
    keys = sorted(d)
    t = torch.tensor([d[k] for k in keys], device=device, dtype=torch.float64)
    dist.all_reduce(t)
    t /= dist.get_world_size()
    return {k: float(v) for k, v in zip(keys, t.tolist())}


def cleanup():
    if dist.is_initialized():
        dist.destroy_process_group()
