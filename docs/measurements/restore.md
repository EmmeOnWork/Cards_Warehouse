# Restoring data and photos

How long it takes to bring the app's data back from a Velero backup onto a platform just created from nothing: from the start of `make restore` until the app shows the data saved before the platform was destroyed, its photos included. The procedure is [docs/restore.md](../restore.md).

## Method

- **Before each cycle, not measured.** Through the app, a new photo goes on the item *Controllo del ripristino*: an image that shows the time it was made, unique to the cycle. Then every table of the database is fingerprinted, a backup is made by hand (the same as the daily one), the platform is destroyed, and it is created again with the one command, until the app answers healthy on an empty database. That last part is the [recreation](platform-recreation.md), measured on its own.
- **Start: `make restore` on the new cluster.** The launch of `infra/platform/restore.sh`, the script `make restore` runs inside the toolbox. It runs with an empty environment: no AWS session, no Infisical credential. Starting the toolbox container, a few seconds, is left out.
- **End: the photo of the cycle opens from the app.** The item's page, asked every second with a session of the app, lists the photo, and its signed link answers with the same bytes that were uploaded. The photo comes from S3, which the destruction never touched. Its row in the database comes from the backup.
- **Step in between: the end of `make restore`.** The script prints its own steps, kept below.
- **Checked in every cycle:** the restore took the newest backup, the one just made; every table holds the same rows as before the backup (row count and md5 of the rows, table by table, sales included once they exist); no namespace is left behind.
- **The tool**: [`infra/platform/tests/restore.sh`](../../infra/platform/tests/restore.sh), inside `make shell` after `aws login --remote`, with the platform up. Each cycle starts from the platform the previous one restored. Times are minutes:seconds after the start. Production is the commit the app reports at `/version`.

## Measurements

| Date | Start (UTC) | Production | Backup | `make restore` done | Photo opens |
|---|---|---|---|---|---|
| 2026-10-27 | 03:24:37 | `85aaad8`, before the fix below | `velero-daily-drill-20261027032144` | 1:29 | 1:31 |
| 2026-10-27 | 03:50:20 | `85aaad8` | `velero-daily-drill-20261027034703` | 1:03 | **1:04** |
| 2026-10-27 | 03:54:26 | `85aaad8` | `velero-daily-drill-20261027035140` | 0:47 | **0:48** |
| 2026-10-27 | 03:58:43 | `85aaad8` | `velero-daily-drill-20261027035530` | 0:38 | **0:39** |

**The value: 0:48, the median of the three runs after the fix, from 0:39 to 1:04.** The production commit of the second row was not printed: the test asked `/version` while the old pod of the app was leaving, and now retries. `production` did not move during the drill.

**The first row is left out.** It ran before the fix of 2026-10-27: on a new cluster, `make restore` took the newest backup while Velero was still copying the list of backups from the bucket into the cluster. That cycle took the right backup by chance. The next cycle took one of two days before, with no error, and its photo never opened. Now the command waits for Velero to finish reading the list ([docs/restore.md](../restore.md#what-make-restore-does)).

## Where the time goes

The steps `make restore` printed, in minutes:seconds after its start:

| Run | Velero has read the bucket | Copy of the database back | Loaded into PostgreSQL | App started again |
|---|---|---|---|---|
| 03:50:20 | 0:35 | 0:59 | 0:59 | 1:03 |
| 03:54:26 | 0:29 | 0:42 | 0:43 | 0:46 |
| 03:58:43 | 0:21 | 0:34 | 0:34 | 0:38 |

- **Waiting for Velero is most of it.** On a new cluster Velero reads the bucket about half a minute after its pod is ready (03:29:27, then 03:29:56 in the run before the fix), and it gets ready after the app: from 21 to 35 seconds after the app is healthy.
- **The copy of the database comes back in 13 to 24 seconds.** Velero creates the PostgreSQL pod of the backup in a namespace of its own, its node agent writes the dump volume back from the bucket with Kopia, then PostgreSQL starts in that pod.
- **Loading takes under a second**, then the app's new pod runs its migrations and becomes ready in about 4 seconds.
- **The database is small.** Its copy weighed about 30 KB: the control item, its photos, the channels and the games. With a real inventory the copy grows, and so do the copy back from the bucket and the load. The photos do not count: they stay in their bucket, however many they are.

## From nothing to the restored data

Adding the recreation of the same cycles, measured by the drill in the same way as [the recreation](platform-recreation.md) (from the launch of `terraform init` and `apply` to the app healthy), the platform lost goes back to the saved data in 3:48, 3:02 and 3:21: **a median of 3:21**.

Proposal for the CV: "restores data and photos from Velero backups onto a cluster just recreated in under a minute and a half (median 0:48, three measured drills); from no cluster to the restored data in about three and a half minutes".

## Environment

The PC and Docker Desktop of [the recreation](platform-recreation.md#environment): Windows 11 Pro, Intel i5-11600K, 32 GB RAM, Docker Desktop 29.5.2 on WSL 2 with 12 CPUs and 15.6 GiB of memory. The cluster: kind, one node, Kubernetes 1.34.3. Velero 1.18.4 with the AWS plugin 1.14.4, bucket in `eu-north-1`, over the home connection.
