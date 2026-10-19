# gitops

Desired state of the cluster, read and applied by Argo CD.

Terraform creates a single Argo CD application, `root`, that follows [apps/](apps/) on the `main` branch of this repository. Whatever that folder holds reaches the cluster with no manual command: plain resources such as a namespace, and the Argo CD `Application` manifests of everything else (the app now; later monitoring and backups). This is the *app of apps* pattern.

| File | What it is |
|---|---|
| [apps/cards-warehouse-namespace.yaml](apps/cards-warehouse-namespace.yaml) | The app's namespace, which enforces the restricted Pod Security Standard |
| [apps/cards-warehouse.yaml](apps/cards-warehouse.yaml) | The app: the [chart](../chart/) from `main`, with `image.tag`, the commit whose image runs |
| [apps/infisical-operator.yaml](apps/infisical-operator.yaml) | The Infisical operator, which copies secrets from Infisical Cloud into the cluster: its official chart, pinned, in the `infisical` namespace that Terraform creates with the operator's credential |
| [promote.sh](promote.sh) | The release: sets `image.tag` to a commit, in one commit by the GitHub bot. Run by the pipeline |
| [tests/promote_test.sh](tests/promote_test.sh) | Its unit tests, in throwaway Git repositories: `make gitops-check` |

- **The version of the app lives here.** `image.tag` in the app's Application is the one place that says which image runs. Changing it in Git is how a release happens, and the pipeline does it (below).
- **Polling.** GitHub cannot reach a cluster on the PC, so Argo CD polls the repository: every 120 seconds plus up to 60 seconds of jitter, the chart defaults. A pushed commit reaches the cluster within about three minutes.
- **Automated sync with self-heal and prune.** A change made by hand in the cluster is undone, a resource deleted by hand is created again, and a manifest removed from Git is deleted from the cluster. Both `root` and the app's Application sync this way.
- **Cascade delete.** The app's Application carries the Argo CD resources finalizer: if it leaves Git, what it installed is deleted with it, instead of being left running without an owner.
- **Retry.** On a new cluster, the app's Application can sync before the operator has installed the kinds its chart uses (`InfisicalAuth`, `InfisicalStaticSecret`), and that sync fails. Argo CD never tries a failed revision again on its own, so the app's Application retries, up to 10 times, waiting from 10 seconds up to 3 minutes.

## Release and rollback

A push on `main` that changes `app/` releases itself, with no manual step:

```
push ─► pipeline: checks, image built, scanned, published ─► release job: bot commit, image.tag = <push>
     ─► Argo CD polls GitHub, sees the commit ─► the new pod is Ready
```

- **The release job** runs [promote.sh](promote.sh) on the latest `main`, then pushes its commit. The commit is by `github-actions[bot]` and changes one line, `image.tag`. It runs only after the `published` job, so an image stopped by the scan never gets here.
- **Only app changes release.** The image holds only `app/`, so a push that changes nothing there (a note, a README, the chart, a revert of a release commit) creates no release commit and restarts no pod. The whole push counts, from the previous head of `main`, not just its last commit.
- **Never backwards.** When two pipelines end in the wrong order, the older commit is not released over the newer one. Releases run one at a time.
- **No loop.** The release commit is pushed with the run's `GITHUB_TOKEN`, and GitHub starts no workflow for what that token pushes. Even if it did, the commit changes nothing in `app/`.
- **Your next push.** After each release `main` on GitHub has one more commit: `git pull --rebase` before pushing again.

To go back to the previous version, revert the release commit and push:

```sh
git pull --rebase
git revert --no-edit <release commit>   # git log --author='github-actions' -1 finds the last one
git push
```

The revert changes nothing in `app/`, so its pipeline runs the checks and releases nothing. Argo CD applies the previous tag at its next poll. There is no build to wait for: the image of the previous commit is already on GHCR. The next push that changes the app releases normally.

`bash infra/platform/tests/release.sh` and `bash infra/platform/tests/release.sh rollback` check both from end to end, with the platform up, and measure them: see [docs/measurements](../docs/measurements/commit-to-production.md).
