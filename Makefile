# Every tool runs inside a container: the PC needs only Docker, Git and make.
TOOLBOX := docker compose -f infra/toolbox/compose.yaml run --rm toolbox
APP_DEV := docker compose -f app/compose.yaml run --rm dev

.PHONY: shell tf-check app-shell test hooks

shell: ## Open a shell with terraform and the AWS CLI
	$(TOOLBOX) bash

tf-check: ## Check Terraform format and validity, then run the Terraform tests
	$(TOOLBOX) bash infra/check.sh

app-shell: ## Open a shell with Python, uv and the Docker CLI, in app/
	$(APP_DEV) bash

test: ## Run the app tests, unit and acceptance (builds and runs the real image)
	$(APP_DEV) uv run pytest

hooks: ## Enable the gitleaks pre-commit hook, once per clone (needs Docker running)
	git config core.hooksPath .githooks
