#!/usr/bin/env bash
# Two-stage training on one H100: stage 1 clean -> stage 2 MediaPipe-noise fine-tune.
# Default: MMFS, ~25 min total (stage budgets MAX_MIN_CLEAN=13, MAX_MIN_NOISY=5 minutes of training,
# plus compile/eval/test overhead). Each stage saves + evaluates when its budget is reached.
# Safe to re-run: each stage auto-resumes from <RUN>/<stage>/latest.pt and is skipped once DONE.
# Run detached so it survives SSH disconnects:
#   tmux new -d -s train 'bash thunder/train_h100.sh'        (attach: tmux attach -t train)
#   or: nohup bash thunder/train_h100.sh >/dev/null 2>&1 &
# Env overrides: NGPU (default: all visible GPUs; >1 -> torchrun DDP), DATA_ROOT, RUN, CONFIG, VENV, MAX_MIN_CLEAN, MAX_MIN_NOISY (0 = no limit),
#                EXTRA_SET (extra key=value config overrides), MMFS_RAW (build the cache if missing).
set -uo pipefail
cd "$(dirname "$0")/.."
VENV=${VENV:-$HOME/skate_venv}
DATA_ROOT=${DATA_ROOT:-$PWD/data/mmfs_cache}
RUN=${RUN:-runs/mmfs_h100}
CONFIG=${CONFIG:-configs/mmfs_h100_30min.yaml}
MAX_MIN_CLEAN=${MAX_MIN_CLEAN:-13}
MAX_MIN_NOISY=${MAX_MIN_NOISY:-5}
EXTRA_SET=${EXTRA_SET:-}
NGPU=${NGPU:-$(nvidia-smi -L 2>/dev/null | grep -c '^GPU' || echo 1)}
[ "${NGPU:-0}" -ge 1 ] 2>/dev/null || NGPU=1
if [ "$NGPU" -gt 1 ]; then
  LAUNCH=(torchrun --standalone --nproc_per_node="$NGPU")   # DDP: per-GPU batch = train.batch_size
else
  LAUNCH=(python)
fi
mkdir -p "$RUN"
LOG="$RUN/train_h100.log"
exec > >(tee -a "$LOG") 2>&1

source "$VENV/bin/activate"
echo "==== $(date) start  host=$(hostname)  run=$RUN  data=$DATA_ROOT  ngpu=$NGPU  launch=${LAUNCH[*]}"
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv || true
if [ ! -f "$DATA_ROOT/programs.npy" ] && [ ! -d "$DATA_ROOT/skeleton" ]; then
  if [ -n "${MMFS_RAW:-}" ]; then
    python scripts/build_mmfs_cache.py --mmfs-root "$MMFS_RAW" --out "$DATA_ROOT" || exit 1
  else
    echo "missing data at $DATA_ROOT (upload data/mmfs_cache, or set MMFS_RAW=<.../MMFS>)"; exit 1
  fi
fi
SPLITS="$RUN/splits.json"
[ -f "$DATA_ROOT/splits.json" ] && SPLITS="$DATA_ROOT/splits.json"   # MMFS: program-level split from the cache

run_stage() {  # $1 = stage name, $2 = minutes budget, rest = extra overrides
  local stage=$1; local minutes=$2; shift 2
  local dir="$RUN/$stage"
  if [ -f "$dir/DONE" ]; then echo "== stage $stage already DONE, skipping"; return 0; fi
  echo "== $(date) stage $stage (auto-resume from $dir/latest.pt if present)"
  "${LAUNCH[@]}" -m skatemodel.train --config "$CONFIG" --ckpt-dir "$dir" --stage-only "$stage" \
      --max-minutes "$minutes" \
      --set data.root="$DATA_ROOT" data.splits_file="$SPLITS" "$@" $EXTRA_SET
  local rc=$?
  if [ ! -f "$dir/DONE" ]; then
    echo "!! stage $stage stopped without DONE (exit $rc). Re-run this script to resume."; exit 1
  fi
}

T0=$(date +%s)
run_stage clean "$MAX_MIN_CLEAN" eval.test_at_end=false
run_stage noisy "$MAX_MIN_NOISY" train.init_from="$RUN/clean/best.pt"

# final artefacts at the top of the run dir
cp "$RUN/noisy/best.pt" "$RUN/final_model.pt"
python - "$RUN" <<'PY'
import json, os, sys
run = sys.argv[1]
out = {}
for st in ("clean", "noisy"):
    p = os.path.join(run, st, "logs", "final_metrics.json")
    if os.path.exists(p):
        out[st] = json.load(open(p))
json.dump(out, open(os.path.join(run, "final_metrics.json"), "w"), indent=1)
for st, m in out.items():
    keys = [k for k in m if k.startswith("test/") and not k.split("/")[-1].startswith("c")]
    print(st, {k: round(m[k], 4) for k in keys if isinstance(m[k], (int, float))})
PY
echo "total wall time: $(( ($(date +%s) - T0) / 60 )) min"
date > "$RUN/DONE"
echo "==== $(date) DONE. Results: $RUN/final_model.pt, $RUN/final_metrics.json, $RUN/*/logs/"
# The instance is intentionally left RUNNING: Thunder has no 'stop' (only 'tnr delete', which
# destroys the disk). Download results from your laptop, then delete the instance there.
