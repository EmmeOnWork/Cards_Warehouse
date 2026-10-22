# Trading card inventory on a GitOps platform

A multichannel inventory manager for trading cards and sealed products, running on a local Kubernetes platform built to be recreated from code.

Work in progress.

## Layout

| Folder | Content |
|---|---|
| [app/](app/) | FastAPI application |
| [chart/](chart/) | Helm chart for the application |
| [infra/](infra/) | Terraform: AWS foundations and the platform |
| [gitops/](gitops/) | Configuration applied by Argo CD |

## Working on it

Every tool runs in a container with pinned versions: the PC needs only Docker, Git and make.

| Command | What it does |
|---|---|
| `make hooks` | Enables the secret check before every commit, once per clone |
| `make lint` | Checks the style of the Python code (ruff) and of the pipeline (actionlint) |
| `make test` | Runs the app tests against a real PostgreSQL, including the ones that build and run the real image |
| `make scan IMAGE=<image>` | Fails when the image has a HIGH or CRITICAL vulnerability with a fix |
| `make app-shell` | Opens a shell with Python, uv, the Docker CLI, trivy and actionlint, in `app/` |
| `make shell` | Opens a shell with Terraform, the AWS CLI, kubectl and Helm |
| `make tf-check` | Checks format and validity of the Terraform code and runs its tests |
| `make chart-check` | Lints the Helm chart and validates what it renders against the Kubernetes schemas |
| `make platform-up` | Creates the kind cluster with Argo CD, which then applies [gitops/](gitops/): the app answers at <http://localhost:8000> |
| `make platform-down` | Destroys the cluster, leaving the AWS foundations untouched |

## Secret protection

The repository is public, so no secret may ever enter Git. The secrets live in Infisical Cloud and reach the cluster through its operator; Git holds only their names ([how](infra/platform/README.md#secrets)). Three checks stand in the way:

1. **Before every commit**, a [gitleaks](https://github.com/gitleaks/gitleaks) hook scans the staged changes, running the official gitleaks image. Enable it with `make hooks`.
2. **On push**, GitHub push protection rejects known token formats.
3. **In the pipeline**, the same gitleaks image scans the whole history.

## Pipeline

[GitHub Actions](.github/workflows/pipeline.yaml) runs on every push on `main` and on every pull request:

```
secrets ──┐
checks ───┼─► image ─► release
platform ─┘
```

- **secrets**: gitleaks over every commit.
- **checks**: `make lint` and `make test`.
- **platform**: `make tf-check` and `make chart-check`. An image is never published for a commit whose Terraform or chart is broken.
- **image**: builds the image with the commit as its version, then `make scan` with [Trivy](app/trivy.yaml). On `main` only, it pushes `ghcr.io/emmeonwork/cards-warehouse:<commit>`, logged in with the token GitHub gives to the run.
- **release**: on `main` only, moves the `production` branch to the pushed commit. It adds no commit to `main`. Argo CD follows `production`, so the cluster only ever runs a commit that passed everything above: see [gitops/](gitops/README.md#release-and-rollback).

A newer push cancels the run of an older one. Pull requests run the checks and the scan but publish nothing. Every step is a `make` target or a pinned image, the same as on the PC. The only action, `actions/checkout`, is pinned by commit.
