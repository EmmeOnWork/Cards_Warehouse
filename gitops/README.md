# gitops

Desired state of the cluster, read and applied by Argo CD.

Terraform creates a single Argo CD application, `root`, that follows [apps/](apps/) on the `main` branch of this repository. Whatever that folder holds reaches the cluster with no manual command: plain resources such as a namespace, and the Argo CD `Application` manifests of everything else (the app now; later monitoring and backups). This is the *app of apps* pattern.

| File | What it is |
|---|---|
| [apps/cards-warehouse-namespace.yaml](apps/cards-warehouse-namespace.yaml) | The app's namespace, which enforces the restricted Pod Security Standard |
| [apps/cards-warehouse.yaml](apps/cards-warehouse.yaml) | The app: the [chart](../chart/) from `main`, with `image.tag`, the commit whose image runs |

- **The version of the app lives here.** `image.tag` in the app's Application is the one place that says which image runs. Changing it in Git is how a release happens.
- **Polling.** GitHub cannot reach a cluster on the PC, so Argo CD polls the repository: every 120 seconds plus up to 60 seconds of jitter, the chart defaults. A pushed commit reaches the cluster within about three minutes.
- **Automated sync with self-heal and prune.** A change made by hand in the cluster is undone, a resource deleted by hand is created again, and a manifest removed from Git is deleted from the cluster. Both `root` and the app's Application sync this way.
- **Cascade delete.** The app's Application carries the Argo CD resources finalizer: if it leaves Git, what it installed is deleted with it, instead of being left running without an owner.
