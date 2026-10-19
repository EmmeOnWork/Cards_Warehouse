#!/usr/bin/env bash
# Rotation drill, run by hand on a running platform. Inside the toolbox (make shell):
#   bash infra/platform/tests/rotation.sh
# You change SESSION_SECRET in Infisical; the drill measures how long the new value takes to reach
# the cluster, then the app, which reads it only at start. Values are never printed, only fingerprints.
set -uo pipefail

app() { # app <kubectl arguments...>: kubectl in the app's namespace
  kubectl --context kind-cards-warehouse --namespace cards-warehouse "$@"
}

# What the app reports: the first 16 hex digits of the SHA-256 of the key.
fingerprint_in_cluster() {
  app get secret cards-warehouse-secrets -o jsonpath='{.data.SESSION_SECRET}' | base64 -d | sha256sum | cut -c1-16
}

fingerprint_in_app() {
  curl --silent --fail --max-time 5 http://host.docker.internal:8000/session-key |
    sed -n 's/.*"fingerprint":"\([0-9a-f]*\)".*/\1/p'
}

before=$(fingerprint_in_app)
if [[ -z $before || $before != "$(fingerprint_in_cluster)" ]]; then
  echo "FAIL  the app must first run with the key in the cluster: app ${before:-unreachable}"
  exit 1
fi
echo "The app runs with key $before."
echo "In Infisical, project cards-warehouse, environment prod, folder /app: give SESSION_SECRET a new value,"
echo "for example the output of: head -c 32 /dev/urandom | base64"
read -rp "Save it, then press Enter: "

SECONDS=0
reached_cluster=""
while ((SECONDS < 600)); do
  in_cluster=$(fingerprint_in_cluster)
  if [[ -z $reached_cluster && $in_cluster != "$before" ]]; then
    reached_cluster=$SECONDS
    echo "after ${SECONDS} s  the new value is in the cluster"
  fi
  in_app=$(fingerprint_in_app)
  if [[ -n $reached_cluster && $in_app == "$in_cluster" ]]; then
    echo "after ${SECONDS} s  the restarted app runs with the new key $in_app"
    echo "PASS  a value changed in Infisical reaches the cluster, and the app uses it after the restart"
    exit 0
  fi
  sleep 1
done
echo "FAIL  after 10 minutes: cluster ${in_cluster:-unreadable}, app ${in_app:-unreachable}, before $before"
exit 1
