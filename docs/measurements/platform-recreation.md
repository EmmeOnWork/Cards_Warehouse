# Recreating the platform

How long one command takes to bring the whole platform back from nothing: the kind cluster, Argo CD, the Infisical operator with the app's secrets, PostgreSQL and the app.

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

## Environment

The PC: Windows 11 Pro, Intel i5-11600K, 32 GB RAM. Docker Desktop 29.5.2 on WSL 2 (kernel 5.15), which gives its machine 12 CPUs and 15.6 GiB of memory. The cluster: kind, one node, Kubernetes 1.34.3.
