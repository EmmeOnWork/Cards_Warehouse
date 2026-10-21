# chart

Helm chart that packages the application for Kubernetes: a Deployment, a NodePort Service, and the two resources of the Infisical operator that bring the app its secrets:

- `InfisicalAuth`: signs in to Infisical as the cluster's machine identity, with the credential Terraform puts in the `infisical` namespace;
- `InfisicalStaticSecret`: copies the app's folder in Infisical into the Secret `cards-warehouse-secrets`, which it owns, and reads it again every minute.

The Deployment gives the app each secret listed in `secrets` as an environment variable from that Secret. When a value changes, the operator restarts the Deployment (annotation `secrets.infisical.com/auto-reload`), since the app reads its secrets only at start.

Argo CD renders it from this folder at the commit the `production` branch points at, through the `cards-warehouse` Application in [gitops/apps](../gitops/apps/cards-warehouse.yaml). That Application gives the one value the chart has no default for: `image.tag`, set to that same commit. Without it, rendering fails instead of running an unknown version.

## Values

| Value | Default | What it sets |
|---|---|---|
| `image.repository` | `ghcr.io/emmeonwork/cards-warehouse` | Public image on GHCR: the node pulls it with no credentials |
| `image.tag` | none, required | The commit to run |
| `secrets` | `[SESSION_SECRET]` | The secrets the app needs, by name only: the list in Git. A name missing from Infisical keeps the pod from starting |
| `infisical.projectSlug`, `.environment`, `.secretPath` | the project, `prod`, `/app` | Where the values live in Infisical |
| `infisical.refreshInterval` | `60s` | How often the operator reads Infisical again |
| `infisical.credentials` | `infisical-credentials` in `infisical` | The Secret Terraform creates with the cluster's credential |
| `infisical.connection` | `default` in `infisical` | The operator's default connection, which holds the address of Infisical |
| `replicas` | `1` | Always written into the Deployment, so Argo CD sees a change made by hand |
| `service.nodePort` | `30000` | The node port the kind cluster maps to `127.0.0.1:8000` on the PC |
| `livenessProbe`, `readinessProbe` | `/livez`, `/readyz` on the `http` port | The app's health endpoints |
| `resources` | 50m CPU and 64Mi requested, 128Mi memory limit | Measured: about 51 MiB after 600 requests |

The pod meets the restricted [Pod Security Standard](https://kubernetes.io/docs/concepts/security/pod-security-standards/), which the `cards-warehouse` namespace enforces: not root, no privilege escalation, no capabilities, read-only root filesystem. It mounts no Kubernetes API token, since the app never calls the API. These are fixed in the templates, not values.

## Checks

```sh
make chart-check
```

It runs, in the toolbox:

1. `helm lint --strict`: the chart is well formed.
2. `helm template | kubeconform -strict`: what the chart renders is valid against the schemas of Kubernetes 1.34.3, the version of the cluster, with no unknown field. The Infisical kinds are checked against the schemas of the community [CRD catalog](https://github.com/datreeio/CRDs-catalog), pinned by commit.

Helm is 4.2.1, the version Argo CD 3.5.4 renders charts with, so the checks see the same manifests as the cluster.
