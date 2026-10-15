# gitops

Desired state of the cluster, read and applied by Argo CD.

Terraform creates a single Argo CD application, `root`, that follows [apps/](apps/) on the `main` branch of this repository. Whatever that folder holds reaches the cluster with no manual command: plain resources such as a namespace, and later the Argo CD `Application` manifests of everything else (the app, monitoring, backups).

- **Polling.** GitHub cannot reach a cluster on the PC, so Argo CD polls the repository: every 120 seconds plus up to 60 seconds of jitter, the chart defaults. A pushed commit reaches the cluster within about three minutes.
- **Automated sync with self-heal and prune.** A change made by hand in the cluster is undone, and a manifest removed from Git is deleted from the cluster.
