#!/usr/bin/env bash
# The switch between eBay's sandbox and the real account: one value of the chart, ebay.environment. Each environment
# keeps its keys in a folder of Infisical of its own, and the pods get those of the one chosen only. Run by
# make chart-check, in the toolbox.
set -uo pipefail
cd "$(dirname "$0")/.." || exit

failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

render() { # render <template> [helm option...]: one manifest, as Argo CD renders it
  helm template cards-warehouse . --set image.tag=check --show-only "templates/$1" "${@:2}"
}

# The folders of Infisical the operator copies into the Secret of the pods, on one line.
folders() {
  render infisicalstaticsecret.yaml "$@" | sed -n 's/^ *secretPath: //p' | tr '\n' ' '
}

# The eBay a pod is told it works on: the value the chart gives EBAY_ENVIRONMENT in each of its containers.
environment_of() { # environment_of <template> [helm option...]
  render "$@" | grep -A1 -- '- name: EBAY_ENVIRONMENT$' | sed -n 's/^ *value: //p' | sort -u | tr '\n' ' '
}

the_real_account_is_one_value_away() {
  local read app worker
  read=$(folders --set ebay.environment=production)
  app=$(environment_of deployment.yaml --set ebay.environment=production)
  worker=$(environment_of worker.yaml --set ebay.environment=production)
  [[ " $read" == *" /ebay/production "* && " $read" != *" /ebay/sandbox "* ]] &&
    [[ $app == "production " && $worker == "production " ]] || {
    echo "      folders: $read; app: ${app:-none}; worker: ${worker:-none}"
    return 1
  }
}

# Until the commit that switches it, a new version of the chart leaves the app on the sandbox.
the_sandbox_until_switched() {
  local read app worker
  read=$(folders)
  app=$(environment_of deployment.yaml)
  worker=$(environment_of worker.yaml)
  [[ " $read" == *" /ebay/sandbox "* && " $read" != *" /ebay/production "* ]] &&
    [[ $app == "sandbox " && $worker == "sandbox " ]] || {
    echo "      folders: $read; app: ${app:-none}; worker: ${worker:-none}"
    return 1
  }
}

# A typo in the commit that switches: Argo CD shows the sync failed, with why, instead of pods reading a folder of
# Infisical that does not exist and an app that cannot tell which eBay to ask.
a_mistyped_environment_stops_the_render() {
  local output
  if output=$(render infisicalstaticsecret.yaml --set ebay.environment=prodution 2>&1); then
    echo "      rendered: $(folders --set ebay.environment=prodution)"
    return 1
  fi
  [[ $output == *"ebay.environment"*"sandbox or production"* ]] || { echo "      $output"; return 1; }
}

check "with ebay.environment production, app and worker get the keys of /ebay/production, and not the sandbox's" \
  the_real_account_is_one_value_away
check "without the setting, app and worker get the keys of /ebay/sandbox only" the_sandbox_until_switched
check "an ebay.environment other than sandbox or production stops the render, and says why" \
  a_mistyped_environment_stops_the_render

exit $((failures > 0))
