#!/usr/bin/env bash
# Create the conda env in /gscratch (NOT home, NOT scrubbed). Run on a COMPUTE node
# (modules only work there), e.g. inside:  salloc -A <account> -p ckpt-all -N 1 -c 4 --mem=16G --gres=gpu:1 --time=1:00:00
#   bash hyak/setup_env.sh /gscratch/<group>/<netid>/envs/skate
set -euo pipefail
ENV_PREFIX=${1:?usage: setup_env.sh /gscratch/<group>/<netid>/envs/skate}
TORCH_INDEX=${TORCH_INDEX:-https://download.pytorch.org/whl/cu124}
cd "$(dirname "$0")/.."
module load conda
# keep the conda package cache out of the 10 GB home
export CONDA_PKGS_DIRS=$(dirname "$ENV_PREFIX")/conda_pkgs
conda create -y --prefix "$ENV_PREFIX" python=3.11
conda activate "$ENV_PREFIX"
pip install --no-cache-dir torch --index-url "$TORCH_INDEX"
pip install --no-cache-dir -r requirements.txt
pip install --no-cache-dir -e .
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())"
python -m pytest -q tests
echo "env ready: conda activate $ENV_PREFIX"
