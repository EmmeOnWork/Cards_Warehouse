#!/usr/bin/env bash
# The single local check of the Terraform code: format, validity and tests.
# It never touches AWS: the tests run against a mock provider.
set -euo pipefail
cd "$(dirname "$0")"

terraform fmt -check -recursive
for module in foundations; do
  terraform -chdir="$module" init -backend=false -input=false >/dev/null
  terraform -chdir="$module" validate
  terraform -chdir="$module" test
done
