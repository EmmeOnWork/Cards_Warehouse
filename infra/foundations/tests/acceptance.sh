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
photos_bucket=$(terraform output -raw photos_bucket)
backups_bucket=$(terraform output -raw backups_bucket)
app_user=$(terraform output -raw app_user)

# --- State and lock ---

state_is_in_s3() {
  aws s3api head-object --bucket "$state_bucket" --key "$state_key" >/dev/null
}

# `state replace-provider` asks for confirmation while it holds the lock. Swapping
# the aws provider for itself changes nothing, and the answer given is always "no".
second_run_is_refused() {
  local answer log first second refused=1
  answer=$(mktemp -u) log=$(mktemp)
  mkfifo "$answer"
  terraform state replace-provider hashicorp/aws hashicorp/aws <"$answer" >"$log" 2>&1 &
  first=$!
  exec 3>"$answer"
  if timeout 120 bash -c "until grep -q 'Enter a value' '$log'; do sleep 1; done" &&
    aws s3api head-object --bucket "$state_bucket" --key "$state_key.tflock" >/dev/null; then
    # The refused plan exits with 1: keep its output apart, or pipefail would fail the check.
    second=$(terraform plan -lock-timeout=0 -input=false -no-color 2>&1)
    grep -q 'Error acquiring the state lock' <<<"$second" && refused=0
  fi
  echo no >&3
  exec 3>&-
  wait "$first"
  rm -f "$answer" "$log"
  return "$refused"
}

# --- Buckets ---

is_versioned() { # is_versioned <bucket>
  [[ $(aws s3api get-bucket-versioning --bucket "$1" --query Status --output text) == Enabled ]]
}

blocks_public_access() { # blocks_public_access <bucket>
  [[ $(aws s3api get-public-access-block --bucket "$1" --output text \
    --query 'PublicAccessBlockConfiguration.[BlockPublicAcls,IgnorePublicAcls,BlockPublicPolicy,RestrictPublicBuckets]') == $'True\tTrue\tTrue\tTrue' ]]
}

# --- The app credential, tried with a temporary access key ---
# The key lives only in these variables: never printed, never in the Terraform
# state, and deleted on exit even when a check fails.

key_id="" key_secret="" deleted_key_id=""
probe=acceptance-test/probe.txt
probe_file=$(mktemp)

as_app() {
  # Without a key the CLI would fall back to the operator's own credentials.
  [[ -n $key_id ]] || return 1
  AWS_ACCESS_KEY_ID=$key_id AWS_SECRET_ACCESS_KEY=$key_secret aws "$@"
}

delete_temporary_key() {
  [[ -z $key_id ]] && return
  aws iam delete-access-key --user-name "$app_user" --access-key-id "$key_id"
  deleted_key_id=$key_id key_id="" key_secret=""
}

clean_up() {
  delete_temporary_key
  # The photos bucket keeps every version of the probe and its delete marker.
  local version
  for version in $(aws s3api list-object-versions --bucket "$photos_bucket" --prefix "$probe" \
    --query '[Versions, DeleteMarkers][][].VersionId' --output text); do
    [[ $version != None ]] && aws s3api delete-object --bucket "$photos_bucket" --key "$probe" --version-id "$version" >/dev/null
  done
  rm -f "$probe_file"
}

# A new key takes a few seconds to be accepted everywhere in AWS.
key_is_accepted() {
  local attempt
  for attempt in {1..30}; do
    [[ $(as_app sts get-caller-identity --query Arn --output text 2>/dev/null) == *":user/$app_user" ]] &&
      as_app s3api list-objects-v2 --bucket "$photos_bucket" --max-keys 1 >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

reads_and_writes() { # reads_and_writes <bucket>
  as_app s3api put-object --bucket "$1" --key "$probe" --body "$probe_file" >/dev/null &&
    as_app s3api get-object --bucket "$1" --key "$probe" /dev/null >/dev/null &&
    [[ $(as_app s3api list-objects-v2 --bucket "$1" --prefix "$probe" --query 'Contents[].Key' --output text) == "$probe" ]] &&
    as_app s3api delete-object --bucket "$1" --key "$probe" >/dev/null
}

is_denied() { # is_denied <aws arguments...>: the app key gets an authorization error
  local out
  if out=$(as_app "$@" 2>&1); then return 1; fi
  grep -qE 'AccessDenied|UnauthorizedOperation|not authorized' <<<"$out"
}

key_is_gone() {
  [[ -n $deleted_key_id ]] &&
    ! aws iam list-access-keys --user-name "$app_user" --query 'AccessKeyMetadata[].AccessKeyId' --output text | grep -q "$deleted_key_id"
}

# --- State contents, budget, protection ---

state_holds_no_secret() {
  local state
  state=$(terraform state pull) || return 1
  # The app user proves the real state was read: an empty one would hold no secret either.
  grep -q '"aws_iam_user"' <<<"$state" && ! grep -qiE 'aws_iam_access_key|secret' <<<"$state"
}

budget_emails_above_5_usd() {
  local account=$(aws sts get-caller-identity --query Account --output text)
  local budget=(--account-id "$account" --budget-name cards-warehouse-monthly)
  [[ $(aws budgets describe-budget "${budget[@]}" --output text \
    --query 'Budget.[BudgetLimit.Amount,BudgetLimit.Unit,CostTypes.IncludeCredit]') == $'5.0\tUSD\tFalse' ]] &&
    [[ $(aws budgets describe-subscribers-for-notification "${budget[@]}" --output text \
      --notification NotificationType=ACTUAL,ComparisonOperator=GREATER_THAN,Threshold=100,ThresholdType=PERCENTAGE \
      --query 'Subscribers[].SubscriptionType') == EMAIL ]]
}

# Only a plan: prevent_destroy makes it fail before anything could be destroyed.
destroy_is_refused() {
  local out
  if out=$(terraform plan -destroy -input=false -no-color 2>&1); then return 1; fi
  grep -q 'Instance cannot be destroyed' <<<"$out"
}

# --- Checks ---

check "the foundations state lives in S3" state_is_in_s3
check "while one run holds the S3 lock file, a second run is refused" second_run_is_refused
check "the photos bucket keeps previous versions" is_versioned "$photos_bucket"
check "the photos bucket blocks public access" blocks_public_access "$photos_bucket"
check "the backups bucket blocks public access" blocks_public_access "$backups_bucket"

trap clean_up EXIT
read -r key_id key_secret < <(aws iam create-access-key --user-name "$app_user" \
  --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
check "a temporary key of the app user is accepted" key_is_accepted
check "the app key reads and writes in the photos bucket" reads_and_writes "$photos_bucket"
check "the app key reads and writes in the backups bucket" reads_and_writes "$backups_bucket"
check "the app key cannot read the Terraform state" is_denied s3api get-object --bucket "$state_bucket" --key "$state_key" /dev/null
check "the app key cannot write into the state bucket" is_denied s3api put-object --bucket "$state_bucket" --key "$probe" --body "$probe_file"
check "the app key cannot list the account's buckets" is_denied s3api list-buckets
check "the app key cannot use IAM" is_denied iam list-users
check "the app key cannot use EC2" is_denied ec2 describe-instances
delete_temporary_key
check "the temporary key no longer exists" key_is_gone
check "the Terraform state holds no access key nor any secret" state_holds_no_secret
check "the budget emails once the month's spending, before credits, passes 5 USD" budget_emails_above_5_usd
check "a destroy of the foundations is refused" destroy_is_refused

exit $((failures > 0))
