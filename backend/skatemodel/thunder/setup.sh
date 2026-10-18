#!/usr/bin/env bash
# One-time environment setup on a fresh Thunder Compute Ubuntu instance (1x H100).
#   bash thunder/setup.sh
# Env overrides: VENV (default ~/skate_venv), TORCH_INDEX (CUDA wheel index, default cu124).
set -euo pipefail
cd "$(dirname "$0")/.."
VENV=${VENV:-$HOME/skate_venv}
TORCH_INDEX=${TORCH_INDEX:-https://download.pytorch.org/whl/cu124}

echo "== GPU"; nvidia-smi || { echo "nvidia-smi failed: no GPU visible"; exit 1; }

if ! python3 -m venv --help >/dev/null 2>&1 || ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  echo "== installing python3-venv"
  sudo apt-get update -y && sudo apt-get install -y python3-venv python3-pip
fi
command -v tmux >/dev/null || { sudo apt-get update -y && sudo apt-get install -y tmux; } || true

echo "== venv at $VENV"
python3 -m venv "$VENV"
source "$VENV/bin/activate"
pip install --upgrade pip wheel
pip install torch --index-url "$TORCH_INDEX"
pip install -r requirements.txt
pip install -e .

echo "== checks"
python - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda, "available", torch.cuda.is_available())
assert torch.cuda.is_available(), "CUDA not available"
print("device", torch.cuda.get_device_name(0), "bf16", torch.cuda.is_bf16_supported())
from skatemodel.models import build_model, count_params
from skatemodel.utils.config import load_config
m = build_model(load_config("configs/mmfs_h100_30min.yaml")).cuda()
print("params", count_params(m))
m.compile_backbone(dynamic=False)
m.train()
x = torch.randn(2, 640, 17, 15, device="cuda"); mask = torch.ones(2, 640, dtype=torch.bool, device="cuda")
with torch.autocast("cuda", dtype=torch.bfloat16):
    out = m(x, mask)
out["cls"].float().mean().backward()
print("torch.compile + bf16 forward/backward OK")
PY
python -m pytest -q tests
echo "SETUP OK. Activate with: source $VENV/bin/activate"
