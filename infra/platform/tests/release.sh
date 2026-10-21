#!/usr/bin/env bash
# Acceptance test of a release, run by hand with the platform up, right after a push on main.
# A rollback is a release too: the release of a `git revert`. Inside the toolbox (make shell):
#   bash infra/platform/tests/release.sh [commit]
# The commit defaults to the local HEAD. Each run ends with one row for
# docs/measurements/commit-to-production.md: minutes and seconds from the push to each step.
set -uo pipefail
cd "$(dirname "$0")/../../.." || exit

api=https://api.github.com/repos/EmmeOnWork/Cards_Warehouse
image=ghcr.io/emmeonwork/cards-warehouse
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

git() { command git -c safe.directory='*' "$@"; }
# Anonymous calls: 60 an hour. The test waits on the cluster, then asks GitHub once per fact.
github() { curl --silent --fail --show-error "$api/$1"; }
kube() { kubectl --context kind-cards-warehouse "$@"; }

# Without a cluster, the wait below would only end after ten minutes.
if ! kube get --raw /readyz >/dev/null 2>&1; then
  echo "FAIL  the test needs the platform up, but the cluster cards-warehouse does not answer: run make platform-up first"
  exit 1
fi

pushed=$(git rev-parse "${1:-HEAD}")

# The push that moved main to the commit, as GitHub recorded it: its time is when the clock starts.
push=$(github "activity?ref=refs/heads/main&activity_type=push&per_page=50" |
  jq --arg sha "$pushed" 'first(.[] | select(.after == $sha)) // empty') || exit 1
if [[ -z $push ]]; then
  echo "FAIL  no push moved main to $pushed on GitHub: push it first"
  exit 1
fi

# Pipeline, Argo CD polling and rollout: allow ten minutes.
cluster_runs_the_commit() {
  local version start=$SECONDS report=60
  while ((SECONDS - start < 600)); do
    version=$(curl --silent --max-time 5 http://host.docker.internal:8000/version)
    [[ $version == "{\"version\":\"$pushed\"}" ]] && { echo "      after $((SECONDS - start)) s of waiting"; return 0; }
    # A line a minute, so a long wait never looks like a hang.
    if ((SECONDS - start >= report)); then
      echo "      $((SECONDS - start)) s: the app reports ${version:-nothing}"
      report=$((report + 60))
    fi
    sleep 5
  done
  echo "      the app reports ${version:-nothing}, the push was $pushed"
  return 1
}

pipeline_succeeded() {
  local conclusion
  conclusion=$(jq -r .conclusion <<<"$run")
  [[ $conclusion == success ]] || { echo "      pipeline of $pushed: $conclusion"; return 1; }
}

production_points_at_the_commit() {
  local head
  head=$(github branches/production | jq -r .commit.sha)
  [[ $head == "$pushed" ]] || { echo "      production: $head"; return 1; }
}

echo "      waiting for the cluster to run $pushed"
check "the cluster runs the pushed commit" cluster_runs_the_commit
# The pipeline run of the push, read once the cluster runs the commit, so after the run has ended.
run=$(github "actions/runs?head_sha=$pushed&event=push" | jq '.workflow_runs[0]')
check "the pipeline of the pushed commit succeeded" pipeline_succeeded
check "production points at the pushed commit" production_points_at_the_commit

# --- Measurement: from the clocks of GitHub, Argo CD and Kubernetes ---

epoch() { [[ -n $1 && $1 != null ]] && date --date "$1" +%s; }
since_push() { # since_push <time>: m:ss after the push, or "-" when the time is unknown
  local t
  t=$(epoch "$1") || { echo -; return; }
  printf '%d:%02d' $(((t - start) / 60)) $(((t - start) % 60))
}

start=$(epoch "$(jq -r .timestamp <<<"$push")")
interval=$(kube --namespace argocd get configmap argocd-cm \
  -o jsonpath='{.data.timeout\.reconciliation} + {.data.timeout\.reconciliation\.jitter}')
jobs=$(github "actions/runs/$(jq -r .id <<<"$run")/jobs")
published=$(jq -r '.jobs[] | select(.name == "build, scan and publish") | .completed_at' <<<"$jobs")
moved=$(jq -r '.jobs[] | select(.name == "release to the cluster") | .completed_at' <<<"$jobs")
# When Argo CD finished applying the commit.
synced=$(kube --namespace argocd get application cards-warehouse -o json | jq -r --arg sha "$pushed" '
  [.status.history[]? | select(.revision == $sha) | .deployedAt] | last')
# When the first pod running that image became Ready: from then on, the cluster runs the version.
ready=$(kube --namespace cards-warehouse get pods -l app.kubernetes.io/name=cards-warehouse -o json | jq -r --arg image "$image:$pushed" '
  [.items[] | select(.spec.containers[0].image == $image) | .status.conditions[] |
   select(.type == "Ready" and .status == "True") | .lastTransitionTime] | sort | first')

echo "      | Date | Commit | Push (UTC) | Image published | Production moved | Argo CD sync | Pod Ready | Argo CD polling |"
echo "      | $(date --utc +%F) | \`${pushed:0:7}\` | $(date --utc --date "@$start" +%T) | $(since_push "$published") | $(since_push "$moved") | $(since_push "$synced") | **$(since_push "$ready")** | $interval |"

exit $((failures > 0))
