# Training on Thunder Compute (1x H100 80GB), MMFS, about 30 minutes

Cost: H100 SXM is $3.20/GPU-hr, billed per minute while the instance exists. A full run is about
25 minutes of training plus setup, roughly $2–3. CLI commands come from `docs/thunder_guide.md`;
items marked "verify" were not tested against a live account.

## 0. Laptop: prepare the data cache (once, about 10 s) and install the CLI

```bash
cd dubhacks_2026/skatemodel
.venv/bin/python scripts/build_mmfs_cache.py --mmfs-root ../data/mmfs/MMFS --out data/mmfs_cache
#  -> data/mmfs_cache/{programs.npy (836 MB), index.json, splits.json}: 701 programs, 4912 aligned elements
curl -fLO https://storage.googleapis.com/thunder-cli/tnr/releases/latest/macos/tnr_darwin_arm64.pkg
open tnr_darwin_arm64.pkg && tnr login
```

## 1. Create the instance

```bash
tnr create          # interactive: H100, 1 GPU, template "base", disk 100 GB (verify flags in the menu)
tnr status --no-wait                # wait for RUNNING; note the ID (0 below)
tnr connect 0                       # run `echo $HOME` (e.g. /home/ubuntu), then `exit`
```

## 2. Upload code and data (from `dubhacks_2026/`)

```bash
ID=0; RHOME=/home/ubuntu                       # <-- set these
tar --exclude=skatemodel/.venv --exclude=skatemodel/runs --exclude=skatemodel/data/mmfs_cache --exclude=skatemodel/data/mmfs_cache_small --exclude=skatemodel/data/synthetic --exclude=__pycache__ -czf /tmp/skate_code.tgz skatemodel
tar -czf /tmp/mmfs_cache.tgz -C skatemodel/data mmfs_cache
tnr scp /tmp/skate_code.tgz $ID:$RHOME/
tnr scp /tmp/mmfs_cache.tgz $ID:$RHOME/
```

`rsync` over plain ssh may also work after `tnr connect` writes `~/.ssh/config` (check the host alias
with `grep -A3 Host ~/.ssh/config`).

## 3. On the instance: unpack and set up (about 5 minutes)

```bash
tnr connect 0
cd ~ && tar -xzf skate_code.tgz && mkdir -p skatemodel/data && tar -xzf mmfs_cache.tgz -C skatemodel/data
cd ~/skatemodel && bash thunder/setup.sh       # venv ~/skate_venv, CUDA torch, compile+bf16 check, tests
```

## 4. Train (about 25 minutes, detached)

```bash
cd ~/skatemodel
tmux new -d -s train 'bash thunder/train_h100.sh'
# or: nohup bash thunder/train_h100.sh >/dev/null 2>&1 &
```

What the script does:
- Stage 1 (`clean`): up to 13 minutes of training (`MAX_MIN_CLEAN`), then save, validate, and write `runs/mmfs_h100/clean/DONE`.
- Stage 2 (`noisy`, MediaPipe-style noise fine-tune starting from `clean/best.pt`): up to 5 minutes (`MAX_MIN_NOISY`), then save, validate, and evaluate on the test programs.
- At the end it writes `runs/mmfs_h100/{final_model.pt, final_metrics.json, DONE}`, prints `DONE`, and
  **leaves the instance running**. Thunder has no stop command and `tnr delete` destroys the disk,
  so download the results first (step 6).

The script is safe to re-run: it resumes from `latest.pt` and skips finished stages. Options:

```bash
MAX_MIN_CLEAN=20 MAX_MIN_NOISY=8 bash thunder/train_h100.sh        # longer budget
EXTRA_SET="train.compile=false" bash thunder/train_h100.sh         # if torch.compile fails
EXTRA_SET="train.batch_size=16" bash thunder/train_h100.sh         # if out of memory
```

`EXTRA_SET` is split on spaces, so each override must be a single `key=value` token with no spaces.

## 5. Monitor

```bash
tail -f ~/skatemodel/runs/mmfs_h100/train_h100.log     # everything; look for steps_per_s
grep EVAL ~/skatemodel/runs/mmfs_h100/*/logs/train.log
nvidia-smi
tmux attach -t train                                    # detach: Ctrl-b d
ls ~/skatemodel/runs/mmfs_h100/DONE                     # exists when finished
```

## 6. Download results, then delete the instance (from the laptop)

```bash
ID=0; RHOME=/home/ubuntu
mkdir -p runs_h100
tnr scp $ID:$RHOME/skatemodel/runs/mmfs_h100/final_metrics.json runs_h100/
tnr scp $ID:$RHOME/skatemodel/runs/mmfs_h100/final_model.pt     runs_h100/
#   (on the instance, optional full logs) cd ~/skatemodel && tar -czf ~/mmfs_run.tgz runs/mmfs_h100 --exclude='*.prev.pt'
tnr scp $ID:$RHOME/mmfs_run.tgz runs_h100/
tnr delete 0                     # stops billing; permanently deletes the disk
```

## Use the model (laptop)

```bash
.venv/bin/python scripts/predict.py --ckpt runs_h100/final_model.pt --npz ../data/mmfs/MMFS/skeleton/n38_p01.npy --format mmfs --program-type fs
.venv/bin/python scripts/cut_jumps.py --input ../data/mmfs/MMFS/skeleton/n38_p01.npy --format mmfs --ckpt runs_h100/final_model.pt --out jumps/
```

## Older FineFS configuration

FineFS (3D) is unavailable. If it ever arrives, run:
`CONFIG=configs/h100.yaml DATA_ROOT=$PWD/data/finefs RUN=runs/h100 MAX_MIN_CLEAN=0 MAX_MIN_NOISY=0 bash thunder/train_h100.sh`
