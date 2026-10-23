# chart

Helm chart that packages the application for Kubernetes: a Deployment, a NodePort Service, PostgreSQL, and the two resources of the Infisical operator that bring the app its secrets:

- `InfisicalAuth`: signs in to Infisical as the cluster's machine identity, with the credential Terraform puts in the `infisical` namespace;
- `InfisicalStaticSecret`: copies the app's folder in Infisical into the Secret `cards-warehouse-secrets`, which it owns, and reads it again every minute.

The Deployment gives the app each secret listed in `secrets` as an environment variable from that Secret. When a value changes, the operator restarts the Deployment (annotation `secrets.infisical.com/auto-reload`), since the app reads its secrets only at start.

The app's pods run as the ServiceAccount `cards-warehouse`. A Role in Velero's namespace lets it list Velero's `Backup` objects and nothing else, so the home page can show the outcome of the last backup ([backup-reader.yaml](templates/backup-reader.yaml)).

Argo CD renders it from this folder at the commit the `production` branch points at, through the `cards-warehouse` Application in [gitops/apps](../gitops/apps/cards-warehouse.yaml). That Application gives the one value the chart has no default for: `image.tag`, set to that same commit. Without it, rendering fails instead of running an unknown version.

## The database

PostgreSQL runs in the cluster, without an operator: a StatefulSet with one replica, `cards-warehouse-postgres`, and a headless Service of the same name, the address the app connects to.

- **The data live on a volume.** The StatefulSet asks for a 1Gi volume, which kind's default storage class creates on the node. A pod that is deleted or restarted gets the same volume back, and the volume outlives even the StatefulSet. It does not outlive the cluster: `make platform-down` deletes it. What outlives the cluster is the daily copy of the database in S3, described below.
- **The password comes from Infisical**, as `PGPASSWORD` in the app's folder. PostgreSQL reads it as `POSTGRES_PASSWORD` only at its first start, on an empty volume, to create the user `cards_warehouse`; the app reads it as `PGPASSWORD`, with `PGHOST`, `PGUSER` and `PGDATABASE` from the chart: the standard variables of libpq, so no address is in the code.
- **Changing the password** in Infisical alone breaks the connection: the database keeps the old one. First change it in the database, inside `make shell`: psql asks for the new value twice and sends it already encrypted, so it lands in no command line, file or shell history. Then write the same value in Infisical:

  ```sh
  kubectl -n cards-warehouse exec -it cards-warehouse-postgres-0 -- psql -U cards_warehouse -d cards_warehouse -c '\password'
  ```

  Within a minute the operator copies the new value from Infisical and restarts the app.
- **A copy for the backups.** The pod's annotations tell Velero what to do at every backup: first run `pg_dump` in the container, which writes a consistent copy of the database into the `dump` volume, then copy that volume into the backups bucket. A copy that fails fails the backup. The data volume is not copied: see [backups](../gitops/README.md#backups).
- **Its pod meets the restricted standard too.** It runs as the image's `postgres` user, 999, with a read-only root filesystem: only the volume, the socket directory, the `dump` volume and `/tmp` are writable. The tests in `app/` run PostgreSQL the same way.

## Migrations at every release

The changes to the structure of the database live in [app/src/cards_warehouse/migrations](../app/src/cards_warehouse/migrations/), as [Alembic](https://alembic.sqlalchemy.org) migrations. Every pod of the app runs them before the app starts, in an init container from the same image, `python -m cards_warehouse.migrate`:

```
new version ─► new pod: init container migrate ─► app starts ─► Ready ─► traffic; the old pod is removed
                              └─ fails ─► the new pod never gets Ready ─► the old pod keeps serving
```

- **Nothing by hand.** A release that brings a new migration applies it on its own, before the new version serves a request.
- **A failure stops the release.** The Deployment replaces the old pod only once the new one is Ready (`maxUnavailable: 0`). When a migration fails, the init container fails, Kubernetes starts it again with growing pauses, and the version already running keeps serving. Argo CD shows the app as *Progressing*, then *Degraded* after 10 minutes. The fix is a new commit.
- **Nothing half done.** All the migrations of a run share one transaction, and PostgreSQL changes its structure inside transactions too: a failed run leaves the database as it was.
- **Harmless when there is nothing to do.** Every restart of the pod runs the migrations again: at the last revision, they change nothing.
- **On a new cluster** the init container can start before PostgreSQL is ready. It fails, and Kubernetes starts it again until the database answers.

## Values

| Value | Default | What it sets |
|---|---|---|
| `image.repository` | `ghcr.io/emmeonwork/cards-warehouse` | Public image on GHCR: the node pulls it with no credentials |
| `image.tag` | none, required | The commit to run |
| `secrets` | `[SESSION_SECRET, PASSWORD_HASH, PGPASSWORD]` | The secrets the app needs, by name only: the list in Git. A name missing from Infisical keeps the pod from starting |
| `infisical.projectSlug`, `.environment`, `.secretPath` | the project, `prod`, `/app` | Where the values live in Infisical |
| `infisical.refreshInterval` | `60s` | How often the operator reads Infisical again |
| `infisical.credentials` | `infisical-credentials` in `infisical` | The Secret Terraform creates with the cluster's credential |
| `infisical.connection` | `default` in `infisical` | The connection declared in [gitops/infisical](../gitops/infisical/connection.yaml), which holds the address of Infisical |
| `replicas` | `1` | Always written into the Deployment, so Argo CD sees a change made by hand |
| `service.nodePort` | `30000` | The node port the kind cluster maps to `127.0.0.1:8000` on the PC |
| `livenessProbe`, `readinessProbe` | `/livez`, `/readyz` on the `http` port | The app's health endpoints. `/readyz` asks the database: while it does not answer, the pod gets no traffic, but it is not restarted |
| `resources` | 50m CPU and 64Mi requested, 128Mi memory limit | Measured: about 55 MiB after 600 requests to `/readyz`, each one asking the database. The init container of the migrations gets the same, and runs within it |
| `database.name`, `.user` | `cards_warehouse` | The database and the user the app connects as |
| `postgres.image` | `postgres:18.6-trixie` | The official image, the version the tests in `app/` run against |
| `postgres.storage` | `1Gi` | The size of the data volume |
| `postgres.resources` | 50m CPU and 128Mi requested, 512Mi memory limit | Measured: 34 MiB idle, 234 MiB after a pgbench run on a million rows |

Every pod meets the restricted [Pod Security Standard](https://kubernetes.io/docs/concepts/security/pod-security-standards/), which the `cards-warehouse` namespace enforces: not root, no privilege escalation, no capabilities, read-only root filesystem. PostgreSQL mounts no Kubernetes API token, since it never calls the API; the app's token can only list Velero's backups. These are fixed in the templates, not values.

## Checks

```sh
make chart-check
```

It runs, in the toolbox:

1. `helm lint --strict`: the chart is well formed.
2. `helm template | kubeconform -strict`: what the chart renders is valid against the schemas of Kubernetes 1.34.3, the version of the cluster, with no unknown field. The Infisical kinds are checked against the schemas of the community [CRD catalog](https://github.com/datreeio/CRDs-catalog), pinned by commit.
3. `kubeconform -strict gitops`: the same check on the manifests Argo CD applies from [gitops/](../gitops/), its `Application` kind included. The values an `Application` passes to a chart are not checked, since no schema describes them.

Helm is 4.2.1, the version Argo CD 3.5.4 renders charts with, so the checks see the same manifests as the cluster.
