# Recreating the platform

How long one command takes to bring the platform back from nothing until the app answers healthy: the kind cluster, Argo CD, the Infisical operator with the app's secrets, PostgreSQL and the app. Argo CD installs Velero in the same run, but the end does not wait for it: the app does not need it to serve.

## Method

- **Start: the Terraform command, with no cluster.** The launch of `terraform init` and `terraform apply` in `infra/platform`, the commands `make platform-up` runs inside the toolbox. Before it, no node of the cluster exists. Starting the toolbox container, a few seconds, is left out.
- **End: the app answers healthy on the PC.** The first `200` from `GET http://localhost:8000/readyz`, asked every second. `/readyz` answers `200` only once the app reaches PostgreSQL, and the Service sends traffic only to a Ready pod. So the app runs, the database runs, and the secrets came from Infisical: without them neither of the two starts.
- **Step in between: the end of `terraform apply`.** By then the cluster, Argo CD and its root application exist. The rest is Argo CD's work, from Git: the operator, the secrets, the database, the migrations, the app.
- **No step by hand.** Nothing is typed between the start and the end. What has to be ready beforehand is not part of the platform: Docker Desktop running, the Infisical credential in `~/.cards-warehouse/platform.env`, an AWS session for the Terraform state (`aws login`).
- **Every image is downloaded each time.** Docker Desktop keeps the node image, but a new node starts with no image inside: Argo CD, the operator, PostgreSQL and the app come again from their registries, over the home connection.
- **The tool**: [`infra/platform/tests/recreation.sh`](../../infra/platform/tests/recreation.sh), inside `make shell`. Each cycle checks that no cluster exists, measures, destroys the platform, and prints the row below. Times are minutes:seconds after the start. Production is the commit the app reports at `/version`.

## Measurements

| Date | Start (UTC) | Production | Terraform apply | App healthy |
|---|---|---|---|---|
| 2026-10-23 | 14:21:32 | `d76858d`, before the fix below and before Velero | 1:29 | 7:25 |
| 2026-10-23 | 16:39:05 | `dba3415` | 1:27 | **2:37** |
| 2026-10-23 | 16:42:03 | `dba3415` | 1:22 | **2:55** |
| 2026-10-23 | 16:45:19 | `dba3415` | 1:20 | **2:55** |
| 2026-10-23 | 16:48:34 | `dba3415` | 1:19 | **2:21** |
| 2026-10-23 | 16:51:16 | `dba3415` | 1:22 | **2:57** |

**The value: 2:55, the median of the five runs on `dba3415`, from 2:21 to 2:57.** Sorted, the five times are 2:21, 2:37, 2:55, 2:55, 2:57: the median is the third. Terraform's part is steady, 1:19 to 1:27; the rest, Argo CD's, varies more, from 1:02 to 1:35.

**The first row is left out.** Between it and the others, `dba3415` changed how the operator gets the address of Infisical: a plain manifest in Git instead of a Helm hook of its chart ([gitops](../../gitops/README.md)). With the hook, on two other new clusters the operator never made the connection ready, and no secret arrived without a restart by hand. That run had no such failure but took 7:25; its timeline was not recorded, so where the extra time went is not measured.

## Environment

The PC: Windows 11 Pro, Intel i5-11600K, 32 GB RAM. Docker Desktop 29.5.2 on WSL 2 (kernel 5.15), which gives its machine 12 CPUs and 15.6 GiB of memory. The cluster: kind, one node, Kubernetes 1.34.3.
