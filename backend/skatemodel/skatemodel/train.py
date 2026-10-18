"""Training entrypoint (single process, or DDP via torchrun).

    python -m skatemodel.train --config configs/base.yaml --ckpt-dir runs/x
    torchrun --standalone --nproc_per_node=2 -m skatemodel.train --config configs/base.yaml --ckpt-dir runs/x

Preemption-safe: checkpoints every `train.ckpt_every` steps and on SIGUSR1/SIGTERM; with
`--resume auto` (default) it continues from <ckpt-dir>/latest.pt. Writes <ckpt-dir>/DONE when finished.
"""
from __future__ import annotations

import argparse
import logging
import math
import os

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # must be set before importing torch
import signal
import sys
import time
from typing import Dict, List

import numpy as np
import torch
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader, Sampler

from .data import finefs_io
from .data.dataset import ProgramStore, WindowDataset, collate, materialize_batch
from .data.splits import load_splits, make_splits
from .inference import evaluate
from .losses import total_loss
from .models import build_model, count_params
from .utils import dist as du
from .utils.checkpoint import load_latest, rng_state, save_atomic, set_rng_state
from .utils.config import load_config
from .utils.logger import ScalarLogger, setup_logging

log = logging.getLogger("skatemodel.train")


# --------------------------------------------------------------------------------------------
class Stopper:
    """Sets a flag on SIGUSR1 / SIGTERM; the loop checkpoints and exits at the next step."""

    def __init__(self):
        self.flag = False
        self.signame = None
        for sig in (signal.SIGUSR1, signal.SIGTERM):
            signal.signal(sig, self._handler)

    def _handler(self, signum, frame):
        self.flag = True
        self.signame = signal.Signals(signum).name


class ResumableSampler(Sampler):
    """Distributed, epoch-seeded shuffling that can skip already-consumed batches after resume."""

    def __init__(self, n, rank, world, seed, epoch, batch_size, start_batch=0, shuffle=True):
        self.n, self.rank, self.world, self.seed, self.epoch = n, rank, world, seed, epoch
        self.bs, self.start_batch, self.shuffle = batch_size, start_batch, shuffle
        per_rank = int(math.ceil(n / world))
        self.n_batches = per_rank // batch_size

    def __iter__(self):
        if self.shuffle:
            g = torch.Generator()
            g.manual_seed(self.seed * 100003 + self.epoch)
            perm = torch.randperm(self.n, generator=g).tolist()
        else:
            perm = list(range(self.n))
        total = int(math.ceil(self.n / self.world)) * self.world
        perm = (perm * (total // max(1, len(perm)) + 1))[:total]
        mine = perm[self.rank::self.world][: self.n_batches * self.bs]
        return iter(mine[self.start_batch * self.bs:])

    def __len__(self):
        return max(0, (self.n_batches - self.start_batch) * self.bs)


def stage_at(stages: List[Dict], step: int):
    acc = 0
    for i, s in enumerate(stages):
        if step < acc + s["steps"]:
            return i, s, step - acc
        acc += s["steps"]
    return len(stages) - 1, stages[-1], stages[-1]["steps"]


def lr_at(stage: Dict, k: int, min_ratio: float, time_frac: float = 0.0) -> float:
    """Linear warmup + cosine. With --max-minutes the cosine follows max(step, wall-clock) progress
    so the LR is annealed when the deadline hits."""
    warm = stage.get("warmup", 0)
    if k < warm:
        return stage["lr"] * (k + 1) / warm
    prog = max((k - warm) / max(1, stage["steps"] - warm), time_frac)
    return stage["lr"] * (min_ratio + (1 - min_ratio) * 0.5 * (1 + math.cos(math.pi * min(1.0, prog))))


def param_groups(model, wd):
    decay, no_decay = [], []
    for n, p in model.named_parameters():
        if not p.requires_grad:
            continue
        (no_decay if p.ndim <= 1 or n.endswith("importance") else decay).append(p)
    return [{"params": decay, "weight_decay": wd}, {"params": no_decay, "weight_decay": 0.0}]


def _worker_init(_):
    torch.set_num_threads(1)  # avoid CPU oversubscription in DataLoader workers


def setup_backend(device):
    if device.type == "cuda":
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True
        torch.backends.cudnn.benchmark = True
        torch.set_float32_matmul_precision("high")


def amp_dtype_for(cfg, device):
    if device.type == "cuda" and cfg["train"].get("amp", "bf16") == "bf16" and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return None


# --------------------------------------------------------------------------------------------
def make_store(cfg, ids, fps):
    if cfg["data"].get("format", "finefs") == "mmfs":
        from .data.mmfs import MMFSCache
        cache = MMFSCache(cfg["data"]["root"])
        return ProgramStore(cfg["data"]["root"], ids, cache.fps, loader=cache.load_program)
    return ProgramStore(cfg["data"]["root"], ids, fps)


def class_codes_for(cfg):
    if cfg["data"].get("format", "finefs") == "mmfs":
        from .data.mmfs import MMFS_CLASSES
        return MMFS_CLASSES
    return None


def get_splits(cfg, ckpt_dir):
    path = cfg["data"].get("splits_file") or os.path.join(ckpt_dir, "splits.json")
    if cfg["data"].get("format") == "mmfs" and not cfg["data"].get("splits_file"):
        path = os.path.join(cfg["data"]["root"], "splits.json")  # written by scripts/build_mmfs_cache.py
    if du.is_main() and not os.path.exists(path):
        make_splits(cfg["data"]["root"], path, seed=cfg.get("seed", 0),
                    ratios=tuple(cfg["data"].get("split_ratios", (0.7, 0.15, 0.15))))
    du.barrier()
    splits = load_splits(path)
    n_sub = cfg["data"].get("subset")
    if n_sub:  # debugging subset drawn from the saved split (keeps the split leakage-free)
        ratios = cfg["data"].get("split_ratios", (0.7, 0.15, 0.15))
        rng = np.random.default_rng(cfg.get("seed", 0))
        for (k, ids), r in zip(list(splits.items()), ratios):
            ids = list(ids)
            rng.shuffle(ids)
            splits[k] = sorted(ids[:max(1, int(round(n_sub * r)))], key=finefs_io._natural_key)
    return splits, path


def run_eval(model, store, device, cfg, priors, amp_dtype, final=False):
    ecfg = cfg.get("eval", {})
    m = model.module if isinstance(model, DDP) else model
    cc = class_codes_for(cfg)
    metrics = evaluate(m, store, device, cfg.get("infer"), priors, None, amp_dtype, class_codes=cc)
    noisy_mode = ecfg.get("noisy", True)
    if noisy_mode is True or (noisy_mode == "final" and final):
        noisy = evaluate(m, store, device, cfg.get("infer"), priors, cfg.get("aug", {}), amp_dtype, class_codes=cc)
        metrics.update({f"noisy/{k}": v for k, v in noisy.items()})
    m.train()
    return {f"{k}": v for k, v in metrics.items()}


def is_better(metric, best, mode):
    if metric is None or not np.isfinite(metric):
        return False
    return best is None or (metric < best if mode == "min" else metric > best)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--ckpt-dir", default=None)
    ap.add_argument("--resume", default="auto", help="auto | none | path/to/ckpt.pt")
    ap.add_argument("--eval-only", action="store_true")
    ap.add_argument("--eval-split", default="test")
    ap.add_argument("--stage-only", default=None,
                    help="run only the named stage from train.stages (e.g. clean / noisy)")
    ap.add_argument("--device", default=None, help="auto | cuda | mps | cpu (default: cfg train.device or auto)")
    ap.add_argument("--set", nargs="*", default=[], help="config overrides key.sub=value")
    ap.add_argument("--max-minutes", type=float, default=0,
                    help="wall-clock budget for this invocation: at the deadline save, evaluate, finish")
    ap.add_argument("--stop-after", type=int, default=0,
                    help="testing: behave as if SIGUSR1 arrived after this global step")
    args = ap.parse_args(argv)

    cfg = load_config(args.config, args.set)
    rank, world, local_rank, device = du.init_distributed(args.device or cfg["train"].get("device", "auto"))
    setup_backend(device)
    ckpt_dir = args.ckpt_dir or cfg.get("output", {}).get("dir", "runs/default")
    os.makedirs(ckpt_dir, exist_ok=True)
    log_dir = os.path.join(ckpt_dir, "logs")
    setup_logging(log_dir, rank)
    seed = int(cfg.get("seed", 0))
    torch.manual_seed(seed + rank)
    np.random.seed(seed + rank)
    tcfg = cfg["train"]
    fps = float(cfg["data"].get("fps", finefs_io.FPS))

    splits, split_path = get_splits(cfg, ckpt_dir)
    log.info("world=%d device=%s splits=%s %s", world, device, split_path, {k: len(v) for k, v in splits.items()})

    model = build_model(cfg).to(device)
    n_params = count_params(model)
    log.info("model params: %.2fM", n_params / 1e6)
    amp_dtype = amp_dtype_for(cfg, device)
    scal = ScalarLogger(log_dir, enabled=(rank == 0), tensorboard=cfg.get("logging", {}).get("tensorboard", True))

    # ---------------------------------------------------------------- eval-only
    if args.eval_only:
        if rank == 0:
            p = args.resume if os.path.isfile(args.resume) else os.path.join(ckpt_dir, "best.pt")
            if not os.path.exists(p):
                p = os.path.join(ckpt_dir, "latest.pt")
            st = torch.load(p, map_location="cpu", weights_only=False)
            model.load_state_dict(st["model"])
            store = make_store(cfg, splits[args.eval_split], fps)
            metrics = run_eval(model, store, device, cfg, st.get("priors"), amp_dtype)
            log.info("%s metrics (%s): %s", args.eval_split, p, metrics)
            scal.dump_json(f"metrics_{args.eval_split}.json", metrics)
        du.cleanup()
        return

    # ---------------------------------------------------------------- data
    train_store = make_store(cfg, splits["train"], fps)
    priors = train_store.bv_priors()
    val_store = None
    if rank == 0:
        ids = splits["val"][: cfg.get("eval", {}).get("max_programs") or None]
        val_store = make_store(cfg, ids, fps)

    # ---------------------------------------------------------------- model / optim
    if world > 1 and device.type == "cuda" and tcfg.get("sync_bn", True):
        model = torch.nn.SyncBatchNorm.convert_sync_batchnorm(model)
    optim = torch.optim.AdamW(param_groups(model, tcfg.get("weight_decay", 0.05)), lr=1e-3, betas=(0.9, 0.999))
    stages = tcfg["stages"]
    if args.stage_only:
        stages = [s for s in stages if s["name"] == args.stage_only]
        if not stages:
            raise ValueError(f"--stage-only {args.stage_only}: no such stage in train.stages")
    total_steps = sum(s["steps"] for s in stages)

    step, epoch, batch_in_epoch, best = 0, 0, 0, None
    state = None
    if args.resume == "auto":
        state = load_latest(ckpt_dir)
    elif args.resume not in ("none", "") and os.path.isfile(args.resume):
        state = torch.load(args.resume, map_location="cpu", weights_only=False)
    if state is not None:
        model.load_state_dict(state["model"])
        optim.load_state_dict(state["optim"])
        step, epoch, batch_in_epoch = state["step"], state["epoch"], state["batch_in_epoch"]
        best = state.get("best")
        set_rng_state(state.get("rng", {}))
        log.info("RESUMED from step %d (epoch %d, batch %d, best=%s)", step, epoch, batch_in_epoch, best)
    elif tcfg.get("init_from"):
        st = torch.load(tcfg["init_from"], map_location="cpu", weights_only=False)
        model.load_state_dict(st["model"])
        log.info("initialised weights from %s", tcfg["init_from"])

    if tcfg.get("compile", False) and device.type == "cuda":
        raw = model
        raw.compile_backbone(dynamic=False, mode=tcfg.get("compile_mode", "default"))
        log.info("torch.compile enabled for the backbone (set train.compile=false to disable)")
    gpu_store = None
    if cfg["data"].get("gpu_preload", False) and device.type in ("cuda", "mps"):
        gpu_store = train_store.tensors(device)
        log.info("preloaded training skeletons onto %s (%.2f GB); augmentation+features run on GPU",
                 device, train_store.flat.nbytes / 1e9)
    ddp_model = DDP(model, device_ids=[local_rank] if device.type == "cuda" else None) if world > 1 else model
    raw_model = model
    ddp_params = [p for p in model.parameters() if p.requires_grad]

    def save(name="latest.pt"):
        if rank != 0:
            return
        st = {"model": raw_model.state_dict(), "optim": optim.state_dict(), "step": step, "epoch": epoch,
              "batch_in_epoch": batch_in_epoch, "best": best, "cfg": cfg, "priors": priors,
              "rng": rng_state(), "n_params": n_params}
        save_atomic(st, os.path.join(ckpt_dir, name), backup=(name == "latest.pt"))
        log.info("saved %s at step %d", name, step)

    stopper = Stopper()
    W, stride = cfg["data"]["window"], cfg["data"]["stride"]
    bs = tcfg["batch_size"]
    lw = cfg.get("loss", {})
    alpha = torch.tensor(lw["class_alpha"], dtype=torch.float32) if lw.get("class_alpha") else None
    eval_every, ckpt_every, log_every = tcfg["eval_every"], tcfg["ckpt_every"], tcfg["log_every"]
    sel_metric = cfg.get("eval", {}).get("select_metric", "tes/mae")
    sel_mode = cfg.get("eval", {}).get("select_mode", "min")
    ddp_model.train()
    t0, last_log_step = time.time(), step
    run_losses: Dict[str, float] = {}
    stopped = False
    t_start = time.time()
    deadline = t_start + args.max_minutes * 60 if args.max_minutes else None
    if deadline:
        log.info("wall-clock budget: %.1f min", args.max_minutes)

    while step < total_steps and not stopped:
        si, stage, _ = stage_at(stages, step)
        ds = WindowDataset(train_store, W, stride, train=True, aug_cfg=cfg.get("aug", {}),
                           noise=bool(stage.get("noise", False)), seed=seed, materialize=gpu_store is None)
        sel_metric = stage.get("select_metric", sel_metric)
        ds.set_epoch(epoch)
        sampler = ResumableSampler(len(ds), rank, world, seed, epoch, bs, start_batch=batch_in_epoch)
        if len(sampler) == 0:
            epoch, batch_in_epoch = epoch + 1, 0
            if sampler.n_batches == 0:
                raise RuntimeError("dataset smaller than one batch per rank; lower train.batch_size")
            continue
        nw = cfg["data"].get("num_workers", 4)
        loader = DataLoader(ds, batch_size=bs, sampler=sampler, num_workers=nw, collate_fn=collate,
                            pin_memory=device.type == "cuda", drop_last=True, worker_init_fn=_worker_init,
                            prefetch_factor=cfg["data"].get("prefetch_factor", 4) if nw > 0 else None)
        log.info("stage=%s noise=%s epoch=%d start_batch=%d (%d batches)", stage["name"],
                 stage.get("noise", False), epoch, batch_in_epoch, len(sampler) // bs)
        stage_changed = False
        for batch in loader:
            k_in_stage = stage_at(stages, step)[2]
            # rank 0's clock decides (broadcast) so LR schedule + deadline stop are identical on all ranks
            elapsed = du.broadcast_float(time.time() - t_start, device) if deadline else 0.0
            tfrac = elapsed / (deadline - t_start) if deadline else 0.0
            lr = lr_at(stage, k_in_stage, tcfg.get("min_lr_ratio", 0.02), tfrac)
            for g in optim.param_groups:
                g["lr"] = lr
            if gpu_store is not None:
                x = materialize_batch(gpu_store, batch["plan"], cfg.get("aug", {}), True)
            else:
                x = batch["x"].to(device, non_blocking=True)
            mask = batch["mask"].to(device, non_blocking=True)
            b = {"labels": batch["labels"].to(device), "reg": batch["reg"].to(device),
                 "elem": {k: v.to(device) for k, v in batch["elem"].items()}}
            with torch.autocast(device_type=device.type, dtype=amp_dtype, enabled=amp_dtype is not None):
                out = ddp_model(x, mask, batch["segs"].to(device))
            loss, parts = total_loss(out, b, lw, alpha)
            if world > 1:  # heads whose loss term is absent in this rank's batch (e.g. no jumps) would leave
                # params without grads -> DDP collectives mismatch across ranks; tie every param into the graph
                loss = loss + 0.0 * sum(p.view(-1)[0] for p in ddp_params)
            optim.zero_grad(set_to_none=True)
            loss.backward()
            gn = torch.nn.utils.clip_grad_norm_(ddp_model.parameters(), tcfg.get("grad_clip", 1.0))
            optim.step()
            step += 1
            batch_in_epoch += 1
            for k, v in parts.items():
                run_losses[k] = run_losses.get(k, 0.0) + v
            run_losses["loss"] = run_losses.get("loss", 0.0) + float(loss.detach())
            run_losses["grad_norm"] = run_losses.get("grad_norm", 0.0) + float(gn)

            if step % log_every == 0:
                n = step - last_log_step
                avg = du.all_reduce_mean({k: v / n for k, v in run_losses.items()}, device)
                dt = time.time() - t0
                avg.update({"lr": lr, "steps_per_s": n / dt, "epoch": epoch, "stage": si})
                if rank == 0:
                    log.info("step %d/%d %s", step, total_steps,
                             " ".join(f"{k}={v:.4g}" for k, v in avg.items()))
                scal.log("train", step, avg)
                run_losses, t0, last_log_step = {}, time.time(), step

            if args.stop_after and step >= args.stop_after:
                stopper.flag, stopper.signame = True, "simulated preemption (--stop-after)"
            stop_now = du.any_true(stopper.flag, device)
            if step % ckpt_every == 0 or stop_now:
                save()
                du.barrier()
            if stop_now:
                log.warning("received %s: checkpoint saved at step %d, exiting for requeue",
                            stopper.signame or "stop signal (other rank)", step)
                stopped = True
                break
            if deadline and elapsed >= deadline - t_start:
                log.info("wall-clock budget reached at step %d -> final eval", step)
                total_steps = step
            if step % eval_every == 0 or step == total_steps:
                if rank == 0:
                    metrics = run_eval(raw_model, val_store, device, cfg, priors, amp_dtype,
                                       final=step == total_steps)
                    log.info("EVAL step %d: %s", step, " ".join(f"{k}={v:.4g}" for k, v in metrics.items()
                                                                  if "/c" not in k))
                    scal.log("val", step, metrics)
                    if is_better(metrics.get(sel_metric), best, sel_mode):
                        best = metrics[sel_metric]
                        save("best.pt")
                    save()
                du.barrier()
                ddp_model.train()
            if step >= total_steps:
                break
            if stage_at(stages, step)[0] != si:
                stage_changed = True
                break
        else:
            epoch, batch_in_epoch = epoch + 1, 0
        if stage_changed:  # restart loader with new augmentation settings on a fresh epoch
            epoch, batch_in_epoch = epoch + 1, 0
            save()

    if not stopped:
        save()
        if rank == 0:
            final = {"n_params": n_params, "best_" + sel_metric: best}
            best_p = os.path.join(ckpt_dir, "best.pt")
            if cfg.get("eval", {}).get("test_at_end", True) and splits.get("test"):
                st = torch.load(best_p if os.path.exists(best_p) else os.path.join(ckpt_dir, "latest.pt"),
                                map_location="cpu", weights_only=False)
                raw_model.load_state_dict(st["model"])
                test_store = make_store(cfg, splits["test"], fps)
                tm = run_eval(raw_model, test_store, device, cfg, priors, amp_dtype, final=True)
                final.update({f"test/{k}": v for k, v in tm.items()})
                scal.log("test", step, tm)
                log.info("TEST: %s", " ".join(f"{k}={v:.4g}" for k, v in tm.items() if "/c" not in k))
            scal.dump_json("final_metrics.json", final)
            with open(os.path.join(ckpt_dir, "DONE"), "w") as f:
                f.write(f"finished at step {step}\n")
            log.info("training finished at step %d", step)
    du.barrier()
    du.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
