# Thunder Compute CLI (`tnr`) Guide

Research notes compiled from the official Thunder Compute docs. Nothing here was installed, logged in, or executed. Items marked **[UNVERIFIED]** conflict across sources or were not found in official docs.

Primary sources:
- CLI quickstart: https://www.thundercompute.com/docs/cli/quickstart.md
- CLI reference (auth): https://www.thundercompute.com/docs/cli-reference
- Authentication: https://www.thundercompute.com/docs/cli/operations/authentication.md
- Creating instances: https://www.thundercompute.com/docs/cli/operations/creating-instances.md
- Modifying instances: https://www.thundercompute.com/docs/cli/operations/modifying-instances.md
- Monitoring: https://www.thundercompute.com/docs/cli/operations/monitoring-instances.md
- Connecting: https://www.thundercompute.com/docs/cli/operations/connecting-to-instances.md
- SSH: https://www.thundercompute.com/docs/cli/operations/ssh.md
- Port forwarding: https://www.thundercompute.com/docs/cli/operations/port-forwarding.md
- File transfers: https://www.thundercompute.com/docs/cli/operations/file-transfers.md
- Deleting: https://www.thundercompute.com/docs/cli/operations/deleting-instances.md
- Snapshots: https://www.thundercompute.com/docs/cli/operations/snapshots.md
- Stopping guide: https://www.thundercompute.com/docs/guides/stopping-instances.md
- Billing: https://www.thundercompute.com/docs/billing.md
- Pricing: https://www.thundercompute.com/pricing
- Technical specs: https://www.thundercompute.com/docs/technical-specs.md
- Full docs index: https://www.thundercompute.com/docs/llms.txt

## 1. Install on macOS

Official quickstart offers a `.pkg` installer (no Homebrew or pip option is documented on the official page):

- Apple Silicon: https://storage.googleapis.com/thunder-cli/tnr/releases/latest/macos/tnr_darwin_arm64.pkg
- Intel: https://storage.googleapis.com/thunder-cli/tnr/releases/latest/macos/tnr_darwin_amd64.pkg

```bash
# Apple Silicon example (download, then open the installer)
curl -fLO https://storage.googleapis.com/thunder-cli/tnr/releases/latest/macos/tnr_darwin_arm64.pkg
open tnr_darwin_arm64.pkg
```

Verify afterward with `tnr --help` (**[UNVERIFIED]**, command not in the fetched docs).

**[UNVERIFIED]** A search snippet said `pip install tnr` is the quickstart method. The fetched official quickstart shows only the `.pkg` installers, so treat pip as unconfirmed.

## 2. Login and auth

```bash
tnr login        # opens browser for OAuth
tnr logout       # deletes the stored token file
```

- `tnr login` opens the browser for OAuth. Press `T` during login to paste an API token generated in the Thunder console instead.
- For scripts/automation, set the environment variable:
  ```bash
  export TNR_API_TOKEN=your_token_here
  ```
- Token file location: **[UNVERIFIED]**. The fetched page says `tnr logout` deletes the token file but does not give its path. A search snippet claimed `~/.thunder/token`, which is not confirmed.
- A payment method must be on file before creating instances: https://console.thundercompute.com/settings/billing

## 3. Create an instance with 1x H100

The official docs say `tnr create` with no flags opens an interactive menu. Documented flags:

```bash
tnr create                       # interactive menu
tnr create --gpu <type> --num-gpus 1 --vcpus <n> --template base --disk <GB>
```

| Flag | Documented meaning |
|---|---|
| `--gpu` | GPU type. Official docs do not list values; run `tnr create` to see current options. |
| `--num-gpus` | 1, 2, 4, or 8 "when available". Use `1`. |
| `--vcpus` | Options vary by GPU type and count. Not listed. |
| `--template` | `base`, `comfy-ui`, `ollama`, or a snapshot name. |
| `--disk` | Disk GB. Range varies by GPU configuration. Persistent disk is 100 to 4000 GB per technical specs. |

Example from the official creating-instances page (uses A6000, not H100):
```bash
tnr create --gpu a6000 --num-gpus 1 --vcpus 8 --template base --disk 100
```

H100 specifics:
- Pricing lists one H100 option: **H100 SXM, 80 GB, $3.20/GPU-hr on-demand** (https://www.thundercompute.com/pricing). No PCIe variant listed.
- **[UNVERIFIED]** The `--gpu` value for H100 (e.g., `h100`) is not stated in any fetched official page. Confirm by running `tnr create` interactively and reading the menu, or by checking the pricing page.
- **[UNVERIFIED] Prototyping vs production mode:** A search snippet showed `tnr create --mode prototyping --gpu t4 --vcpus 8 --template base --disk-size-gb 100`. Neither the creating-instances page nor the quickstart mentions `--mode`, and the snippet's `--disk-size-gb` conflicts with the official `--disk`. Do not rely on the snippet. No prototyping/production distinction was found in official docs.

## 4. Listing status

```bash
tnr status              # live monitoring until state changes
tnr status --no-wait    # single snapshot, then exit
```

States documented: `CREATING` (provisioning), `RUNNING` (ready), `RESTORING` (restoring from snapshot), `DELETING` (being removed).

## 5. Connecting

```bash
tnr connect             # interactive picker
tnr connect 0           # connect directly by instance ID
```

- The CLI sets up `~/.ssh/config` automatically on first connect (per the connecting page). The block it writes is not shown in the docs.
- Manual SSH: the official SSH page says "Manual SSH setup is not available in the CLI" and is only in the console: https://www.thundercompute.com/docs/console/operations/ssh **[UNVERIFIED]** whether a generic `ssh <alias>` works after `tnr connect`.
- Port forwarding (the CLI does not use `-L`):
  ```bash
  tnr ports forward                        # interactive
  tnr ports forward 0 --add 8080           # expose one port
  tnr ports forward 0 --add 8080,3000,5000 # several ports
  tnr ports forward 0 --remove 8080        # stop forwarding
  tnr ports forward 0 --add 3000 --remove 8080
  tnr ports list                           # list forwarded ports across instances
  ```
  Ports are exposed through the platform, not as an SSH tunnel. The official port-forwarding page does not describe the mechanism.

## 6. Copying files

```bash
tnr scp ./data.csv 0:/home/user/        # local -> instance
tnr scp 0:/home/user/results.csv ./     # instance -> local
```

- Prefix the remote path with `<instance_id>:`.
- Uses `rsync` on Linux and macOS when available, falling back to `scp`. Windows/WSL uses `scp`.
- Plain `scp`/`rsync` with a hand-written host is **[UNVERIFIED]**. The docs describe SSH only through the console.

## 7. Stop vs delete, and billing

**Stop:** Thunder has no native stop command documented in the CLI pages I fetched. The stopping guide says the workaround is:
1. Create a snapshot of the running instance.
2. Delete the instance.
3. Restore the snapshot into a new instance later (`--template <snapshot-name>` per creating docs).

**Delete:**
```bash
tnr delete        # interactive list
tnr delete 0      # by ID, still asks for confirmation
```
- Permanently removes the instance and all data on it. Back up first (snapshot or `tnr scp`).
- "Billing stops immediately when an instance is deleted."

**Billing (from https://www.thundercompute.com/docs/billing.md and /pricing):**

| State | Billed? |
|---|---|
| Running | GPU at per-GPU-hour rate, billed per minute. Instance disk billed at **$0.219/GB/mo**, but the first 100 GB per GPU is included, and disk is "billed only while running". |
| Stopped (via snapshot, instance deleted) | Only snapshot storage at **$0.05/GB/mo** until you delete the snapshot. |
| Deleted | No compute. Snapshots you keep still bill. |

Also: data egress is $0.00/GB. Billing for a stopped instance with a disk but no snapshot is **not documented**.

GPU rates (on-demand, per GPU-hour): RTX A6000 $0.35, L40 $0.79, A100 80GB $1.09, H100 SXM $3.20.

## 8. Stopping from inside the instance

**Not documented.** No official page describes a command to stop or delete an instance from inside it. Possible approaches (all **[UNVERIFIED]**, not tested):
- Call the REST API with a token from inside the instance. The API reference has a delete-instance endpoint: https://www.thundercompute.com/docs/api-reference/instances/delete-instance.md
- Use `tnr` from inside the instance, if it's installed there, to run `tnr delete <id>`. Not documented.

## 9. Snapshots

```bash
tnr snapshot create
tnr snapshot create --instance-id 0 --name my-environment
tnr snapshot list
tnr snapshot delete
tnr snapshot delete my-environment
```

- Snapshot storage bills at $0.05/GB/mo until deleted.
- Restore by passing the snapshot name as `--template` on `tnr create`.
- Speed guide: https://www.thundercompute.com/docs/guides/speeding-up-snapshots.md

## 10. Modify an instance

```bash
tnr modify 0 --gpu a100
tnr modify 0 --vcpus 16
tnr modify 0 --disk 300     # disk can only be increased
tnr modify 0 --num-gpus 4
```

## Open items to verify before using

1. The exact `--gpu` value for H100 (run `tnr create` interactively first).
2. Whether `--mode` exists (search snippet says yes; official pages do not show it).
3. Stopped-instance disk billing when no snapshot is kept.
4. Token file location.
5. Whether a generic SSH alias works after `tnr connect`.
6. Whether an instance can delete itself via the API.
