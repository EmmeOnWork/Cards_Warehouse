#!/usr/bin/env bash
# Acceptance test of the AWS foundations, run by hand against the real account.
# Inside the toolbox (make shell), after `aws login --remote`:
#   bash infra/foundations/tests/acceptance.sh
set -uo pipefail
cd "$(dirname "$0")/.."

failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

if ! terraform init -input=false >/dev/null || ! state_bucket=$(terraform output -raw state_bucket 2>/dev/null); then
  echo "FAIL  the foundations are not deployed: no state with their outputs"
  exit 1
fi
state_key=foundations/terraform.tfstate

state_is_in_s3() {
  aws s3api head-object --bucket "$state_bucket" --key "$state_key" >/dev/null
}

# `state replace-provider` asks for confirmation while it holds the lock. Swapping
# the aws provider for itself changes nothing, and the answer given is always "no".
second_run_is_refused() {
  local answer log first refused=1
  answer=$(mktemp -u) log=$(mktemp)
  mkfifo "$answer"
  terraform state replace-provider hashicorp/aws hashicorp/aws <"$answer" >"$log" 2>&1 &
  first=$!
  exec 3>"$answer"
  if timeout 120 bash -c "until grep -q 'Enter a value' '$log'; do sleep 1; done" &&
    aws s3api head-object --bucket "$state_bucket" --key "$state_key.tflock" >/dev/null &&
    terraform plan -lock-timeout=0 -input=false -no-color 2>&1 | grep -q 'Error acquiring the state lock'; then
    refused=0
  fi
  echo no >&3
  exec 3>&-
  wait "$first"
  rm -f "$answer" "$log"
  return "$refused"
}

check "the foundations state lives in S3" state_is_in_s3
check "while one run holds the S3 lock file, a second run is refused" second_run_is_refused

exit $((failures > 0))
