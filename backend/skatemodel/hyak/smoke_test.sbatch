#!/bin/bash
# ~5-minute GPU smoke test on real data: 150 steps (clean+noisy), eval, checkpoint, resume.
#   mkdir -p logs && sbatch hyak/smoke_test.sbatch
#SBATCH --job-name=skate_smoke
#SBATCH --account=CHANGE_ME
#SBATCH --partition=ckpt-all
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --time=00:20:00
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

PROJ=/gscratch/CHANGE_ME_GROUP/CHANGE_ME_NETID
ENV=$PROJ/envs/skate
CODE=$PROJ/skatemodel
DATA=$PROJ/data/finefs
RUN=$PROJ/runs/smoke_$SLURM_JOB_ID

set -euo pipefail
module load conda
conda activate "$ENV"
cd "$CODE"
nvidia-smi
python scripts/inspect_finefs.py --data-root "$DATA" --n 2
COMMON=(--config configs/hyak_smoke.yaml --ckpt-dir "$RUN" --set data.root="$DATA" data.splits_file="$PROJ/runs/skate_base/splits.json")
mkdir -p "$PROJ/runs/skate_base"
python -m skatemodel.train "${COMMON[@]}" --stop-after 60          # simulated preemption
python -m skatemodel.train "${COMMON[@]}"                          # auto-resume -> finish
grep "RESUMED" "$RUN/logs/train.log"
test -f "$RUN/DONE" && echo "HYAK SMOKE TEST PASSED ($RUN)"
