# Every tool runs inside a container: the PC needs only Docker, Git and make.
TOOLBOX := docker compose -f infra/toolbox/compose.yaml run --rm toolbox
APP_RUN := docker compose -f app/compose.yaml run --rm --build
APP_DEV := $(APP_RUN) dev

.PHONY: shell tf-check platform-up platform-down app-shell lint test scan verify-published hooks

shell: ## Open a shell with terraform, the AWS CLI and kubectl
	$(TOOLBOX) bash

tf-check: ## Check Terraform format and validity, then run the Terraform tests
	$(TOOLBOX) bash infra/check.sh

platform-up: ## Create the kind cluster, Argo CD and its root application (after aws login)
	$(TOOLBOX) sh -c "terraform -chdir=infra/platform init -input=false && terraform -chdir=infra/platform apply -auto-approve -input=false"

platform-down: ## Destroy the cluster; the AWS foundations are not touched
	$(TOOLBOX) sh -c "terraform -chdir=infra/platform init -input=false && terraform -chdir=infra/platform destroy -auto-approve -input=false"

app-shell: ## Open a shell with Python, uv, the Docker CLI, trivy and actionlint, in app/
	$(APP_DEV) bash

lint: ## Check style: ruff on the Python code, actionlint on the pipeline
	$(APP_DEV) sh -c 'uv run ruff check && uv run ruff format --check && cd .. && actionlint'

test: ## Run the app tests, unit and acceptance (builds and runs the real image)
	$(APP_DEV) uv run pytest

scan: ## Fail when IMAGE=<image> has a HIGH or CRITICAL vulnerability with a fix (policy: app/trivy.yaml)
	$(if $(IMAGE),,$(error usage: make scan IMAGE=<image>))
	$(APP_DEV) trivy image $(IMAGE)

verify-published: ## Check that the image published for SHA=<commit> is public and reports that commit
	$(if $(SHA),,$(error usage: make verify-published SHA=<commit>))
	$(APP_RUN) -e PUBLISHED_SHA=$(SHA) dev uv run pytest -v tests/acceptance/test_published_image.py

hooks: ## Enable the gitleaks pre-commit hook, once per clone (needs Docker running)
	git config core.hooksPath .githooks
