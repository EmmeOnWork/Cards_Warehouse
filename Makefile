# Every tool runs inside a container: the PC needs only Docker, Git and make.
TOOLBOX := docker compose -f infra/toolbox/compose.yaml run --rm --build toolbox
APP_DEV := docker compose -f app/compose.yaml run --rm --build dev

.PHONY: shell tf-check chart-check platform-up platform-down backup restore tailscale-up app-shell lint test password-hash ebay-connect ebay-setup ebay-record scan hooks

shell: ## Open a shell with terraform, the AWS CLI, kubectl, Helm and Velero
	$(TOOLBOX) bash

tf-check: ## Check Terraform format and validity, then run the Terraform tests
	$(TOOLBOX) bash infra/check.sh

# The image tag is only a placeholder: Argo CD gives the real one, the commit it reads.
# Schemas of Kubernetes 1.34.3, the version of the cluster node (infra/platform/cluster.tf), and for the
# Infisical and Argo CD kinds the community CRD catalog, pinned by commit. Checked against operator 0.11.12 on
# 2026-10-19: same fields; the catalog still requires infisicalConnectionRef, which the operator made optional.
# The values Argo CD passes to a chart (valuesObject) are not checked: no schema describes them.
CRD_SCHEMAS := https://raw.githubusercontent.com/datreeio/CRDs-catalog/501527ab9c40c827144c8f45945b25a023e344ce/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json
KUBECONFORM := kubeconform -strict -summary -kubernetes-version 1.34.3 -schema-location default -schema-location "$(CRD_SCHEMAS)"
chart-check: ## Lint the chart, and check what it renders and the manifests in gitops/ against the Kubernetes schemas
	$(TOOLBOX) bash -o pipefail -c '\
	  helm lint --strict chart --set image.tag=check && \
	  helm template cards-warehouse chart --set image.tag=check | $(KUBECONFORM) && \
	  $(KUBECONFORM) gitops'

platform-up: ## Create the kind cluster, Argo CD and its root application (after aws login)
	$(TOOLBOX) sh -c "terraform -chdir=infra/platform init -input=false && terraform -chdir=infra/platform apply -auto-approve -input=false"

platform-down: ## Destroy the cluster; the AWS foundations are not touched
	$(TOOLBOX) sh -c "terraform -chdir=infra/platform init -input=false && terraform -chdir=infra/platform destroy -auto-approve -input=false"

# Named by Velero after the schedule and the time: velero-daily-<YYYYMMDDhhmmss>.
backup: ## Back up now, the same as the daily backup, and wait for its outcome (platform up)
	$(TOOLBOX) velero backup create --from-schedule velero-daily --wait

# On a new cluster, after make platform-up: docs/restore.md. Needs no aws login.
restore: ## Load the app's data from a backup (platform up): the newest that completed, or BACKUP=<name>
	$(TOOLBOX) bash infra/platform/restore.sh $(BACKUP)

# Waits up to 30 s for the node to reach Tailscale: then either it is in, or it has a login link.
tailscale-up: ## Start the Tailscale node that brings the app to the phone, and print its address: the first time, a login link
	docker compose -f infra/tailscale/compose.yaml up --detach
	@docker exec cards-warehouse-tailscale sh -c 'for second in $$(seq 30); do \
	  if tailscale status >/dev/null 2>&1; then tailscale serve status; exit; fi; \
	  tailscale status 2>&1 | grep "Log in at" && exit; sleep 1; done; tailscale status'

app-shell: ## Open a shell with Python, uv, the Docker CLI, trivy and actionlint, in app/
	$(APP_DEV) bash

lint: ## Check style: ruff on the Python code, actionlint on the pipeline
	$(APP_DEV) sh -c 'uv run ruff check && uv run ruff format --check && cd .. && actionlint'

test: ## Run the app tests, unit and acceptance (builds and runs the real image)
	$(APP_DEV) uv run pytest

password-hash: ## Ask for a new app password, unseen, and print its hash: the value of PASSWORD_HASH in Infisical
	$(APP_DEV) uv run --quiet python -m cards_warehouse.password

ebay-connect: ## Connect the eBay account: a link to agree on eBay, then the values to put in Infisical (docs/ebay.md)
	$(APP_DEV) uv run --quiet python -m cards_warehouse.ebay_connect

ebay-setup: ## Set up the eBay account for the app's listings: policies and location, values for Infisical (docs/ebay.md)
	$(APP_DEV) uv run --quiet python -m cards_warehouse.ebay_setup

ebay-record: ## Publish three listings on the eBay sandbox and record its answers for the tests (docs/ebay.md)
	$(APP_DEV) uv run --quiet python -m tests.ebay_recording

scan: ## Fail when IMAGE=<image> has a HIGH or CRITICAL vulnerability with a fix (policy: app/trivy.yaml)
	$(if $(IMAGE),,$(error usage: make scan IMAGE=<image>))
	$(APP_DEV) trivy image $(IMAGE)

hooks: ## Enable the gitleaks pre-commit hook, once per clone (needs Docker running)
	git config core.hooksPath .githooks
