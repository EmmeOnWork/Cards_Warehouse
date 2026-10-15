# Platform

What one command recreates on the PC:

- `cards-warehouse`: a single-node [kind](https://kind.sigs.k8s.io/) cluster on Docker Desktop, Kubernetes 1.34.3;
- Argo CD 3.5.4, installed with the official `argo-cd` Helm chart;
- `root`: the Argo CD application that applies [gitops/apps](../../gitops/apps/) from the `main` branch. Everything else reaches the cluster through Git, not through Terraform.

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

## How it fits together

- **The toolbox talks to the cluster.** kind creates the nodes as containers on the PC's Docker, through the docker CLI and the mounted socket. The toolbox runs on the network of the Docker host, where kind publishes the cluster API on `127.0.0.1`, so the kubeconfig written by kind works unchanged. That kubeconfig lives in a Docker volume mounted at `~/.kube`, out of the repository: left without a path, the kind provider would export it into the working directory.
- **One apply, three steps.** Terraform creates the cluster, then configures the Helm provider from the cluster's attributes and installs Argo CD and the root application. The root application is a release of the `argocd-apps` chart, not a `kubernetes_manifest`, which would need the cluster to exist already when the plan is made.
- **Only the PC's loopback.** The cluster publishes the Argo CD node port on `127.0.0.1:8090` and its API on `127.0.0.1`: nothing is reachable from the home network. For the same reason, Argo CD serves the UI in plain HTTP.
- **Polling.** GitHub cannot reach the cluster, so Argo CD polls the repository, as described in [gitops/](../../gitops/).
- **What the state holds.** The kind provider stores the cluster's kubeconfig in the state, client key included. That key only opens a cluster bound to the PC's loopback and dies with it. The state bucket is private.

## Checks

```sh
make tf-check                            # format, validity and unit tests: no Docker, no AWS
bash infra/platform/tests/acceptance.sh  # inside make shell: a whole cycle, about 3 minutes
```

The unit tests in [tests/platform.tftest.hcl](tests/platform.tftest.hcl) check the plan against mock providers: the UI published only on the loopback, the path from port 8090 to the Argo CD server, the root application following `main` with self-heal and prune.

The acceptance test starts from no cluster and runs the real thing: while `terraform apply` runs, a second run is refused by the S3 lock; then the node is Ready, the UI answers on the PC, the root application is Synced and Healthy at the last commit on GitHub, the namespace declared in Git exists, and no new file is offered to Git. It then destroys the platform and checks that no node is left and the foundations are intact.

One behaviour needs a commit, so it is checked by hand: add a manifest to `gitops/apps` (a namespace, for example), push it, and it appears in the cluster within about three minutes; remove it, push, and it is deleted.

## Choices checked on 2026-10-15

- **The kind provider.** [tehcyx/kind](https://registry.terraform.io/providers/tehcyx/kind/latest) is maintained by the community, by one person; the original kyma-incubator provider is archived. Version 0.11.0 (February 2026) embeds kind 0.31; the repository is active (last push September 2026, an open Dependabot update to kind 0.33) and has no open bug reports. Pinned to `~> 0.11.0`, with the node image pinned by digest from the kind 0.31 release notes. If it ever breaks, the fallback is a `terraform_data` resource running the kind CLI.
- **Kubernetes 1.34, not 1.35.** Kubernetes 1.35 [refuses cgroup v1 hosts](https://kubernetes.io/blog/2026/10/06/kubernetes-cgroups-v2-shift/) by default, and Docker Desktop on this PC (WSL 2.4.13, kernel 5.15) still runs cgroup v1: with the 1.35 node image, `kubeadm init` fails. 1.34 reaches its end of life on 2026-10-27. Moving on needs cgroup v2 on the PC: WSL 2.7 or later lets `wsl.conf` select the cgroup version.
