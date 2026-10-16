#!/usr/bin/env bash
# Acceptance test of the platform, run by hand: a whole cycle, from no cluster
# to the one-command creation and back to no cluster. Inside the toolbox
# (make shell), after `aws login --remote`:
#   bash infra/platform/tests/acceptance.sh
set -uo pipefail
cd "$(dirname "$0")/.."

cluster=cards-warehouse
prefix=emmeonwork-cards-warehouse
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

# kind labels every node container with the name of its cluster.
cluster_nodes() {
  docker ps --all --quiet --filter "label=io.x-k8s.kind.cluster=$cluster"
}

new_to_git() { # files Git would offer to commit: untracked and not ignored
  git -C ../.. -c safe.directory='*' status --porcelain --untracked-files=all | sed -n 's/^?? //p' | sort
}

succeeded() { # succeeded <exit status> <log>
  [[ $1 -eq 0 ]] || { tail -n 20 "$2"; return 1; }
}

if [[ -n $(cluster_nodes) ]]; then
  echo "FAIL  the test starts from no cluster, but $cluster exists: run make platform-down first"
  exit 1
fi
if ! terraform init -input=false >/dev/null; then
  echo "FAIL  terraform init"
  exit 1
fi
log=$(mktemp)
trap 'rm -f "$log"' EXIT

# --- Creation: the one command ---

state_key=platform/terraform.tfstate

# The S3 lock file exists only while a run holds the state.
lock_refuses_a_second_run() {
  local attempt second
  for attempt in {1..30}; do
    aws s3api head-object --bucket "$prefix-tfstate" --key "$state_key.tflock" >/dev/null 2>&1 && break
    sleep 1
  done
  # The refused plan exits with 1: keep its output apart, or pipefail would fail the check.
  second=$(terraform plan -lock-timeout=0 -input=false -no-color 2>&1)
  grep -q 'Error acquiring the state lock' <<<"$second"
}

state_is_in_s3() {
  aws s3api head-object --bucket "$prefix-tfstate" --key "$state_key" >/dev/null
}

new_before_apply=$(new_to_git)
SECONDS=0
terraform apply -auto-approve -input=false -no-color >"$log" 2>&1 &
apply_pid=$!
check "while the apply runs, a second run is refused by the S3 lock" lock_refuses_a_second_run
wait "$apply_pid"
apply_status=$?
echo "      terraform apply took $((SECONDS / 60)) min $((SECONDS % 60)) s"

node_is_ready() {
  kubectl --context "kind-$cluster" wait node --all --for=condition=Ready --timeout=120s >/dev/null
}

# From a container, host.docker.internal is the PC: the same port a browser on the PC opens.
argocd_ui_answers_on_the_pc() {
  curl --silent --fail --max-time 5 --retry 12 --retry-delay 5 --retry-all-errors \
    http://host.docker.internal:8090/ | grep -q '<title>Argo CD</title>'
}

argocd() { # argocd <kubectl arguments...>: kubectl in the Argo CD namespace
  kubectl --context "kind-$cluster" --namespace argocd "$@"
}

# Synced and Healthy at the last commit of the branch it follows, read from GitHub.
# The first sync starts as soon as Argo CD sees the application: allow it three minutes.
root_app_is_synced_with_git() {
  local source repo branch head status attempt
  source=$(argocd get application root -o jsonpath='{.spec.source.repoURL} {.spec.source.targetRevision}') || return 1
  read -r repo branch <<<"$source"
  head=$(git ls-remote "$repo" "refs/heads/$branch" | cut -f1)
  for attempt in {1..36}; do
    status=$(argocd get application root -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision}')
    [[ $status == "Synced Healthy $head" ]] && return 0
    sleep 5
  done
  echo "      root application: $status; $branch on GitHub: $head"
  argocd get application root -o jsonpath='{.status.conditions[*].message}{"\n"}'
  return 1
}

# Argo CD marks what it applies with a tracking annotation naming the application.
namespace_from_git_exists() {
  kubectl --context "kind-$cluster" get namespace cards-warehouse \
    -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/tracking-id}' | grep -q '^root:'
}

# The root application creates the app's Application, which installs the chart; the node
# then pulls the image from GHCR. The Service sends traffic only to a Ready pod: allow five minutes.
app_answers_healthy_on_the_pc() {
  curl --silent --fail --max-time 5 --retry 30 --retry-delay 5 --retry-all-errors \
    http://host.docker.internal:8000/readyz >/dev/null
}

# The tag in gitops/apps at the last commit of main, read from GitHub itself rather than from
# Argo CD. A commit in the URL, not the branch: the raw files of a branch are cached for minutes.
app_reports_the_version_in_git() {
  local head tag version
  head=$(git ls-remote https://github.com/EmmeOnWork/Cards_Warehouse.git refs/heads/main | cut -f1)
  tag=$(curl --silent --fail "https://raw.githubusercontent.com/EmmeOnWork/Cards_Warehouse/$head/gitops/apps/cards-warehouse.yaml" |
    sed -n 's/^ *tag: *//p')
  version=$(curl --silent --fail --max-time 5 http://host.docker.internal:8000/version)
  [[ -n $tag && $version == "{\"version\":\"$tag\"}" ]] || {
    echo "      in Git: ${tag:-no tag}; the app reports: ${version:-nothing}"
    return 1
  }
}

app() { # app <kubectl arguments...>: kubectl in the app's namespace
  kubectl --context "kind-$cluster" --namespace cards-warehouse "$@"
}

# The pod runs, so the node pulled its image; neither the pod nor its service account holds a registry login.
image_pulled_from_ghcr_without_credentials() {
  local pods image secrets
  pods=(get pods -l app.kubernetes.io/name=cards-warehouse)
  image=$(app "${pods[@]}" -o jsonpath='{.items[0].status.containerStatuses[0].imageID}')
  secrets=$(app "${pods[@]}" -o jsonpath='{.items[0].spec.imagePullSecrets}')$(app get serviceaccount default -o jsonpath='{.imagePullSecrets}')
  [[ $image == ghcr.io/emmeonwork/cards-warehouse@sha256:* && -z $secrets ]] || {
    echo "      image: ${image:-none}; pull secrets: ${secrets:-none}"
    return 1
  }
}

# Scale by hand, as someone with kubectl would, and wait for Argo CD to restore the count in Git.
hand_scaling_is_undone() {
  local in_git replicas start=$SECONDS
  in_git=$(app get deployment cards-warehouse -o jsonpath='{.spec.replicas}') || return 1
  app scale deployment cards-warehouse --replicas=$((in_git + 2)) >/dev/null || return 1
  while ((SECONDS - start < 300)); do
    replicas=$(app get deployment cards-warehouse -o jsonpath='{.spec.replicas}')
    [[ $replicas == "$in_git" ]] && { echo "      undone after $((SECONDS - start)) s"; return 0; }
    sleep 1
  done
  echo "      still $replicas replicas, $in_git in Git"
  return 1
}

# A new uid means a new object: the Service deleted by hand was created again.
deleted_service_is_created_again() {
  local uid now start=$SECONDS
  uid=$(app get service cards-warehouse -o jsonpath='{.metadata.uid}') || return 1
  app delete service cards-warehouse >/dev/null || return 1
  while ((SECONDS - start < 300)); do
    now=$(app get service cards-warehouse -o jsonpath='{.metadata.uid}' 2>/dev/null)
    [[ -n $now && $now != "$uid" ]] && { echo "      created again after $((SECONDS - start)) s"; return 0; }
    sleep 1
  done
  return 1
}

# Files such as the kubeconfig must never be offered to a commit.
repository_gets_no_new_file() {
  local new
  new=$(comm -13 <(echo "$new_before_apply") <(new_to_git))
  [[ -z $new ]] || { echo "      new files: $new"; return 1; }
}

check "one terraform apply, from no cluster, succeeds" succeeded "$apply_status" "$log"
check "the platform state lives in S3, under its own key" state_is_in_s3
check "the cluster node is Ready" node_is_ready
check "the Argo CD UI answers on the PC at localhost:8090" argocd_ui_answers_on_the_pc
check "the root application is Synced and Healthy at the last commit on GitHub" root_app_is_synced_with_git
check "the namespace declared in Git exists, applied by Argo CD" namespace_from_git_exists
check "the app answers healthy on the PC at localhost:8000" app_answers_healthy_on_the_pc
check "the app reports the version written in Git" app_reports_the_version_in_git
check "the cluster pulled the image from GHCR without credentials" image_pulled_from_ghcr_without_credentials
check "a replica count changed by hand is undone by Argo CD" hand_scaling_is_undone
check "a Service deleted by hand is created again by Argo CD" deleted_service_is_created_again
check "the apply writes no file into the repository" repository_gets_no_new_file

# --- Destruction ---

terraform destroy -auto-approve -input=false -no-color >"$log" 2>&1
destroy_status=$?

no_cluster_node_is_left() {
  [[ -z $(cluster_nodes) ]]
}

foundations_are_intact() {
  local name
  aws s3api head-object --bucket "$prefix-tfstate" --key foundations/terraform.tfstate >/dev/null || return 1
  for name in tfstate photos backups; do
    aws s3api head-bucket --bucket "$prefix-$name" >/dev/null || return 1
  done
}

check "terraform destroy succeeds" succeeded "$destroy_status" "$log"
check "no node of the cluster is left" no_cluster_node_is_left
check "the foundations state and the three buckets are intact" foundations_are_intact

exit $((failures > 0))
