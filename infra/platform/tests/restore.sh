#!/usr/bin/env bash
# The restore drill, measured, run by hand with the platform up. Each cycle adds a photo to the control item
# "Controllo del ripristino" through the app, backs up, destroys the platform, creates it again with the one
# command, and restores the backup with make restore. It measures from the start of the restore until the app
# shows that photo and the photo opens. Inside the toolbox (make shell), after `aws login --remote`:
#   bash infra/platform/tests/restore.sh [cycles]
# Three cycles by default. Each cycle prints one row for docs/measurements/restore.md. A cycle that fails stops
# the run and leaves its cluster up, to look at it.
set -uo pipefail
cd "$(dirname "$0")/.." || exit

cluster=cards-warehouse
schedule=velero-daily
app=http://host.docker.internal:8000
control="Controllo del ripristino"
cycles=${1:-3}
# Seconds from the start of a step: well over twice the time expected.
limit=900
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

kube() { kubectl --context "kind-$cluster" "$@"; }
velero() { command velero --kubecontext "kind-$cluster" "$@"; }
in_app() { kube --namespace cards-warehouse "$@"; }
in_velero() { kube --namespace velero "$@"; }
cluster_nodes() { docker ps --all --quiet --filter "label=io.x-k8s.kind.cluster=$cluster"; }
mmss() { printf '%d:%02d' $(($1 / 60)) $(($1 % 60)); }

if [[ -z ${TF_VAR_infisical_client_id:-} || -z ${TF_VAR_infisical_client_secret:-} ]]; then
  echo "FAIL  the Infisical credential is missing: put it in ~/.cards-warehouse/platform.env, see README.md"
  exit 1
fi
# The drill destroys the platform: never without the command that brings the data back.
if [[ ! -f restore.sh ]]; then
  echo "FAIL  the restore command is missing: infra/platform/restore.sh, which make restore runs"
  exit 1
fi
if ! curl --silent --fail --max-time 5 "$app/readyz" >/dev/null; then
  echo "FAIL  the drill starts from the platform up, but the app does not answer: run make platform-up first"
  exit 1
fi
log=$(mktemp)
photo=$(mktemp --suffix=.svg)
trap 'rm -f "$log" "$photo"' EXIT

# A session cookie signed with the app's own key, as the login gives: the drill needs no password. The key comes
# from Infisical, the same on every new cluster, so the cookie still opens the restored app.
cookie=$(in_app exec deploy/cards-warehouse -c app -- python -c '
import base64, json, os
from itsdangerous import TimestampSigner
session = base64.b64encode(json.dumps({"signed_in": True}).encode())
print(TimestampSigner(os.environ["SESSION_SECRET"]).sign(session).decode())')
signed_in() { curl --silent --show-error --fail --max-time 30 --cookie "session=$cookie" "$@"; }

# One control item for every run, loaded by the first: the inventory gains one item, not one per cycle.
control_item() {
  local id
  id=$(signed_in "$app/items" | grep --only-matching --perl-regexp "href=\"/items/\K[0-9]+(?=\">$control</a>)" | head -1)
  if [[ -z $id ]]; then
    id=$(signed_in --output /dev/null --write-out '%{redirect_url}' \
      --data kind=magazine --data-urlencode "name=$control" --data language=it --data quantity=1 \
      --data unknown_cost=true --data-urlencode "notes=La prova di ripristino (infra/platform/tests/restore.sh) aggiunge qui una foto a ogni ciclo." \
      "$app/items")
    id=${id##*/items/}
  fi
  [[ $id =~ ^[0-9]+$ ]] && echo "$id"
}

# This cycle's photo, unique to it: what it shows is the time it was taken.
photo_is_added_to_the_control_item() {
  printf '<svg xmlns="http://www.w3.org/2000/svg" width="720" height="120"><text x="20" y="70" font-size="32">Prova di ripristino, %s UTC</text></svg>\n' \
    "$(date --utc '+%F %T')" >"$photo"
  signed_in --output /dev/null --form "photos=@$photo;type=image/svg+xml" "$app/items/$item/photos" &&
    photo_opens
}

# As the browser does it: the item's page, then each photo from its signed link, straight from S3.
photo_opens() {
  local page link
  page=$(signed_in "$app/items/$item" 2>/dev/null) || return 1
  for link in $(grep --only-matching --perl-regexp '<img src="\K[^"]+' <<<"$page" | sed 's/&amp;/\&/g'); do
    [[ $(curl --silent --fail --max-time 10 "$link" | md5sum) == "$(md5sum <"$photo")" ]] && return 0
  done
  return 1
}

# Every table of the app, each with its rows counted and hashed in order: the same before the backup and after
# the restore means the same data. A table added later, such as the sales, is covered with no change here.
fingerprint() {
  in_app exec --stdin cards-warehouse-postgres-0 -c postgres -- \
    psql --username cards_warehouse --dbname cards_warehouse --tuples-only --no-align --quiet <<'SQL'
SELECT format('SELECT %L, count(*), md5(coalesce(string_agg(t::text, %L ORDER BY t::text), %L)) FROM %I t',
              tablename, E'\n', '', tablename)
FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
\gexec
SQL
}

backup_completes() {
  local phase
  backup=$schedule-drill-$(date --utc +%Y%m%d%H%M%S)
  velero backup create "$backup" --from-schedule "$schedule" --wait >"$log" 2>&1
  phase=$(in_velero get backup "$backup" -o jsonpath='{.status.phase}' 2>/dev/null)
  [[ $phase == Completed ]] || { echo "      $backup: ${phase:-not created}"; tail -n 5 "$log"; return 1; }
}

destroy_leaves_no_node() {
  terraform destroy -auto-approve -input=false -no-color >"$log" 2>&1 || { tail -n 20 "$log"; return 1; }
  [[ -z $(cluster_nodes) ]] || { echo "      a node is left"; return 1; }
}

# The same commands as make platform-up, until the app answers healthy: with an empty database.
one_command_brings_the_app_healthy() {
  SECONDS=0
  if ! { terraform init -input=false && terraform apply -auto-approve -input=false -no-color; } >"$log" 2>&1; then
    tail -n 20 "$log"
    return 1
  fi
  until curl --silent --fail --max-time 2 "$app/readyz" >/dev/null; do
    ((SECONDS < limit)) || { echo "      the app is not healthy after $(mmss "$limit")"; return 1; }
    sleep 1
  done
  echo "      platform created and healthy after $(mmss "$SECONDS")"
}

# The measure: from make restore on the new cluster to the photo of this cycle opening from the item's page.
# With an empty environment, so no AWS session and no Infisical credential: only the cluster's own.
restore_brings_back_the_data_and_the_photos() {
  local finished shown
  day=$(date --utc +%F)
  start=$(date --utc +%T)
  SECONDS=0
  if ! env -i PATH="$PATH" HOME="$HOME" AWS_CONFIG_FILE=/dev/null AWS_SHARED_CREDENTIALS_FILE=/dev/null \
    bash restore.sh >"$log" 2>&1; then
    tail -n 20 "$log"
    return 1
  fi
  finished=$SECONDS
  # Its steps, each with the time since it started: where the time goes.
  sed 's/^/      /' "$log"
  # Once the restore is done, a photo that does not open within two minutes will not open: the data is wrong.
  until photo_opens; do
    ((SECONDS < finished + 120)) || { echo "      the photo of this cycle does not open 2 minutes after the restore"; return 1; }
    sleep 1
  done
  shown=$SECONDS
  # Retried: the old pod of the app may be leaving just now, as on 2026-10-27, when one row lost its commit.
  version=$(curl --silent --fail --max-time 5 --retry 5 --retry-all-errors "$app/version" | jq -r .version)
  row="| $day | $start | \`${version:0:7}\` | \`$backup\` | $(mmss "$finished") | **$(mmss "$shown")** |"
  echo "      $row"
}

restore_takes_the_newest_backup() {
  local taken
  taken=$(in_velero get restores --sort-by=.metadata.creationTimestamp -o jsonpath='{.items[-1:].spec.backupName}')
  [[ $taken == "$backup" ]] || { echo "      restored from: ${taken:-nothing}, the newest is $backup"; return 1; }
}

every_table_is_as_before_the_backup() {
  local after
  after=$(fingerprint)
  [[ -n $before && $after == "$before" ]] || {
    echo "      tables that differ, before and after:"
    diff <(echo "$before") <(echo "$after") | grep '^[<>]' | sed 's/^/      /'
    return 1
  }
}

# Deleted at the end of the restore, without waiting: the namespace goes once its pod has stopped.
no_namespace_is_left_behind() {
  kube wait --for=delete namespace/cards-warehouse-restore --timeout=120s >/dev/null 2>&1 ||
    { echo "      cards-warehouse-restore is still there"; return 1; }
}

rows=()
for ((cycle = 1; cycle <= cycles; cycle++)); do
  echo "      cycle $cycle of $cycles"
  item=$(control_item)
  check "the control item is in the app" test -n "$item"
  ((failures == 0)) || break
  check "a new photo of the control item opens from its page" photo_is_added_to_the_control_item
  ((failures == 0)) || break
  before=$(fingerprint)
  check "a backup started by hand completes" backup_completes
  ((failures == 0)) || break
  check "terraform destroy leaves no node of the cluster" destroy_leaves_no_node
  ((failures == 0)) || break
  check "from no cluster, the one command brings the app healthy, empty" one_command_brings_the_app_healthy
  ((failures == 0)) || break
  check "make restore, with no secret, brings back the data and the photo of this cycle" \
    restore_brings_back_the_data_and_the_photos
  ((failures == 0)) || { echo "      the cluster stays as it is: inspect it, then make platform-down"; break; }
  rows+=("$row")
  check "the restore took the newest backup, the one just made" restore_takes_the_newest_backup
  check "every table holds the same rows as before the backup" every_table_is_as_before_the_backup
  check "the restore leaves no namespace behind" no_namespace_is_left_behind
  ((failures == 0)) || break
done

if ((${#rows[@]})); then
  echo "      | Date | Start (UTC) | Production | Backup | make restore done | Photo opens |"
  printf '      %s\n' "${rows[@]}"
fi

exit $((failures > 0))
