#!/bin/bash
# Full 2-GPU DDP training on Hyak (Klone). Preemption-safe: requeues itself and auto-resumes.
#   mkdir -p logs && sbatch hyak/train.sbatch
#SBATCH --job-name=skate_train
#SBATCH --account=CHANGE_ME           # e.g. stf or your lab group; see `hyakalloc`
#SBATCH --partition=ckpt-all          # ckpt / ckpt-g2 / ckpt-all, or gpu-a40 etc. if your account owns it
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:2                  # or gpu:a40:2 etc.
#SBATCH --cpus-per-task=16
#SBATCH --mem=96G
#SBATCH --time=08:00:00               # ckpt GPU jobs are requeued every ~8-9 h anyway
#SBATCH --requeue
#SBATCH --signal=B:USR1@180           # USR1 to this batch shell 3 min before the time limit
#SBATCH --open-mode=append
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

# ---- edit these paths ----
PROJ=/gscratch/CHANGE_ME_GROUP/CHANGE_ME_NETID          # e.g. /gscratch/scrubbed/<netid> if no group storage
ENV=$PROJ/envs/skate
CODE=$PROJ/skatemodel
DATA=$PROJ/data/finefs
RUN=$PROJ/runs/skate_base                               # stable across requeues
CONFIG=configs/base.yaml
# --------------------------

set -uo pipefail
module load conda
conda activate "$ENV"
cd "$CODE"
mkdir -p "$RUN"
echo "job $SLURM_JOB_ID restart=${SLURM_RESTART_COUNT:-0} host=$(hostname) $(date)"
nvidia-smi || true
if [ -f "$RUN/DONE" ]; then echo "already DONE"; exit 0; fi

NGPU=$(nvidia-smi -L | wc -l)
torchrun --standalone --nproc_per_node="$NGPU" -m skatemodel.train --config "$CONFIG" \
    --ckpt-dir "$RUN" --resume auto \
    --set data.root="$DATA" data.splits_file="$RUN/splits.json" &
TR=$!

# USR1 (time limit) or TERM (preemption): forward USR1 to the training workers (children of
# torchrun; not torchrun itself, which would die on USR1), let them checkpoint, then requeue.
on_signal() {
  echo "$(date) caught signal; asking workers to checkpoint"
  pkill -USR1 -P "$TR" || true
  wait "$TR"
  if [ ! -f "$RUN/DONE" ]; then scontrol requeue "$SLURM_JOB_ID" || true; fi
  exit 0
}
trap on_signal USR1 TERM
wait "$TR"; rc=$?
# wait returns early when a trapped signal arrives; the trap handles that case
echo "torchrun exited rc=$rc $(date)"
if [ ! -f "$RUN/DONE" ] && [ "$rc" -eq 0 ]; then scontrol requeue "$SLURM_JOB_ID" || true; fi
exit $rc
