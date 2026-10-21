# From commit to production

How long a push on `main` takes to run in the cluster. A rollback is the release of a `git revert`, so it is measured the same way.

## Method

- **Start: the push.** The time GitHub records for the push that moved `main` to the commit, from its [repository activity](https://docs.github.com/en/rest/repos/repos#list-repository-activities) API.
- **End: the new pod is Ready.** The `Ready` condition of the first pod running the image of the commit, from Kubernetes. From then on the Service sends it traffic, and `/version` answers with the commit.
- **Steps in between**, from the same clocks:
  - *Image published*: the end of the `build, scan and publish` job, from GitHub Actions.
  - *Production moved*: the end of the `release to the cluster` job, which points the `production` branch at the commit.
  - *Argo CD sync*: `deployedAt` of the app's Application, in the history entry for the commit.
- **The tool**: [`infra/platform/tests/release.sh`](../../infra/platform/tests/release.sh), run right after the push. It also checks the release from end to end and prints the row below. Times are minutes:seconds after the push.

**Argo CD polling has a floor.** GitHub cannot reach a cluster on the PC, so Argo CD polls the repository every `timeout.reconciliation` plus a random jitter up to `timeout.reconciliation.jitter`. The test reads both from `argocd-cm` in the cluster. With the chart defaults, 120 s + 60 s, a moved `production` waits from 0 to 3 minutes before Argo CD sees it.

## Releases

Rollbacks are marked as such in the Commit column.

| Date | Commit | Push (UTC) | Image published | Production moved | Argo CD sync | Pod Ready | Argo CD polling |
|---|---|---|---|---|---|---|---|

## Environment

The cluster: kind, one node, Kubernetes 1.34.3, on Docker Desktop (WSL 2) on the PC: Windows 11 Pro, Intel i5-11600K, 32 GB RAM. The pipeline: GitHub-hosted `ubuntu-24.04` runners.
