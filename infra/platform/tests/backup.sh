#!/usr/bin/env bash
# Acceptance test of the backups, run by hand with the platform up. It starts a backup like the daily one,
# waits for it, and checks what it holds and where it went. Inside the toolbox (make shell), after `aws login --remote`:
#   bash infra/platform/tests/backup.sh
set -uo pipefail

bucket=emmeonwork-cards-warehouse-backups
schedule=velero-daily
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

kube() { kubectl --context kind-cards-warehouse "$@"; }
velero() { command velero --kubecontext kind-cards-warehouse "$@"; }
in_velero() { kube --namespace velero "$@"; }
in_app() { kube --namespace cards-warehouse "$@"; }
epoch() { date --date "$1" +%s; }

if ! kube get --raw /readyz >/dev/null 2>&1; then
  echo "FAIL  the test needs the platform up, but the cluster cards-warehouse does not answer: run make platform-up first"
  exit 1
fi

velero_is_installed_by_argocd() {
  local status
  status=$(kube --namespace argocd get application velero -o jsonpath='{.status.sync.status} {.status.health.status}' 2>/dev/null)
  [[ $status == "Synced Healthy" ]] || { echo "      velero: ${status:-no application}"; return 1; }
}

# Available: Velero reached the bucket with the credential the Infisical operator copied into the cluster.
backup_location_is_available_with_the_credential_from_infisical() {
  local phase owner
  phase=$(in_velero get backupstoragelocation default -o jsonpath='{.status.phase}' 2>/dev/null)
  owner=$(in_velero get secret velero-credentials -o jsonpath='{.metadata.ownerReferences[0].kind}' 2>/dev/null)
  [[ $phase == Available && $owner == InfisicalStaticSecret ]] || {
    echo "      backup location: ${phase:-none}; credential owned by: ${owner:-nobody}"
    return 1
  }
}

# Every day: the last three fields of the cron expression, day of month, month and day of week, are all "*".
schedule_runs_every_day() {
  local cron phase
  cron=$(in_velero get schedule "$schedule" -o jsonpath='{.spec.schedule}' 2>/dev/null)
  phase=$(in_velero get schedule "$schedule" -o jsonpath='{.status.phase}' 2>/dev/null)
  [[ $phase == Enabled && $cron =~ ^[0-9]+\ [0-9]+\ \*\ \*\ \*$ ]] || {
    echo "      schedule $schedule: ${phase:-missing}, cron '${cron}'"
    return 1
  }
}

# The same backup the schedule makes, started now instead of at its hour.
backup=$schedule-by-hand-$(date --utc +%Y%m%d%H%M%S)
backup_started_by_hand_completes() {
  local phase
  velero backup create "$backup" --from-schedule "$schedule" --wait >/dev/null 2>&1
  phase=$(in_velero get backup "$backup" -o jsonpath='{.status.phase}' 2>/dev/null)
  [[ $phase == Completed ]] || { echo "      $backup: ${phase:-not created}"; return 1; }
}

files_are_in_the_bucket() { # files_are_in_the_bucket <backup>
  local keys
  keys=$(aws s3api list-objects-v2 --bucket "$bucket" --prefix "backups/$1/" --query 'Contents[].Key' --output text)
  [[ $keys == *"backups/$1/velero-backup.json"* && $keys == *"backups/$1/$1.tar.gz"* ]] || {
    echo "      in s3://$bucket/backups/$1/: ${keys:-nothing}"
    return 1
  }
}

# Velero deletes a backup, from the cluster and from the bucket, once its expiration has passed.
backup_expires_after_30_days() {
  local created expiration days
  created=$(in_velero get backup "$backup" -o jsonpath='{.metadata.creationTimestamp}')
  expiration=$(in_velero get backup "$backup" -o jsonpath='{.status.expiration}')
  [[ -n $created && -n $expiration ]] || { echo "      no expiration"; return 1; }
  days=$((($(epoch "$expiration") - $(epoch "$created") + 60) / 86400))
  [[ $days -eq 30 ]] || { echo "      expires after $days days"; return 1; }
}

# Before copying the dump volume, Velero ran the hook: pg_dump wrote a copy of the database during this backup,
# and it holds the revision of the migrations the database is at.
backup_holds_a_consistent_copy_of_the_database() {
  local volumes started written revision copied
  volumes=$(in_velero get podvolumebackups -l "velero.io/backup-name=$backup" \
    -o jsonpath='{range .items[*]}{.spec.pod.name}/{.spec.volume}={.status.phase} {end}')
  started=$(in_velero get backup "$backup" -o jsonpath='{.status.startTimestamp}')
  written=$(in_app exec cards-warehouse-postgres-0 -c postgres -- stat --format=%Y /dump/cards_warehouse.dump 2>/dev/null)
  revision=$(in_app exec cards-warehouse-postgres-0 -c postgres -- psql --username cards_warehouse \
    --dbname cards_warehouse --tuples-only --no-align --command 'SELECT version_num FROM alembic_version')
  copied=$(in_app exec cards-warehouse-postgres-0 -c postgres -- pg_restore --data-only --table=alembic_version \
    --file=- /dump/cards_warehouse.dump 2>/dev/null)
  [[ $volumes == "cards-warehouse-postgres-0/dump=Completed " && -n $started && ${written:-0} -ge $(epoch "$started") &&
    -n $revision && $'\n'$copied$'\n' == *$'\n'$revision$'\n'* ]] || {
    echo "      volumes copied: ${volumes:-none}; dump written at ${written:-never}, backup started at $started;" \
      "revision in the database: ${revision:-unreadable}, in the copy: $(grep -c . <<<"$copied") lines"
    return 1
  }
}

# The Secrets come from Infisical: a copy in the bucket would be one more place to guard.
backup_holds_no_secret() {
  local details
  details=$(velero backup describe "$backup" --details 2>&1)
  [[ $details == *"v1/Pod:"* && $details != *"v1/Secret:"* ]] || {
    echo "      resources of the backup:"
    sed -n '/Resource List:/,/^$/p' <<<"$details"
    return 1
  }
}

# The line the home page shows, printed by the app inside its own pod, with its own permissions.
app_shows_the_backup() {
  local completed expected shown
  completed=$(in_velero get backup "$backup" -o jsonpath='{.status.completionTimestamp}')
  expected="Ultimo backup: $(TZ=Europe/Rome date --date "$completed" '+%d/%m alle %H:%M'), riuscito."
  shown=$(in_app exec deploy/cards-warehouse -c app -- python -m cards_warehouse.backups 2>&1)
  [[ $shown == "$expected" ]] || { echo "      expected: $expected"; echo "      the app: $shown"; return 1; }
}

# The schedule names each backup after itself and the time it started it. Before the first scheduled hour
# after the platform was created, there is none yet: run the test again the next day.
scheduled_backup=""
schedule_ran_in_the_last_day() {
  local last phase
  last=$(in_velero get schedule "$schedule" -o jsonpath='{.status.lastBackup}' 2>/dev/null)
  [[ -n $last ]] || { echo "      the schedule has not run yet"; return 1; }
  scheduled_backup=$schedule-$(date --utc --date "$last" +%Y%m%d%H%M%S)
  phase=$(in_velero get backup "$scheduled_backup" -o jsonpath='{.status.phase}' 2>/dev/null)
  (($(date +%s) - $(epoch "$last") <= 86400)) && [[ $phase == Completed ]] || {
    echo "      last scheduled backup: $scheduled_backup, ${phase:-missing}"
    return 1
  }
}

check "Velero is installed by Argo CD" velero_is_installed_by_argocd
check "Velero reaches the backups bucket with the credential from Infisical" \
  backup_location_is_available_with_the_credential_from_infisical
check "the schedule runs every day" schedule_runs_every_day
check "a backup started by hand completes" backup_started_by_hand_completes
check "its files are in the backups bucket" files_are_in_the_bucket "$backup"
check "it expires after 30 days" backup_expires_after_30_days
check "it holds a consistent copy of the database, made by the hook during the backup" \
  backup_holds_a_consistent_copy_of_the_database
check "it holds no Secret" backup_holds_no_secret
check "the app shows its time and outcome" app_shows_the_backup
check "the schedule ran a backup in the last 24 hours, and it completed" schedule_ran_in_the_last_day
[[ -n $scheduled_backup ]] && check "its files are in the backups bucket" files_are_in_the_bucket "$scheduled_backup"

exit $((failures > 0))
