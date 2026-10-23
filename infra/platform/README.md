# Platform

What one command recreates on the PC:

- `cards-warehouse`: a single-node [kind](https://kind.sigs.k8s.io/) cluster on Docker Desktop, Kubernetes 1.34.3;
- Argo CD 3.5.4, installed with the official `argo-cd` Helm chart;
- `infisical`: the namespace of the Infisical operator, holding `infisical-credentials`, the credential the cluster signs in to Infisical with. It is the one secret kept by hand: see [Secrets](#secrets);
- `root`: the Argo CD application that applies [gitops/apps](../../gitops/apps/) from the `production` branch. Everything else reaches the cluster through Git, not through Terraform: first of all the app, installed from its [chart](../../chart/) and answering at <http://localhost:8000>.

The state lives in the foundations' state bucket under its own key, `platform/terraform.tfstate`, with the same native S3 lock. Destroying the platform never touches the foundations.

## Commands

From the repository root, after `aws login --remote` inside `make shell` (the S3 state needs it):

```sh
make platform-up     # terraform init + apply: cluster, Argo CD, root application
make platform-down   # terraform destroy: the cluster disappears, the buckets stay
```

The Argo CD UI answers at <http://localhost:8090>, as user `admin`. Inside `make shell`, the initial password is in the cluster, never in a file:

```sh
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

## Secrets

The secrets live in [Infisical Cloud](https://infisical.com), US region: the organization that holds the project lives there, and Infisical offers no way to create a second one in the EU account (checked on 2026-10-21). The secrets are encrypted by Infisical and none of them is personal data. Git holds only their names, in the app's [chart](../../chart/values.yaml). The path of a secret:

```
Infisical (project cards-warehouse, environment prod, folder /app)
  └─► Infisical operator, installed by Argo CD (gitops/apps/infisical-operator.yaml), reads it every minute
        └─► Secret cards-warehouse-secrets ─► environment variable of the app, read at start
```

- **The cluster signs in as a machine identity**, `kind-cluster`, with Universal Auth: a client id and a client secret, read-only on the project. Infisical Cloud cannot reach a cluster on the PC, so the identity cannot prove itself with a Kubernetes token: it needs a credential of its own.
- **That credential is the one secret kept by hand.** It lives on the PC in `~/.cards-warehouse/platform.env`, out of the repository. The toolbox loads that file as `TF_VAR_` variables, and Terraform puts the credential into the `infisical-credentials` Secret.
- **Terraform keeps no copy of it.** The variables are *ephemeral* and the Secret receives them through `data_wo`, a *write-only* attribute: Terraform sends the values to the cluster and writes them neither into the plan nor into the state. The state bucket is versioned, so a copy written there once would stay in its history.
- **A changed value restarts the app.** The operator reads Infisical again every 60 seconds and updates the Secret. The app's Deployment carries `secrets.infisical.com/auto-reload`, so the operator then restarts it, and the new pod reads the new value.

### Once: set up Infisical

1. Sign up at <https://app.infisical.com>. The region is chosen with the account and cannot be changed later: the US and EU regions are separate installations, each with its own accounts.
2. Create the project `cards-warehouse` and write its slug, from the project settings, into `infisical.projectSlug` in [chart/values.yaml](../../chart/values.yaml). The slug is a name, not a secret.
3. In the `prod` environment, create the folders `/app` and `/aws`. In `/app`, create `SESSION_SECRET` and `PGPASSWORD`, each with a random value, for example the output of `head -c 32 /dev/urandom | base64`, run in `make shell`. PostgreSQL takes `PGPASSWORD` at its first start: changing it later needs a step in the database too, see [the chart](../../chart/README.md#the-database). Create also `PASSWORD_HASH`, the hash of the password you log in to the app with: run `make password-hash`, type the password twice (it is not shown), and paste the line it prints, starting with `$argon2id$`. Infisical keeps only the hash; the app refuses to start if the value is not one. To change the password, give `PASSWORD_HASH` a new hash: the operator restarts the app with it.
4. In the organization's machine identities, create `kind-cluster` with Universal Auth, add it to the project with the *Viewer* role (read-only), and create a client secret.
5. Copy the client id and the client secret straight into `~/.cards-warehouse/platform.env` on the PC (`C:\Users\<you>\.cards-warehouse\platform.env`):

   ```sh
   TF_VAR_infisical_client_id=<client id>
   TF_VAR_infisical_client_secret=<client secret>
   ```

The `/aws` folder holds the key of the scoped AWS credential: see [the foundations](../foundations/README.md#the-app-credential).

### Replacing the cluster's credential

Create a new client secret for `kind-cluster` in Infisical and write it into `platform.env`. A new cluster gets it at creation. To update a running cluster, raise `data_wo_revision` in [infisical.tf](infisical.tf) and run `make platform-up`: the values are not in the state, so Terraform cannot see that they changed. Then revoke the old client secret in Infisical.

## How it fits together

- **The toolbox talks to the cluster.** kind creates the nodes as containers on the PC's Docker, through the docker CLI and the mounted socket. The toolbox runs on the network of the Docker host, where kind publishes the cluster API on `127.0.0.1`, so the kubeconfig written by kind works unchanged. That kubeconfig lives in a Docker volume mounted at `~/.kube`, out of the repository: left without a path, the kind provider would export it into the working directory.
- **One apply, three steps.** Terraform creates the cluster, then configures the Helm provider from the cluster's attributes and installs Argo CD and the root application. The root application is a release of the `argocd-apps` chart, not a `kubernetes_manifest`, which would need the cluster to exist already when the plan is made.
- **Only the PC's loopback.** The cluster publishes two node ports, Argo CD's on `127.0.0.1:8090` and the app's (30000, set by its chart) on `127.0.0.1:8000`, and its API on `127.0.0.1`: nothing is reachable from the home network. For the same reason, Argo CD serves the UI in plain HTTP. Port mappings are fixed when kind creates the node: changing them recreates the cluster.
- **Polling.** GitHub cannot reach the cluster, so Argo CD polls the repository, as described in [gitops/](../../gitops/).
- **What the state holds.** The kind provider stores the cluster's kubeconfig in the state, client key included. That key only opens a cluster bound to the PC's loopback and dies with it. The state bucket is private.

## Checks

```sh
make tf-check                            # format, validity and unit tests: no cluster, no AWS
bash infra/platform/tests/acceptance.sh  # inside make shell: a whole cycle, about 6 minutes
```

The unit tests in [tests/platform.tftest.hcl](tests/platform.tftest.hcl) check the plan against mock providers: every port published only on the loopback, the path from port 8090 to the Argo CD server and from port 8000 to the app's node port, the root application following `production` with self-heal and prune. Two of them check that separate places agree: the Infisical credential is in the Secret the app's chart reads, and Argo CD installs the operator in the namespace Terraform creates, whose default connection the chart uses.

The acceptance test needs the Infisical credential in `platform.env` and the set-up above. It starts from no cluster and runs the real thing: while `terraform apply` runs, a second run is refused by the S3 lock; then the Infisical credential is in the cluster but, searched by its value, neither in the state, nor in the Git history, nor in any file of the repository; the node is Ready, the UI answers on the PC, the root application is Synced and Healthy at the commit `production` points at on GitHub, the namespace declared in Git exists, and the Infisical operator is installed by Argo CD. Then the app: it answers healthy on `localhost:8000`, reports as its version that same commit, runs the GHCR image with no pull credentials, and reads the session key created in Infisical: the fingerprint it reports matches the value the operator synced. It connects to PostgreSQL with the password from Infisical, and PostgreSQL keeps its data when its pod is deleted. A replica count changed by hand and a Service deleted by hand are both put back by Argo CD, and the test prints how many seconds it took. No new file is offered to Git. It then destroys the platform and checks that no node is left and the foundations are intact.

A release needs a push, so its acceptance test runs by hand, with the platform up, right after pushing:

```sh
bash infra/platform/tests/release.sh   # after a push on main, a revert included
```

It waits until the app reports the pushed commit as its version, and checks that the database is at the commit's last migration, applied by the release itself. Then it checks, on GitHub, that the pipeline of the push succeeded and that `production` points at the commit. It ends with one row of [measurements](../../docs/measurements/commit-to-production.md): the time from the push to each step, from the clocks of GitHub, Argo CD and Kubernetes.

Changing a secret needs a person in Infisical, so it is a drill, run by hand with the platform up:

```sh
bash infra/platform/tests/rotation.sh   # inside make shell
```

It asks you to give `SESSION_SECRET` a new value in Infisical, then prints the seconds until the new value is in the cluster and until the restarted app runs with it. Only fingerprints are printed, never values.

One behaviour needs a commit, so it is checked by hand: add a manifest to `gitops/apps` (a namespace, for example), push it, and it appears in the cluster within about three minutes of the end of the pipeline; remove it, push, and it is deleted.

## Choices checked on 2026-10-15

- **The kind provider.** [tehcyx/kind](https://registry.terraform.io/providers/tehcyx/kind/latest) is maintained by the community, by one person; the original kyma-incubator provider is archived. Version 0.11.0 (February 2026) embeds kind 0.31; the repository is active (last push September 2026, an open Dependabot update to kind 0.33) and has no open bug reports. Pinned to `~> 0.11.0`, with the node image pinned by digest from the kind 0.31 release notes. If it ever breaks, the fallback is a `terraform_data` resource running the kind CLI.
- **Kubernetes 1.34, not 1.35.** Kubernetes 1.35 [refuses cgroup v1 hosts](https://kubernetes.io/blog/2026/10/06/kubernetes-cgroups-v2-shift/) by default, and Docker Desktop on this PC (WSL 2.4.13, kernel 5.15) still runs cgroup v1: with the 1.35 node image, `kubeadm init` fails. 1.34 reaches its end of life on 2026-10-27. Moving on needs cgroup v2 on the PC: WSL 2.7 or later lets `wsl.conf` select the cgroup version.

## Choices checked on 2026-10-19

- **Infisical's free plan** ([pricing](https://infisical.com/pricing)): 5 identities, people included, unlimited projects, 3 environments, 10 secret syncs. The project plans three machine identities, the cluster's being the first: with the owner's account, four of five. It uses one environment. Not included: secret versioning and point-in-time recovery (a value overwritten in Infisical is gone, so the AWS key rotation creates the new key before retiring the old one), secret rotation, and instant updates pushed to the operator (it polls every 60 seconds instead). First checked on 2026-10-16.
- **The operator.** Chart `secrets-operator` 0.11.12 (2026-10-16), from Infisical's Helm repository; since January 2026 its code lives in [Infisical/kubernetes-operator](https://github.com/Infisical/kubernetes-operator). It uses the `v1beta1` kinds, which replace `InfisicalSecret`: `InfisicalConnection` (where Infisical is), `InfisicalAuth` (who signs in) and `InfisicalStaticSecret` (what to copy, and where). Its pod meets the restricted Pod Security Standard, which the `infisical` namespace enforces.
- **Write-only Secret data.** `kubernetes_secret_v1` takes `data_wo` from version 2.36 of the Kubernetes provider, and a bug with it was fixed in 3.2.1; pinned to `~> 3.3`. With `data_wo_revision` set, the provider never reads the values back into the state.
