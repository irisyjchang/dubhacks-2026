# Training PyTorch on UW Hyak (Klone)

Legend: [V] = stated in the Hyak docs I fetched. [U] = NOT verified in the docs (general knowledge or inferred); check before relying on it.

## 1. Access

- Prerequisite: a UW NetID with Duo 2FA [V]. Every Hyak account needs this.
- You also need a Slurm account (a group). Options [V]:
  - Your PI adds you to their lab group (owner uses groups.uw.edu, group like `u_hyak_mylab`, Membership, Add members).
  - A PI with no nodes can request a Demonstration Account.
  - Student with no PI: pay the Student Technology Fee (STF) and join the Research Computing Club (RCC) to get the `stf` account. The Hyak team does not manage this group; follow the RCC's Hyak access page (URL not fetched) [V].
- Demo account limits [V]: only `ckpt`, `ckpt-g2`, `ckpt-all` partitions; 10 GB home; one job running at a time; max 80 cores, 360 GB RAM, 2 GPUs, 2 nodes.
- SSH [V]: `ssh UWNetID@klone.hyak.uw.edu`, password then Duo. SSH keys are NOT allowed on the login node. Login node is for file moves, light editing, `sbatch`, `hyakalloc`, `hyakstorage` only; heavy work gets throttled (Arbiter2 emails).
- Off campus, Open OnDemand needs the UW VPN (Husky OnNet) [V]. Whether SSH also needs it: [U].
- Open OnDemand (OOD) [V]: https://ondemand.hyak.uw.edu/, log in with NetID + Duo. Dashboard has file upload/download/edit, job monitoring, and Interactive Apps (Desktop, Jupyter, VS Code, MATLAB, RStudio) launched as Slurm jobs.
  - OOD apps default to your 10 GB home. Avoid filling it: make a dir in lab space or `/gscratch/scrubbed/` and `ln -s <path> ~` [V].
  - Jupyter with a conda env: install `ipykernel` in the env and register a kernel; or give an Apptainer image path (use `realpath`) in the "Jupyter Container" field [V].
  - Form fields for GPU selection in Jupyter/VS Code: [U] (docs pages did not list them; the VS Code page was not fetched).

## 2. Storage [V unless noted]

| Location | Quota | Notes |
|---|---|---|
| `/mmfs1/home/<NetID>` (home) | 10 GB, ~250k files, fixed | Configs and small scripts only. |
| `/gscratch/<group>` | 1 TB per contributed slice | Shared lab space, NVMe. Check with `hyakstorage`. Needs a group with storage. |
| `/gscratch/scrubbed/` | 10 TB/user (not guaranteed; 100 TB shared) | Files not accessed for 21 days are deleted. Open permissions by default. |

- No backups anywhere on `/gscratch`. Copy final results elsewhere (Kopah S3 or Lolo archive).
- Recommendation: datasets in `/gscratch/<group>/...` (or scrubbed if you have no group storage, with the purge risk). Checkpoints: group dir if available. On scrubbed, touch/copy final checkpoints out regularly because of the 21-day purge. Conda envs should NOT live in scrubbed (they can be partially purged and corrupt).
- Demo accounts have no group storage, so scrubbed is the practical location [inferred, U].

## 3. Environment

- Modules [V]: on Klone, `module` commands work only on compute nodes (inside `salloc`/`sbatch`). `module load conda`, `module load apptainer`.
- Conda [V]: put envs outside home:
  ```
  module load conda
  conda create --prefix /gscratch/<proj>/<me>/envs/torch python=3.12
  conda activate /gscratch/<proj>/<me>/envs/torch
  ```
  Or set `envs_dirs`/`pkgs_dirs` in `~/.condarc` to a gscratch path.
- PyTorch with CUDA [U: docs give no PyTorch commands]. Typical approach, run on a GPU compute node (allocate with `salloc` first):
  ```
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
  python -c "import torch; print(torch.cuda.is_available())"
  ```
  Pick the CUDA wheel version per pytorch.org; pip wheels bundle the CUDA runtime, so a separate CUDA module should not be needed [U]. Miniforge: the docs only use the `conda` module [V]; no need to install your own.
- Apptainer alternative [V partly]: `module load apptainer`; `apptainer pull docker://nvcr.io/nvidia/pytorch:<tag>` (NGC images ship CUDA). Bind storage with `--bind /gscratch`. The `--nv` GPU flag is [U] (not in the docs page) but is standard Apptainer for GPU access. Default cache is in home; clean with `apptainer cache clean` or point `APPTAINER_CACHEDIR` at node-local `/tmp` (exact path in docs was garbled, verify). Some NGC images need `module load ngc; ngc config set`.

## 4. GPU jobs

- Accounts/partitions [V]: your account determines usable partitions. Run `hyakalloc` to list accounts, utilization and idle resources; `hyakalloc -c` shows checkpoint resources. `sinfo -s` lists partitions.
- GPU partitions [V] (GPUs/node, mem/GPU): `gpu-2080ti` (8, 11 GB), `gpu-rtx6k` (8, 48 GB), `gpu-p100` (4, 16 GB), `gpu-titan` (4, 24 GB), `gpu-a100` (8, 40 GB), `gpu-a40` (8, 48 GB), `gpu-l40` (8, 48 GB), `gpu-l40s` (8, 48 GB), `gpu-h200` (8, 141 GB). Using these directly requires an account that owns/has access to them (a lab group; `stf` access to specific gpu-* partitions: [U], check `hyakalloc`).
- Checkpoint partitions [V]: `ckpt` (idle resources cluster-wide), `ckpt-all` (g1 or g2 nodes), `ckpt-g2`. Use with your account (e.g. `-A stf` or your lab). Jobs can be preempted any time; GPU ckpt jobs are also requeued every 8-9 hours (non-GPU 4-5 h). Idle does not guarantee you get it.
- Max `--time` per partition: [U] (docs page lists none). Format `D-HH:MM:SS` etc.
- GPU request syntax `--gres=gpu:1` (or `--gres=gpu:a100:1`) [U: not in fetched pages; standard Slurm].
- Interactive [V base form]:
  ```
  salloc -A <account> -p ckpt-all -N 1 -c 4 --mem=10G --time=2:30:00
  ```
  For a GPU add `--gres=gpu:1` [U].
- Preemption handling: your code must save checkpoints periodically and resume from the latest on start. Docs mention DMTCP as a generic option [V]; in PyTorch just save `model/optimizer/scheduler/epoch` yourself (see template). Listen for SIGTERM/SIGUSR1 [U] and requeue.

## 5. Data transfer [V]

```
# local -> Klone
rsync -avz --progress ./data/ UWNetID@klone.hyak.uw.edu:/gscratch/<group>/<me>/data/
scp file UWNetID@klone.hyak.uw.edu:/path/to/dir
# Klone -> local
rsync -av UWNetID@klone.hyak.uw.edu:/gscratch/<group>/<me>/runs/ ./runs/
```
- rsync is better for large/resumable transfers; for many small files `tar` first. Each transfer prompts for password + Duo.
- Docs page has an inconsistent host `hyak.klone.uw.edu` in one tar example; use `klone.hyak.uw.edu`.
- OOD Files app can upload/download in the browser (good for small files) [V]; size limits [U]. Use git for code (`git clone` on the login node should be fine [U]).

## 6. sbatch template

Save as `scripts/train.slurm`; submit from the login node with `mkdir -p logs && sbatch scripts/train.slurm`.

```bash
#!/bin/bash
#SBATCH --job-name=train
#SBATCH --account=<account>          # e.g. stf or your lab; see `hyakalloc`
#SBATCH --partition=ckpt-all         # or ckpt-g2, or gpu-a40 etc. if your account has it
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=48G
#SBATCH --gres=gpu:1
#SBATCH --time=08:00:00              # check partition max
#SBATCH --requeue
#SBATCH --signal=B:USR1@120          # send USR1 to the batch shell 120 s before time limit
#SBATCH --open-mode=append           # keep appending to the same log after requeue
#SBATCH --output=logs/%x_%j.out
#SBATCH --error=logs/%x_%j.err

set -euo pipefail

module load conda
conda activate /gscratch/<proj>/<me>/envs/torch

cd /gscratch/<proj>/<me>/dubhacks_2026     # project dir (not scrubbed if possible)
export CKPT_DIR=/gscratch/<proj>/<me>/ckpts/${SLURM_JOB_NAME}   # stable across requeues
mkdir -p "$CKPT_DIR"

echo "Job $SLURM_JOB_ID restart=${SLURM_RESTART_COUNT:-0} on $(hostname) at $(date)"
nvidia-smi

# On USR1 (time limit warning), requeue self. Preemption (SIGTERM) is handled by Slurm requeue
# for ckpt jobs; train.py should also catch SIGTERM and save a checkpoint.
requeue() { echo "Caught signal, requeueing"; scontrol requeue "$SLURM_JOB_ID"; exit 0; }
trap requeue USR1 TERM

# Run in background so the trap can fire; train.py must resume from $CKPT_DIR/latest.pt if present.
python train.py --config configs/x.yaml --ckpt-dir "$CKPT_DIR" --resume auto &
wait $!
echo "Finished at $(date)"
```

Notes for `train.py`: save `latest.pt` (model, optimizer, scheduler, epoch/step, RNG) every N minutes via write-to-temp-then-rename; on start, load it if it exists; catch SIGTERM to save then exit. `--ckpt-dir`/`--resume` flags are assumptions about your script; adapt as needed. The `--requeue`, `--signal`, `--open-mode`, `scontrol requeue` mechanics are standard Slurm and not shown in the Hyak docs [U]; whether `ckpt` jobs are auto-requeued on preemption is stated in the docs [V], but test it with a short job.

## Sources

- https://hyak.uw.edu/ood/getting-started
- https://hyak.uw.edu/ood/apps/jupyter
- https://hyak.uw.edu/docs
- https://hyak.uw.edu/docs/getting-started/account-creation
- https://hyak.uw.edu/docs/getting-started/join-group
- https://hyak.uw.edu/docs/getting-started/ssh-login
- https://hyak.uw.edu/docs/systems/klone/storage
- https://hyak.uw.edu/docs/systems/klone/get-started
- https://hyak.uw.edu/docs/systems/klone/scheduling-jobs
- https://hyak.uw.edu/docs/guides/software/conda-python
- https://hyak.uw.edu/docs/guides/software/containers
- https://hyak.uw.edu/docs/guides/data-transfer/scp-rsync

Not fetched: RCC Hyak access page (stf signup), OOD VS Code page, DMTCP page, pricing KB articles.
