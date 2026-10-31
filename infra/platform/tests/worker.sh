#!/usr/bin/env bash
# Acceptance test of the worker, run by hand with the platform up, after the push that brought it. It checks that
# Argo CD installed it from the chart, beside the app and from the same image, and that it runs: up, never restarted,
# reaching the database. Inside the toolbox (make shell):
#   bash infra/platform/tests/worker.sh
set -uo pipefail

worker=cards-warehouse-worker
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

kube() { kubectl --context kind-cards-warehouse "$@"; }
in_app() { kube --namespace cards-warehouse "$@"; }

if ! kube get --raw /readyz >/dev/null 2>&1; then
  echo "FAIL  the test needs the platform up, but the cluster cards-warehouse does not answer: run make platform-up first"
  exit 1
fi

# Argo CD lists among the resources of the app's Application those it installed from the chart.
worker_is_installed_by_argocd() {
  local status installed
  status=$(kube --namespace argocd get application cards-warehouse \
    -o jsonpath='{.status.sync.status} {.status.health.status}' 2>/dev/null)
  installed=$(kube --namespace argocd get application cards-warehouse \
    -o jsonpath='{.status.resources[?(@.kind=="Deployment")].name}' 2>/dev/null)
  [[ $status == "Synced Healthy" && " $installed " == *" $worker "* ]] || {
    echo "      cards-warehouse: ${status:-no application}; Deployments installed: ${installed:-none}"
    return 1
  }
}

# The commit Argo CD runs, in the app and in the worker alike.
worker_runs_the_image_of_the_app() {
  local app runs
  app=$(in_app get deployment cards-warehouse -o jsonpath='{.spec.template.spec.containers[?(@.name=="app")].image}')
  runs=$(in_app get deployment "$worker" -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null)
  [[ -n $app && $runs == "$app" ]] || { echo "      app: ${app:-none}; worker: ${runs:-none}"; return 1; }
}

# A component of its own: no Service sends it traffic, and it is not one of the app's pods.
worker_is_a_component_of_its_own() {
  local pods
  pods=$(in_app get pods --selector app.kubernetes.io/name=cards-warehouse -o name 2>/dev/null)
  ! grep -q "$worker" <<<"$pods" || { echo "      the app's Service selects the worker: $pods"; return 1; }
}

# Up, with no restart since it started: a worker that cannot reach the database stops, and Kubernetes restarts it.
worker_runs_without_restarts() {
  local phase restarts
  phase=$(in_app get pods --selector app.kubernetes.io/name=worker -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
  restarts=$(in_app get pods --selector app.kubernetes.io/name=worker \
    -o jsonpath='{.items[0].status.containerStatuses[0].restartCount}' 2>/dev/null)
  [[ $phase == Running && $restarts == 0 ]] || { echo "      phase ${phase:-none}, restarts ${restarts:-none}"; return 1; }
}

# The line it logs at start, and a round of its own run by hand in its pod, on the app's database.
worker_reaches_the_database() {
  local logged round
  logged=$(in_app logs "deploy/$worker" 2>/dev/null | head -n 1)
  round=$(in_app exec "deploy/$worker" -- python -c '
from datetime import UTC, datetime
from cards_warehouse import channel_queue
from cards_warehouse.database import create_database_engine
with create_database_engine().connect() as connection:
    print(len(channel_queue.pending(connection)), "waiting")' 2>&1)
  [[ $logged == "The worker looks for operations to ask again every"* && $round =~ ^[0-9]+\ waiting$ ]] || {
    echo "      logged at start: ${logged:-nothing}"
    echo "      a round by hand: $round"
    return 1
  }
}

check "the worker is installed by Argo CD" worker_is_installed_by_argocd
check "it runs the image of the app" worker_runs_the_image_of_the_app
check "it is a component of its own, apart from the app's pods" worker_is_a_component_of_its_own
check "it runs, with no restart" worker_runs_without_restarts
check "it reaches the database" worker_reaches_the_database

exit $((failures > 0))
