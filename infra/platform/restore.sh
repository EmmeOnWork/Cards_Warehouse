#!/usr/bin/env bash
# Restores the app's database from a Velero backup, on the platform up: on a new cluster, after a disaster.
# The photos need nothing: they never left their bucket. Run by make restore, inside the toolbox:
#   bash infra/platform/restore.sh [backup]
# With no backup named, the newest that completed. It needs only the cluster: no AWS session and no Infisical
# credential, since Velero reads the bucket with its own key, from Infisical. docs/restore.md explains each step.
set -uo pipefail

cluster=cards-warehouse
scratch=cards-warehouse-restore
database=(--username=cards_warehouse --dbname=cards_warehouse)
# Seconds for each wait: well over twice the time seen.
limit=300

kube() { kubectl --context "kind-$cluster" "$@"; }
velero() { command velero --kubecontext "kind-$cluster" "$@"; }
in_app() { kube --namespace cards-warehouse "$@"; }
in_velero() { kube --namespace velero "$@"; }
in_scratch() { kube --namespace "$scratch" "$@"; }
step() { printf '%d:%02d  %s\n' $((SECONDS / 60)) $((SECONDS % 60)) "$1"; }
fail() { echo "FAIL  $1"; exit 1; }
wait_for() { # wait_for "<what>" <command...>
  local until=$((SECONDS + limit))
  until "${@:2}"; do
    ((SECONDS < until)) || fail "$1, still not after $limit s"
    sleep 2
  done
}

completed_backups() { # name per line, the newest last
  in_velero get backups -o jsonpath='{range .items[?(@.status.phase=="Completed")]}{.status.completionTimestamp} {.metadata.name}{"\n"}{end}' |
    sort | cut -d ' ' -f 2
}

kube get --raw /readyz >/dev/null 2>&1 || fail "the cluster $cluster does not answer: run make platform-up first"

# On a new cluster Velero copies the backups of the bucket into the cluster one by one, in no order, as soon as it
# reaches the bucket. Only when it has gone through all of them does it write the time of that sync on the location.
# Before that, the newest listed may be days old: seen in the drill of 2026-10-27, which restored a backup of 25/10.
step "waiting for Velero to read the whole list of backups in the bucket"
synced() { [[ -n $(in_velero get backupstoragelocation default -o jsonpath='{.status.lastSyncedTime}' 2>/dev/null) ]]; }
wait_for "Velero has not read the bucket: kubectl -n velero get backupstoragelocation" synced
wanted=${1:-}
completed_backups | grep --quiet --line-regexp -- "${wanted:-.*}" ||
  fail "no completed backup${wanted:+ named $wanted} in the bucket: velero backup get"
backup=${wanted:-$(completed_backups | tail -n 1)}
step "restoring $backup, completed $(in_velero get backup "$backup" -o jsonpath='{.status.completionTimestamp}')"

# Velero gives a volume back only to a pod it creates itself, and on this cluster Argo CD has already created
# PostgreSQL. So Velero recreates that pod in a namespace of its own, which Argo CD does not know, with an empty
# disk and a password of its own: only its dump volume matters, the copy of the database the backup holds.
kube get namespace "$scratch" >/dev/null 2>&1 && kube delete namespace "$scratch" --wait=true >/dev/null
kube create namespace "$scratch" >/dev/null
in_scratch create secret generic cards-warehouse-secrets \
  --from-literal=PGPASSWORD="$(head -c 24 /dev/urandom | base64 | tr -d '/+=')" >/dev/null
in_scratch apply --filename - >/dev/null <<'YAML'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  # The name the pod of the backup asks for. Not restored from the backup: that one names a disk of the old cluster.
  name: data-cards-warehouse-postgres-0
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 1Gi
YAML
restore=restore-$(date --utc +%Y%m%d%H%M%S)
velero restore create "$restore" --from-backup "$backup" --include-resources pods \
  --selector app.kubernetes.io/name=postgres --namespace-mappings "cards-warehouse:$scratch" >/dev/null ||
  fail "Velero refused the restore"
# Not velero --wait: a pod that never starts keeps a restore waiting for hours, and Velero restores nothing else.
ended() { [[ $(in_velero get restore "$restore" -o jsonpath='{.status.phase}') =~ ^(Completed|PartiallyFailed|Failed)$ ]]; }
wait_for "the restore $restore has not ended: velero restore describe $restore" ended
phase=$(in_velero get restore "$restore" -o jsonpath='{.status.phase}')
[[ $phase == Completed ]] || fail "the restore $restore is $phase: velero restore logs $restore"
in_scratch wait --for=condition=Ready pod/cards-warehouse-postgres-0 --timeout="${limit}s" >/dev/null ||
  fail "the pod with the copy of the database does not start: kubectl -n $scratch describe pod"
step "the copy of the database is back, in the namespace $scratch"

# One transaction: the empty schema and the copy, or nothing, and the database stays as it was. Emptied first,
# so that a copy older than the app loads too: the migrations then bring it to the app's revision.
# The COMMIT goes last, only once the whole copy went through: a copy cut halfway ends the session with the
# transaction open, and PostgreSQL undoes it. (psql --single-transaction would commit whatever arrived.)
in_app wait --for=condition=Ready pod/cards-warehouse-postgres-0 --timeout="${limit}s" >/dev/null ||
  fail "PostgreSQL is not ready: kubectl -n cards-warehouse describe pod cards-warehouse-postgres-0"
{
  echo 'SET client_min_messages = warning; BEGIN; DROP SCHEMA public CASCADE; CREATE SCHEMA public;'
  in_scratch exec cards-warehouse-postgres-0 -c postgres -- pg_restore --no-owner --file=- /dump/cards_warehouse.dump &&
    echo 'COMMIT;'
} | in_app exec --stdin cards-warehouse-postgres-0 -c postgres -- \
  psql "${database[@]}" --set=ON_ERROR_STOP=1 --quiet --output=/dev/null ||
  fail "the copy did not load, and the database is as it was"
step "the copy is loaded into PostgreSQL"

# A new pod of the app: its init container migrates the database, and it opens new connections.
in_app rollout restart deployment/cards-warehouse >/dev/null
in_app rollout status deployment/cards-warehouse --timeout="${limit}s" >/dev/null ||
  fail "the app does not start again: kubectl -n cards-warehouse get pods"
step "the app runs on the restored data"

kube delete namespace "$scratch" --wait=false >/dev/null
step "done: $backup restored. The photos open as before: they never left their bucket"
