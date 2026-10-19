# From commit to production

How long a push on `main` that changes the app takes to run in the cluster, and how long a rollback takes.

## Method

- **Start: the push.** The time GitHub records for the push that moved `main` to the commit, from its [repository activity](https://docs.github.com/en/rest/repos/repos#list-repository-activities) API.
- **End: the new pod is Ready.** The `Ready` condition of the first pod running the image of the commit, from Kubernetes. From then on the Service sends it traffic, and `/version` answers with the commit.
- **Steps in between**, from the same clocks:
  - *Image published*: the end of the `build, scan and publish` job, from GitHub Actions.
  - *Release commit*: the push of the bot's commit that sets `image.tag`, from the repository activity.
  - *Argo CD sync*: `deployedAt` of the app's Application, in the history entry with that `image.tag`.
- **The tool**: [`infra/platform/tests/release.sh`](../../infra/platform/tests/release.sh), run right after the push. It also checks the release from end to end and prints the row below. Times are minutes:seconds after the push.

**Argo CD polling has a floor.** GitHub cannot reach a cluster on the PC, so Argo CD polls the repository every `timeout.reconciliation` plus a random jitter up to `timeout.reconciliation.jitter`. The test reads both from `argocd-cm` in the cluster. With the chart defaults, 120 s + 60 s, a release commit waits from 0 to 3 minutes before Argo CD sees it.

## Releases

| Date | Commit | Push (UTC) | Image published | Release commit | Argo CD sync | Pod Ready | Argo CD polling |
|---|---|---|---|---|---|---|---|

## Rollbacks

Revert of the release commit, pushed: no build, only Argo CD polling and the rollout.

| Date | Revert | Push (UTC) | Argo CD sync | Pod Ready | Argo CD polling |
|---|---|---|---|---|---|

## Environment

The cluster: kind, one node, Kubernetes 1.34.3, on Docker Desktop (WSL 2) on the PC: Windows 11 Pro, Intel i5-11600K, 32 GB RAM. The pipeline: GitHub-hosted `ubuntu-24.04` runners.
