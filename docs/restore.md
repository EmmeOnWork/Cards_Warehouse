# Restoring the data

How to bring the app's data back from a [Velero backup](../gitops/README.md#backups): after the cluster is lost (a new PC, Docker Desktop reset, `make platform-down`), or when the database is broken. What comes back is the database as it was at the backup: items, purchases, stock movements, the list of each item's photos, sales. The photos themselves never left their bucket ([photos](photos.md)).

What is lost is what was typed after that backup: at most a day of work, since the backups run every day at 19:00 UTC.

## What you need

- The platform up. On a lost cluster that is `make platform-up`, which needs Docker Desktop running, the Infisical credential in `~/.cards-warehouse/platform.env` and `aws login` for the Terraform state ([infra/platform](../infra/platform/README.md)).
- Nothing else. The restore uses only the cluster: Velero reads the bucket with its own key, which the Infisical operator brought into the cluster. No AWS session, no other secret.

## Steps

1. **Create the platform**, if the cluster is gone, and wait for the app to answer: `http://localhost:8000/readyz` says `ok`. The app runs, on an empty database.

   ```sh
   make platform-up
   ```

2. **Restore before 19:00 UTC**, or name the backup. A new cluster makes its first backup at the next 19:00 UTC, of its empty database, and from then on that is the newest. To see the backups, with their dates (inside `make shell`):

   ```sh
   velero backup get
   ```

   On a new cluster the list fills about half a minute after Velero is ready, when it reads the bucket.

3. **Restore**: the newest backup that completed, or the one you name.

   ```sh
   make restore
   make restore BACKUP=velero-daily-20261026190038
   ```

   It prints each step with the time since it started, and ends with `done: <backup> restored`. About a minute.

4. **Check** on the phone or the PC: the items are there, and their photos open.

When something fails, the command stops with a `FAIL` line that says what to look at. It can be run again: it starts over from step 1 of what it does.

## What make restore does

Velero gives a volume back only to a pod it creates itself. On a new cluster Argo CD has already created PostgreSQL, with an empty database, so Velero would skip it and restore nothing. The copy of the database therefore takes a detour:

```
make restore ─► infra/platform/restore.sh
 ├─ waits for Velero to read the whole list of backups in the bucket, and takes the newest that completed
 ├─ namespace cards-warehouse-restore, which Argo CD does not know:
 │    an empty disk, a throwaway password, then velero restore of the PostgreSQL pod alone
 │    └─ Velero's restore-wait init container holds the pod while the node agent writes back /dump
 ├─ cat of the copy there ─► psql in the real PostgreSQL, in one transaction:
 │    the schema emptied, then the copy
 ├─ the app's pod started again: its init container migrates the database to the app's revision
 └─ the namespace cards-warehouse-restore deleted
```

- **The whole list first.** On a new cluster Velero copies the backups of the bucket into the cluster one by one, in no order, over a few seconds, and writes the time of the sync on its backup location (`lastSyncedTime`) only at the end. The command waits for that time: the drill of 2026-10-27 took "the newest" while only one backup was listed, and loaded a backup two days old with no error.
- **One transaction, committed last.** The `COMMIT` is sent only once the whole copy went through. A copy cut halfway ends the session with the transaction open, PostgreSQL undoes it, and the database stays as it was. Seen in the drill: `psql --single-transaction` would have committed whatever had arrived, and left an empty database.
- **A copy older than the app loads too.** The schema is emptied first, then the copy creates the tables of its own revision, and the migrations bring them forward when the app starts again.
- **Its own time limit.** The command waits at most 5 minutes for each step, instead of `velero restore create --wait`. A pod that never starts keeps a Velero restore waiting for hours, and meanwhile Velero restores nothing else. If it happens anyway: `kubectl -n velero delete pod -l name=velero` restarts Velero, which marks that restore as failed.

## After the restore

- **Photos added after the backup** are in the bucket, but no item lists them any more. Upload them again from the bucket, as for [a photo deleted from the app](photos.md#recovering-a-photo-deleted-from-the-app).
- **Photos deleted after the backup** show broken on their item's page: the database has them again, the bucket has a delete marker over them. See [a photo broken on the item's page](photos.md#a-photo-broken-on-the-items-page).
- **The password** is the one the app had at the backup: a change made from the app after it is lost. A reset from the PC, `make password-hash` into Infisical, still wins over it, as always.

## The drill

`bash infra/platform/tests/restore.sh [cycles]`, inside `make shell` after `aws login --remote`, with the platform up, checks all of this from end to end and measures it. Each cycle adds a photo to the item *Controllo del ripristino* through the app, backs up, destroys the platform, creates it again, runs the restore with an empty environment, and checks that the photo of that cycle opens and that every table holds the same rows as before the backup. The measurements are in [docs/measurements/restore.md](measurements/restore.md).
