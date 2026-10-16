# chart

Helm chart that packages the application for Kubernetes: a Deployment and a NodePort Service.

Argo CD renders it from this folder on `main`, through the `cards-warehouse` Application in [gitops/apps](../gitops/apps/cards-warehouse.yaml). That Application gives the one value the chart has no default for: `image.tag`, the commit whose image runs. Without it, rendering fails instead of running an unknown version.

## Values

| Value | Default | What it sets |
|---|---|---|
| `image.repository` | `ghcr.io/emmeonwork/cards-warehouse` | Public image on GHCR: the node pulls it with no credentials |
| `image.tag` | none, required | The commit to run |
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
2. `helm unittest`: the tests in [tests/](tests/), written with [helm-unittest](https://github.com/helm-unittest/helm-unittest). They render the templates and check the result, in milliseconds and with no cluster.
3. `helm template | kubeconform -strict`: what the chart renders is valid against the schemas of Kubernetes 1.34.3, the version of the cluster, with no unknown field.

Helm is 4.2.1, the version Argo CD 3.5.4 renders charts with, so the checks see the same manifests as the cluster.
