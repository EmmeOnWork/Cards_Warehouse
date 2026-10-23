# gitops

Desired state of the cluster, read and applied by Argo CD.

Terraform creates a single Argo CD application, `root`, that follows [apps/](apps/) on the `production` branch of this repository. Whatever that folder holds reaches the cluster with no manual command: plain resources such as a namespace, and the Argo CD `Application` manifests of everything else (the app with its database, the Infisical operator, the backups). This is the *app of apps* pattern.

| File | What it is |
|---|---|
| [apps/cards-warehouse-namespace.yaml](apps/cards-warehouse-namespace.yaml) | The app's namespace, which enforces the restricted Pod Security Standard |
| [apps/cards-warehouse.yaml](apps/cards-warehouse.yaml) | The app and its PostgreSQL: the [chart](../chart/) at the commit `production` points at, with the image of that commit |
| [apps/infisical-operator.yaml](apps/infisical-operator.yaml) | The Infisical operator, which copies secrets from Infisical Cloud into the cluster: its official chart, pinned, in the `infisical` namespace that Terraform creates with the operator's credential, and the folder [infisical/](infisical/), which tells it where Infisical is |
| [apps/velero-namespace.yaml](apps/velero-namespace.yaml) | Velero's namespace, *privileged*: its node agent reads the volumes from the node's disk, as root |
| [apps/velero.yaml](apps/velero.yaml) | [Backups](#backups) with Velero: its official chart, pinned, and the folder [velero/](velero/), which brings it the AWS credential from Infisical |

- **`production` is the version in the cluster.** You work on `main`; the pipeline moves `production` to a commit only once its checks pass and its image is scanned and published. Argo CD reads everything from `production`, so a red `main` never reaches the cluster.
- **The image tag is the commit Argo CD reads.** The app's Application sets `image.tag` to `$ARGOCD_APP_REVISION`, which Argo CD replaces with the commit it renders. Chart and image always come from the same commit, and no file holds a version to update.
- **Polling.** GitHub cannot reach a cluster on the PC, so Argo CD polls the repository: every 120 seconds plus up to 60 seconds of jitter, the chart defaults. A moved `production` reaches the cluster within about three minutes.
- **Automated sync with self-heal and prune.** A change made by hand in the cluster is undone, a resource deleted by hand is created again, and a manifest removed from Git is deleted from the cluster. Both `root` and the app's Application sync this way.
- **Cascade delete.** The app's Application carries the Argo CD resources finalizer: if it leaves Git, what it installed is deleted with it, instead of being left running without an owner.
- **Retry.** On a new cluster, the app's and Velero's Applications can sync before the operator has installed the kinds they use (`InfisicalAuth`, `InfisicalStaticSecret`), and that sync fails. Argo CD never tries a failed revision again on its own, so these two and the operator's Application retry, up to 10 times, waiting from 10 seconds up to 3 minutes.
- **The connection to Infisical is a plain manifest.** The operator's chart offers to create it, but as a Helm hook: Argo CD creates a hook only once the operator runs, then modifies it, and on two new clusters the operator never made that connection ready, so no secret arrived. [infisical/connection.yaml](infisical/connection.yaml) declares it instead, applied with the operator's CRDs.

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

**A migration is never reverted.** Every release migrates the database before the new version starts ([chart](../chart/README.md#migrations-at-every-release)). Code older than the database finds there a revision it does not know: its migrations fail, and the release stops with the newer version still serving. This holds for a `git revert` of a commit that adds a migration, and for `production` moved back by hand past one. Undo such a commit forward: a new commit that undoes the code, and a new migration that undoes the change to the database.

`bash infra/platform/tests/release.sh` checks a release from end to end, with the platform up, and measures it: see [docs/measurements](../docs/measurements/commit-to-production.md).

## Backups

[Velero](https://velero.io) saves the app's data into the bucket `emmeonwork-cards-warehouse-backups`, once a day:

```
19:00 UTC, schedule velero-daily ─► Backup velero-daily-<time>
  ├─ hook in the PostgreSQL pod: pg_dump ─► /dump/cards_warehouse.dump, a consistent copy
  ├─ node agent: copies the dump volume into the bucket, with Kopia
  └─ server: the resources of the cards-warehouse namespace, Secrets excluded, into the bucket
```

- **A copy of the database, not its volume.** At the start of every backup, a hook runs `pg_dump` in the PostgreSQL pod, into the `dump` volume, an `emptyDir` that Velero then copies ([chart](../chart/templates/postgres.yaml)). The data volume itself is left out: kind makes it a `hostPath`, which Velero's file system backup skips, and a copy of the files of a running server would not be consistent anyway. Restoring therefore means loading the copy into an empty PostgreSQL.
- **No photos and no Secrets.** The photos are already on S3, protected by the versions of their bucket. The Secrets come from Infisical: a copy in the bucket would be one more place to guard.
- **Every day at 19:00 UTC**: 21:00 in Italy on summer time, 20:00 in winter. When the PC is off at that hour, Velero runs one backup as soon as the cluster is back, without waiting for the next evening. A new cluster makes its first backup at the next 19:00.
- **30 days**, then Velero deletes the backup, from the cluster and from the bucket. The bucket keeps no versions of its own, so nothing else piles up.
- **The credential** is the key of `cards-warehouse-app`, the scoped user of the [foundations](../infra/foundations/README.md#the-app-credential), in Infisical's `/aws` folder. The Infisical operator writes its two values into the AWS credentials file Velero reads, the Secret `velero-credentials` ([velero/credentials.yaml](velero/credentials.yaml)).
- **Kopia's repository** in the bucket is encrypted with Velero's default password, the same on every new cluster, which can therefore read the old backups. What keeps the backups private is the bucket, not that password.
- **The outcome is on the app's home page**: when the last backup ended and whether it succeeded. The line turns red when it failed, when no backup succeeded in the last 24 hours, or when the state cannot be read. The app lists Velero's `Backup` objects through the Kubernetes API, with a token allowed to do that and nothing else ([chart](../chart/templates/backup-reader.yaml)).

A backup by hand, with the platform up:

```sh
make backup     # the same as the daily backup, named velero-daily-<time>; waits for the outcome
```

Inside `make shell`, the Velero CLI shows the rest:

```sh
velero backup get                         # every backup, with its status and expiry
velero backup describe <name> --details   # what it holds, resource by resource
velero backup logs <name>                 # what went wrong, when it failed
```

`bash infra/platform/tests/backup.sh` checks the backups from end to end, inside `make shell` after `aws login --remote`, with the platform up. It backs up by hand and checks that the backup completes, its files are in the bucket, it expires after 30 days, it holds a copy of the database made by the hook during that backup, and no Secret; that the app shows its time and outcome; and that the schedule ran a backup in the last 24 hours. On a platform younger than its first 19:00, that last check fails: run the test again the next day.
