#!/usr/bin/env bash
# End-to-end CPU smoke test on synthetic data:
#   unit tests -> synthetic data -> train (simulated preemption at step 5) -> auto-resume to the end
#   (incl. clean->noisy stage switch, eval, test) -> real SIGUSR1 handling -> 2-process DDP (gloo)
#   -> predict on one program.
# Usage: bash scripts/smoke_test.sh   (from the skatemodel/ directory; PY=python override allowed)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-.venv/bin/python}
RUN=runs/smoke_cpu
rm -rf "$RUN" runs/smoke_ddp runs/smoke_sig runs/smoke_mps runs/mmfs_smoke_deadline data/synthetic

echo "== 1. unit tests"
$PY -m pytest -q tests

echo "== 2. synthetic data"
$PY scripts/make_synthetic.py --out data/synthetic --n 24 --duration-scale 0.35

echo "== 3. train, simulated preemption after step 5"
$PY -m skatemodel.train --config configs/smoke_cpu.yaml --ckpt-dir $RUN --stop-after 5
test -f $RUN/latest.pt && ! test -f $RUN/DONE && echo "OK: checkpoint saved, not DONE"

echo "== 4. auto-resume to completion"
$PY -m skatemodel.train --config configs/smoke_cpu.yaml --ckpt-dir $RUN
grep -q "RESUMED from step 5" $RUN/logs/train.log && echo "OK: resumed from step 5"
test -f $RUN/DONE && test -f $RUN/best.pt && echo "OK: DONE + best.pt"
cat $RUN/logs/final_metrics.json | head -40

echo "== 5. real SIGUSR1 -> checkpoint + clean exit"
$PY -m skatemodel.train --config configs/smoke_cpu.yaml --ckpt-dir runs/smoke_sig \
    --set train.stages='[{name: clean, steps: 400, noise: false, lr: 0.0005, warmup: 2}]' \
          train.eval_every=100000 train.ckpt_every=100000 &
PID=$!
for i in $(seq 1 120); do
  grep -q "step 4/" runs/smoke_sig/logs/train.log 2>/dev/null && break; sleep 1
done
kill -USR1 $PID
wait $PID
grep -q "received SIGUSR1" runs/smoke_sig/logs/train.log && test -f runs/smoke_sig/latest.pt \
  && echo "OK: SIGUSR1 handled, checkpoint written"

echo "== 6. DDP with 2 CPU processes (gloo)"
$PY -m torch.distributed.run --nnodes=1 --nproc_per_node=2 --master_addr=127.0.0.1 --master_port=29533 -m skatemodel.train \
    --config configs/smoke_cpu.yaml --ckpt-dir runs/smoke_ddp \
    --set data.splits_file=$RUN/splits.json eval.test_at_end=false \
          train.stages='[{name: clean, steps: 4, noise: false, lr: 0.0005, warmup: 1}]'
test -f runs/smoke_ddp/DONE && echo "OK: DDP run finished"

echo "== 7. mac_small on auto device (MPS if available) with GPU-preload batched augmentation"
$PY -m skatemodel.train --config configs/mac_small.yaml --ckpt-dir runs/smoke_mps \
    --set data.root=data/synthetic data.splits_file=$RUN/splits.json data.gpu_preload=true \
          data.num_workers=0 data.window=256 infer.window=256 infer.stride=192 train.batch_size=4 \
          train.log_every=2 train.eval_every=6 eval.max_programs=2 eval.test_at_end=false \
          train.stages='[{name: clean, steps: 3, noise: false, lr: 0.001, warmup: 1}, {name: noisy, steps: 3, noise: true, lr: 0.0003, warmup: 1}]'
test -f runs/smoke_mps/DONE && echo "OK: mac_small run finished"

echo "== 8. predict"
$PY scripts/predict.py --ckpt $RUN/best.pt --npz data/synthetic/skeleton/1.npz --program-type fs | head -20
echo "== 9. MMFS (real 2D data subset): train -> preempt -> resume -> eval/test, wall-clock deadline"
MMFS_RAW=${MMFS_RAW:-../data/mmfs/MMFS}
if [ -d "$MMFS_RAW" ]; then
  [ -f data/mmfs_cache_small/programs.npy ] || $PY scripts/build_mmfs_cache.py --mmfs-root "$MMFS_RAW" --out data/mmfs_cache_small --max-programs 30
  rm -rf runs/mmfs_smoke
  $PY -m skatemodel.train --config configs/mmfs_smoke.yaml --stop-after 5
  $PY -m skatemodel.train --config configs/mmfs_smoke.yaml
  grep -q "RESUMED from step 5" runs/mmfs_smoke/logs/train.log && test -f runs/mmfs_smoke/DONE && echo "OK: MMFS resume + DONE"
  $PY -m skatemodel.train --config configs/mmfs_smoke.yaml --ckpt-dir runs/mmfs_smoke_deadline --stage-only clean \
      --max-minutes 0.2 --set train.eval_every=100000 eval.test_at_end=false \
      train.stages='[{name: clean, steps: 100000, noise: false, lr: 0.001, warmup: 5}]'
  grep -q "wall-clock budget reached" runs/mmfs_smoke_deadline/logs/train.log && echo "OK: --max-minutes deadline"
else
  echo "(skipped: no MMFS at $MMFS_RAW)"
fi
echo "SMOKE TEST PASSED"
