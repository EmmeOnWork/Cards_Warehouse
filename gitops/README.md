# gitops

Desired state of the cluster, read and applied by Argo CD.

Terraform creates a single Argo CD application, `root`, that follows [apps/](apps/) on the `production` branch of this repository. Whatever that folder holds reaches the cluster with no manual command: plain resources such as a namespace, and the Argo CD `Application` manifests of everything else (the app now; later monitoring and backups). This is the *app of apps* pattern.

| File | What it is |
|---|---|
| [apps/cards-warehouse-namespace.yaml](apps/cards-warehouse-namespace.yaml) | The app's namespace, which enforces the restricted Pod Security Standard |
| [apps/cards-warehouse.yaml](apps/cards-warehouse.yaml) | The app: the [chart](../chart/) at the commit `production` points at, with the image of that commit |
| [apps/infisical-operator.yaml](apps/infisical-operator.yaml) | The Infisical operator, which copies secrets from Infisical Cloud into the cluster: its official chart, pinned, in the `infisical` namespace that Terraform creates with the operator's credential |

- **`production` is the version in the cluster.** You work on `main`; the pipeline moves `production` to a commit only once its checks pass and its image is scanned and published. Argo CD reads everything from `production`, so a red `main` never reaches the cluster.
- **The image tag is the commit Argo CD reads.** The app's Application sets `image.tag` to `$ARGOCD_APP_REVISION`, which Argo CD replaces with the commit it renders. Chart and image always come from the same commit, and no file holds a version to update.
- **Polling.** GitHub cannot reach a cluster on the PC, so Argo CD polls the repository: every 120 seconds plus up to 60 seconds of jitter, the chart defaults. A moved `production` reaches the cluster within about three minutes.
- **Automated sync with self-heal and prune.** A change made by hand in the cluster is undone, a resource deleted by hand is created again, and a manifest removed from Git is deleted from the cluster. Both `root` and the app's Application sync this way.
- **Cascade delete.** The app's Application carries the Argo CD resources finalizer: if it leaves Git, what it installed is deleted with it, instead of being left running without an owner.
- **Retry.** On a new cluster, the app's Application can sync before the operator has installed the kinds its chart uses (`InfisicalAuth`, `InfisicalStaticSecret`), and that sync fails. Argo CD never tries a failed revision again on its own, so the app's Application retries, up to 10 times, waiting from 10 seconds up to 3 minutes.

## Release and rollback

Every push on `main` releases itself, with no manual step and no commit added to `main`:

```
push ─► pipeline: checks, image built, scanned, published ─► production moved to <push>
     ─► Argo CD polls GitHub, sees production moved ─► the new pod is Ready
```

- **The release job** runs `git push origin <commit>:production`: it moves a branch, it adds no commit. `main` holds only your commits, so your next push never needs a `git pull` first.
- **Never backwards.** Without `--force`, Git refuses to move a branch onto an older commit. When two pipelines overlap, the newer push cancels the older run anyway.
- **No loop.** The pipeline runs on pushes to `main` only, and the run's `GITHUB_TOKEN` never starts a workflow.

To go back to the previous version, revert the bad commit and push, like any other change:

```sh
git revert --no-edit <bad commit>
git push
```

The revert is released like any commit: a build, then Argo CD. When it cannot wait for a build, move `production` back by hand to a commit that ran before, whose image is already on GHCR: `git push --force origin <good commit>:production`. The next push on `main` moves it forward again.

`bash infra/platform/tests/release.sh` checks a release from end to end, with the platform up, and measures it: see [docs/measurements](../docs/measurements/commit-to-production.md).
