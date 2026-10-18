# Training on UW Hyak (Klone): secondary option

The main target is Thunder Compute (`../thunder/README.md`). This setup uses 2 GPUs with DDP on
checkpoint partitions (preemptible). Replace `NETID` (yours is probably `rss42`), `GROUP`, and
`ACCOUNT` (see `hyakalloc`). If you have no group storage, use `/gscratch/scrubbed/NETID`, but note
that scrubbed deletes files not accessed for 21 days, and conda envs should not live there.

## 1. Upload code and data (from the laptop, repo root `dubhacks_2026/`)

```bash
ssh NETID@klone.hyak.uw.edu "mkdir -p /gscratch/GROUP/NETID/{data,runs,envs}"
rsync -avz --exclude .venv --exclude runs --exclude data skatemodel/ NETID@klone.hyak.uw.edu:/gscratch/GROUP/NETID/skatemodel/
tar -czf /tmp/finefs_data.tgz -C data finefs            # many small files: pack first
rsync -av --progress /tmp/finefs_data.tgz NETID@klone.hyak.uw.edu:/gscratch/GROUP/NETID/data/
ssh NETID@klone.hyak.uw.edu "cd /gscratch/GROUP/NETID/data && tar -xzf finefs_data.tgz && ls finefs"
```

Each command asks for your password and Duo.

## 2. Environment (once, on a compute node)

```bash
ssh NETID@klone.hyak.uw.edu
salloc -A ACCOUNT -p ckpt-all -N 1 -c 4 --mem=16G --gres=gpu:1 --time=1:00:00
cd /gscratch/GROUP/NETID/skatemodel
bash hyak/setup_env.sh /gscratch/GROUP/NETID/envs/skate
python scripts/inspect_finefs.py --data-root /gscratch/GROUP/NETID/data/finefs --n 3   # check format
exit
```

## 3. Edit the sbatch files

In `hyak/train.sbatch` and `hyak/smoke_test.sbatch`, set `--account`, `--partition`, and `PROJ=`.

## 4. Smoke test (about 5 minutes)

```bash
cd /gscratch/GROUP/NETID/skatemodel && mkdir -p logs
sbatch hyak/smoke_test.sbatch
squeue -u NETID
tail -f logs/skate_smoke_*.out        # ends with "HYAK SMOKE TEST PASSED"
```

## 5. Full training

```bash
sbatch hyak/train.sbatch
```

The job checkpoints every 500 steps. On preemption or at the time limit it saves and requeues
itself, then resumes from `runs/skate_base/latest.pt`. It stops requeueing once
`runs/skate_base/DONE` exists.

## 6. Monitor

```bash
squeue -u NETID
tail -f logs/skate_train_*.out
grep EVAL /gscratch/GROUP/NETID/runs/skate_base/logs/train.log | tail
scancel JOBID                         # stop (resume later by re-submitting)
```

## 7. Download results (from the laptop)

```bash
rsync -av NETID@klone.hyak.uw.edu:/gscratch/GROUP/NETID/runs/skate_base/ ./runs_hyak/ \
      --exclude 'latest.prev.pt'
tensorboard --logdir runs_hyak/logs/tb
```
