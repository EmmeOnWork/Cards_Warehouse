#!/usr/bin/env bash
# Acceptance test of the daily check, run by hand with the platform up, after the push that brought it. It starts a
# check like the daily one, waits for it, and checks that the app shows what it found. Inside the toolbox (make shell):
#   bash infra/platform/tests/daily-check.sh
set -uo pipefail

cronjob=cards-warehouse-daily-check
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

kube() { kubectl --context kind-cards-warehouse "$@"; }
in_app() { kube --namespace cards-warehouse "$@"; }
epoch() { date --date "$1" +%s; }

if ! kube get --raw /readyz >/dev/null 2>&1; then
  echo "FAIL  the test needs the platform up, but the cluster cards-warehouse does not answer: run make platform-up first"
  exit 1
fi

# Argo CD lists among the resources of the app's Application those it installed from the chart.
cronjob_is_installed_by_argocd() {
  local status installed
  status=$(kube --namespace argocd get application cards-warehouse \
    -o jsonpath='{.status.sync.status} {.status.health.status}' 2>/dev/null)
  installed=$(kube --namespace argocd get application cards-warehouse \
    -o jsonpath='{.status.resources[?(@.kind=="CronJob")].name}' 2>/dev/null)
  [[ $status == "Synced Healthy" && $installed == "$cronjob" ]] || {
    echo "      cards-warehouse: ${status:-no application}; CronJob installed: ${installed:-none}"
    return 1
  }
}

# The commit Argo CD runs, in the app and in the check alike.
cronjob_runs_the_image_of_the_app() {
  local app job
  app=$(in_app get deployment cards-warehouse -o jsonpath='{.spec.template.spec.containers[?(@.name=="app")].image}')
  job=$(in_app get cronjob "$cronjob" -o jsonpath='{.spec.jobTemplate.spec.template.spec.containers[0].image}' 2>/dev/null)
  [[ -n $app && $job == "$app" ]] || { echo "      app: ${app:-none}; check: ${job:-none}"; return 1; }
}

# Every day: the last three fields of the cron expression, day of month, month and day of week, are all "*".
cronjob_runs_every_day_in_italian_time() {
  local cron zone
  cron=$(in_app get cronjob "$cronjob" -o jsonpath='{.spec.schedule}' 2>/dev/null)
  zone=$(in_app get cronjob "$cronjob" -o jsonpath='{.spec.timeZone}' 2>/dev/null)
  [[ $cron =~ ^[0-9]+\ [0-9]+\ \*\ \*\ \*$ && $zone == Europe/Rome ]] || {
    echo "      schedule '${cron}' in '${zone}'"
    return 1
  }
}

# The same Job the schedule starts, started now instead of at its hour.
job=$cronjob-by-hand-$(date --utc +%Y%m%d%H%M%S)
check_started_by_hand_completes() {
  local completed=no
  in_app create job "$job" --from "cronjob/$cronjob" >/dev/null &&
    in_app wait --for condition=complete "job/$job" --timeout 120s >/dev/null 2>&1 && completed=yes
  [[ $completed == yes ]] || {
    echo "      $job:"
    in_app logs "job/$job" 2>&1 | tail -n 5 | sed 's/^/      /'
    return 1
  }
}

# The line the Job logged is the one the home shows: read by the app inside its own pod, from the same database.
app_shows_what_the_check_found() {
  local logged shown
  logged=$(in_app logs "job/$job" 2>/dev/null)
  shown=$(in_app exec deploy/cards-warehouse -c app -- python -c '
from datetime import UTC, datetime
from cards_warehouse import daily_check
from cards_warehouse.database import create_database_engine
with create_database_engine().connect() as connection:
    print(daily_check.summary(daily_check.last(connection), datetime.now(UTC)).text)' 2>&1)
  [[ -n $logged && $shown == "$logged" && $shown =~ ^(Controllo|Attenzione:\ il\ controllo)\ del\  ]] || {
    echo "      logged by the check: ${logged:-nothing}"
    echo "      shown by the app: $shown"
    return 1
  }
}

# Before the first 07:00 after the CronJob was installed, there is none yet: run the test again the next day.
schedule_ran_in_the_last_day() {
  local last age=""
  last=$(in_app get cronjob "$cronjob" -o jsonpath='{.status.lastSuccessfulTime}' 2>/dev/null)
  [[ -n $last ]] && age=$(($(date +%s) - $(epoch "$last")))
  [[ -n $age && $age -le 86400 ]] || {
    echo "      last successful check of the schedule: ${last:-never}"
    return 1
  }
}

check "the CronJob is installed by Argo CD" cronjob_is_installed_by_argocd
check "it runs the image of the app" cronjob_runs_the_image_of_the_app
check "it runs every day, in Italian time" cronjob_runs_every_day_in_italian_time
check "a check started by hand completes" check_started_by_hand_completes
check "the app shows what it found" app_shows_what_the_check_found
check "the schedule ran a check in the last 24 hours, and it completed" schedule_ran_in_the_last_day

exit $((failures > 0))
