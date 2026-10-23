#!/usr/bin/env bash
# Measurement of the platform's recreation, run by hand: from no cluster, the one command, to the app
# answering healthy on the PC. Each cycle creates the platform, measures it and destroys it. Inside the
# toolbox (make shell), after `aws login --remote`:
#   bash infra/platform/tests/recreation.sh [cycles]
# Five cycles by default, about ten minutes each. Each cycle prints one row for
# docs/measurements/platform-recreation.md. A cycle whose app never gets healthy stops the run and leaves
# its cluster up, to look at it; then make platform-down.
set -uo pipefail
cd "$(dirname "$0")/.." || exit

cluster=cards-warehouse
cycles=${1:-5}
# Seconds from the start of a cycle: well over twice the time expected.
limit=900
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

# kind labels every node container with the name of its cluster.
cluster_nodes() {
  docker ps --all --quiet --filter "label=io.x-k8s.kind.cluster=$cluster"
}

kube() { kubectl --context "kind-$cluster" "$@"; }
mmss() { printf '%d:%02d' $(($1 / 60)) $(($1 % 60)); }

if [[ -z ${TF_VAR_infisical_client_id:-} || -z ${TF_VAR_infisical_client_secret:-} ]]; then
  echo "FAIL  the Infisical credential is missing: put it in ~/.cards-warehouse/platform.env, see README.md"
  exit 1
fi
log=$(mktemp)
trap 'rm -f "$log"' EXIT

# Docker Desktop runs the cluster inside its WSL machine, with the CPUs and the memory it gives it.
docker info --format '{{.ServerVersion}} {{.NCPU}} {{.MemTotal}}' |
  awk '{printf "      Docker Desktop %s: %d CPUs, %.1f GiB of memory\n", $1, $2, $3 / 2^30}'

# What the app was waiting for, with the signs of the two problems of the Infisical operator seen on
# 2026-10-21: its Application left on a failed sync, and its connection left with no status.
diagnose() {
  local app
  for app in infisical-operator cards-warehouse; do
    echo "      $app: $(kube --namespace argocd get application "$app" -o jsonpath='{.status.sync.status} {.status.health.status}, last sync {.status.operationState.phase}: {.status.operationState.message}' 2>&1)"
  done
  echo "      InfisicalConnection default, status: $(kube --namespace infisical get infisicalconnection default -o jsonpath='{.status}' 2>&1)"
  kube --namespace infisical logs deployment/infisical-opera-controller-manager 2>/dev/null |
    grep -m 1 'the object has been modified' | cut -c1-200 | sed 's/^/      operator log: /'
  # Every pod with a container not ready, and why: ImagePullBackOff, CreateContainerConfigError, Pending...
  kube get pods --all-namespaces --no-headers |
    awk '{split($3, ready, "/")} ready[1] != ready[2] && $4 != "Completed" {print "      pod " $1 "/" $2 ": " $4}'
}

# The same commands as make platform-up, then the PC's port 8000 asked every second. /readyz answers 200
# only once the app reaches PostgreSQL, and the Service sends traffic only to a Ready pod.
one_command_brings_the_app_healthy() {
  local applied healthy version
  SECONDS=0
  if ! { terraform init -input=false && terraform apply -auto-approve -input=false -no-color; } >"$log" 2>&1; then
    tail -n 20 "$log"
    return 1
  fi
  applied=$SECONDS
  echo "      terraform apply done after $(mmss "$applied")"
  until curl --silent --fail --max-time 2 http://host.docker.internal:8000/readyz >/dev/null; do
    if ((SECONDS >= limit)); then
      echo "      the app is not healthy after $(mmss "$limit")"
      diagnose
      return 1
    fi
    sleep 1
  done
  healthy=$SECONDS
  version=$(curl --silent --max-time 5 http://host.docker.internal:8000/version | jq -r .version)
  row="| $day | $start | \`${version:0:7}\` | $(mmss "$applied") | **$(mmss "$healthy")** |"
  echo "      $row"
}

destroy_leaves_no_node() {
  terraform destroy -auto-approve -input=false -no-color >"$log" 2>&1 || { tail -n 20 "$log"; return 1; }
  [[ -z $(cluster_nodes) ]] || { echo "      a node is left"; return 1; }
}

rows=()
for ((cycle = 1; cycle <= cycles; cycle++)); do
  if [[ -n $(cluster_nodes) ]]; then
    echo "FAIL  each cycle starts from no cluster, but $cluster exists: run make platform-down first"
    exit 1
  fi
  echo "      cycle $cycle of $cycles"
  day=$(date --utc +%F)
  start=$(date --utc +%T)
  check "from no cluster, the one command brings the app healthy, with no step by hand" \
    one_command_brings_the_app_healthy
  ((failures == 0)) || { echo "      the cluster stays as it is: inspect it, then make platform-down"; break; }
  rows+=("$row")
  check "terraform destroy leaves no node of the cluster" destroy_leaves_no_node
  ((failures == 0)) || break
done

if ((${#rows[@]})); then
  echo "      | Date | Start (UTC) | Production | Terraform apply | App healthy |"
  printf '      %s\n' "${rows[@]}"
fi

exit $((failures > 0))
