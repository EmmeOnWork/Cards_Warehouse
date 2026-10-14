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
| `make test` | Runs the app tests, including the ones that build and run the real image |
| `make app-shell` | Opens a shell with Python, uv and the Docker CLI, in `app/` |
| `make shell` | Opens a shell with Terraform and the AWS CLI |
| `make tf-check` | Checks format and validity of the Terraform code and runs its tests |

## Secret protection

The repository is public, so no secret may ever enter Git. Three checks stand in the way:

1. **Before every commit**, a [gitleaks](https://github.com/gitleaks/gitleaks) hook scans the staged changes, running the official gitleaks image. Enable it with `make hooks`.
2. **On push**, GitHub push protection rejects known token formats.
3. **In the pipeline** (not built yet), the same gitleaks image will scan the whole history.
