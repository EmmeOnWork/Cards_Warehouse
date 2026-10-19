#!/usr/bin/env bash
# Acceptance test of a release, run by hand with the platform up, right after a push on main.
# Inside the toolbox (make shell):
#   bash infra/platform/tests/release.sh [commit]   # after pushing a commit that changes app/
#   bash infra/platform/tests/release.sh rollback   # after `git revert` of the bot's release commit, pushed
# The commit defaults to the local HEAD. Each run ends with one row for
# docs/measurements/commit-to-production.md: seconds from the push to each step.
set -uo pipefail
cd "$(dirname "$0")/../../.." || exit

api=https://api.github.com/repos/EmmeOnWork/Cards_Warehouse
manifest=gitops/apps/cards-warehouse.yaml
image=ghcr.io/emmeonwork/cards-warehouse
bot='github-actions[bot]'
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

if [[ ${1:-} == rollback ]]; then
  scenario=rollback
  pushed=$(git rev-parse HEAD)
  # The version Git asks for after the revert: the tag the bot's commit had replaced.
  expected=$(git show "$pushed:$manifest" | sed -n 's/^ *tag: *//p')
else
  scenario=release
  pushed=$(git rev-parse "${1:-HEAD}")
  expected=$pushed
fi

# The push that moved main to the commit, as GitHub recorded it: its time is when the clock starts.
activity=$(github "activity?ref=refs/heads/main&activity_type=push&per_page=50") || exit 1
push() { # push <commit>: the push that moved main to <commit>, as JSON
  jq --arg sha "$1" 'first(.[] | select(.after == $sha)) // empty' <<<"$activity"
}
if [[ -z $(push "$pushed") ]]; then
  echo "FAIL  no push moved main to $pushed on GitHub: push it first"
  exit 1
fi
if [[ $scenario == release ]] && git diff --quiet "$(push "$pushed" | jq -r .before)" "$pushed" -- app/; then
  echo "FAIL  the push of $pushed changes nothing in app/, so it releases nothing: push an app change"
  exit 1
fi

# Pipeline, release commit, Argo CD polling and rollout: allow ten minutes.
cluster_runs_the_version() {
  local version start=$SECONDS report=60
  while ((SECONDS - start < 600)); do
    version=$(curl --silent --max-time 5 http://host.docker.internal:8000/version)
    [[ $version == "{\"version\":\"$expected\"}" ]] && { echo "      after $((SECONDS - start)) s of waiting"; return 0; }
    # A line a minute, so a long wait never looks like a hang.
    if ((SECONDS - start >= report)); then
      echo "      $((SECONDS - start)) s: the app reports ${version:-nothing}"
      report=$((report + 60))
    fi
    sleep 5
  done
  echo "      the app reports ${version:-nothing}, Git asks for $expected"
  return 1
}

# The latest commit on main that changed the app's Application.
last_manifest_commit=
read_last_manifest_commit() {
  last_manifest_commit=$(github "commits?sha=main&path=$manifest&per_page=1" | jq '.[0]')
}

pipeline_of() { # pipeline_of <commit>: the pipeline runs started by a push of <commit>, as JSON
  github "actions/runs?head_sha=$1&event=push"
}

pipeline_succeeded() {
  local conclusion
  conclusion=$(pipeline_of "$pushed" | jq -r '.workflow_runs[0].conclusion')
  [[ $conclusion == success ]] || { echo "      pipeline of $pushed: $conclusion"; return 1; }
}

release_commit_is_by_the_bot() {
  local authors
  authors=$(jq -r '"\(.author.login) \(.committer.login)"' <<<"$last_manifest_commit")
  [[ $authors == "$bot $bot" ]] || { echo "      author and committer: $authors"; return 1; }
}

release_commit_changes_only_the_tag() {
  local sha files
  sha=$(jq -r .sha <<<"$last_manifest_commit")
  files=$(github "commits/$sha" | jq -c '[.files[] | {filename, additions, deletions, patch}]')
  jq -e --arg file "$manifest" --arg tag "$pushed" '
    length == 1 and .[0].filename == $file and .[0].additions == 1 and .[0].deletions == 1 and
    (.[0].patch | test("\n\\+ *tag: " + $tag + "\n"))' <<<"$files" >/dev/null || {
    echo "      $sha changes: $files"
    return 1
  }
}

# The release commit is pushed with the run's token, which GitHub never lets start a workflow.
release_commit_starts_no_pipeline() {
  local sha runs
  sha=$(jq -r .sha <<<"$last_manifest_commit")
  runs=$(github "actions/runs?head_sha=$sha" | jq .total_count)
  [[ $runs == 0 ]] || { echo "      $runs pipeline runs for $sha"; return 1; }
}

# The revert changes nothing in app/: its pipeline runs the checks and leaves the tag alone.
revert_releases_nothing() {
  local status start=$SECONDS
  while ((SECONDS - start < 600)); do
    status=$(pipeline_of "$pushed" | jq -r '.workflow_runs[0] | "\(.status) \(.conclusion)"')
    [[ $status == completed* ]] && break
    sleep 30
  done
  read_last_manifest_commit
  [[ $status == "completed success" && $(jq -r .sha <<<"$last_manifest_commit") == "$pushed" ]] || {
    echo "      pipeline of $pushed: $status; last change to $manifest: $(jq -r .sha <<<"$last_manifest_commit")"
    return 1
  }
}

echo "      waiting for the cluster to run $expected ($scenario of $pushed)"
check "the cluster runs the version Git asks for" cluster_runs_the_version
if [[ $scenario == release ]]; then
  read_last_manifest_commit
  check "the pipeline of the pushed commit succeeded" pipeline_succeeded
  check "the release commit on main is by $bot" release_commit_is_by_the_bot
  check "the release commit changes only image.tag, to the pushed commit" release_commit_changes_only_the_tag
  check "the release commit starts no pipeline" release_commit_starts_no_pipeline
else
  check "the revert starts no release" revert_releases_nothing
fi

# --- Measurement: seconds from the push, from the clocks of GitHub, Argo CD and Kubernetes ---

epoch() { [[ -n $1 && $1 != null ]] && date --date "$1" +%s; }
since_push() { # since_push <time>: m:ss after the push, or "-" when the time is unknown
  local t
  t=$(epoch "$1") || { echo -; return; }
  printf '%d:%02d' $(((t - start) / 60)) $(((t - start) % 60))
}

start=$(epoch "$(push "$pushed" | jq -r .timestamp)")
interval=$(kube --namespace argocd get configmap argocd-cm \
  -o jsonpath='{.data.timeout\.reconciliation} + {.data.timeout\.reconciliation\.jitter}')
# When Argo CD finished applying the Application that asks for the version.
synced=$(kube --namespace argocd get application cards-warehouse -o json | jq -r --arg tag "$expected" '
  [.status.history[]? | select(.source.helm.valuesObject.image.tag == $tag) | .deployedAt] | last')
# When the first pod running that image became Ready: from then on, the cluster runs the version.
ready=$(kube --namespace cards-warehouse get pods -l app.kubernetes.io/name=cards-warehouse -o json | jq -r --arg image "$image:$expected" '
  [.items[] | select(.spec.containers[0].image == $image) | .status.conditions[] |
   select(.type == "Ready" and .status == "True") | .lastTransitionTime] | sort | first')

if [[ $scenario == release ]]; then
  run=$(pipeline_of "$pushed" | jq -r '.workflow_runs[0].id')
  published=$(github "actions/runs/$run/jobs" | jq -r '.jobs[] | select(.name == "build, scan and publish") | .completed_at')
  # The bot's push, or the commit's own time when GitHub lists no push for it.
  activity=$(github "activity?ref=refs/heads/main&activity_type=push&per_page=50")
  release_sha=$(jq -r .sha <<<"$last_manifest_commit")
  released=$(push "$release_sha" | jq -r '.timestamp // empty')
  released=${released:-$(jq -r .commit.committer.date <<<"$last_manifest_commit")}
  echo "      | Date | Commit | Push (UTC) | Image published | Release commit | Argo CD sync | Pod Ready | Argo CD polling |"
  echo "      | $(date --utc +%F) | \`${pushed:0:7}\` | $(date --utc --date "@$start" +%T) | $(since_push "$published") | $(since_push "$released") | $(since_push "$synced") | **$(since_push "$ready")** | $interval |"
else
  echo "      | Date | Revert | Push (UTC) | Argo CD sync | Pod Ready | Argo CD polling |"
  echo "      | $(date --utc +%F) | \`${pushed:0:7}\` | $(date --utc --date "@$start" +%T) | $(since_push "$synced") | **$(since_push "$ready")** | $interval |"
fi

exit $((failures > 0))
