#!/usr/bin/env bash
# Acceptance test of the access from outside home, run by hand with the platform up and the Tailscale
# node logged in (infra/tailscale/README.md). Inside the toolbox (make shell):
#   bash infra/tailscale/tests/acceptance.sh
# Run it again after make platform-down and make platform-up: the address the phone opens must not change.
set -uo pipefail

node=cards-warehouse-tailscale
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

tailscale() { # tailscale <arguments...>: the CLI of the node, in its container
  docker exec "$node" tailscale "$@"
}

# What the node reports about itself, empty when its container is not running.
status=$(tailscale status --json 2>/dev/null)
# The address the phone opens: the node's name in the tailnet, without the final dot of DNS.
address=$(jq -r '.Self.DNSName // empty' <<<"$status" 2>/dev/null | sed 's/\.$//')

# Logged in and online, under its own name: a second node with the same name would get magazzino-1,
# and the phone's bookmark would lead nowhere.
node_is_online_as_magazzino() {
  local state
  state=$(jq -r '"\(.BackendState) \(.Self.Online) \(.Self.DNSName)"' <<<"$status" 2>/dev/null)
  [[ $state == "Running true magazzino."* ]] || { echo "      node: ${state:-not running}"; return 1; }
}

# With key expiry on, the node logs out after 180 days, and the app is out of reach until a new login.
node_key_never_expires() {
  local expiry
  [[ -n $status ]] || { echo "      node: not running"; return 1; }
  expiry=$(jq -r '.Self.KeyExpiry // empty' <<<"$status")
  [[ -z $expiry ]] || { echo "      the key expires on $expiry: disable key expiry for magazzino in the admin console"; return 1; }
}

# The phone's path: into the tailnet, to the node's HTTPS port, through Serve to the PC port of the app.
# The node's outbound proxy is a way into the tailnet; curl checks the certificate as the phone's browser does.
app_answers_over_https_from_the_tailnet() {
  local answer
  [[ -n $address ]] || { echo "      the node has no address"; return 1; }
  answer=$(curl --silent --show-error --fail --max-time 30 --proxy http://127.0.0.1:1055 "https://$address/readyz")
  [[ $answer == '{"status":"ok"}' ]] || { echo "      https://$address/readyz: ${answer:-no answer}"; return 1; }
}

# Funnel would give the name public DNS records. Without it, a resolver on the internet knows no address
# for the name, or only a tailnet one (100.64.0.0/10, fd7a:115c:a1e0::/48), which the internet cannot route.
internet_finds_no_route_to_the_app() {
  local type answers ip routable=()
  [[ -n $address ]] || { echo "      the node has no address"; return 1; }
  for type in A AAAA; do
    answers=$(curl --silent --fail --max-time 10 --header 'accept: application/dns-json' \
      "https://cloudflare-dns.com/dns-query?name=$address&type=$type" | jq -r '.Answer[]? | select(.type == 1 or .type == 28) | .data') || {
      echo "      the public resolver did not answer"
      return 1
    }
    for ip in $answers; do
      [[ $ip =~ ^100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\. || $ip == fd7a:115c:a1e0:* ]] || routable+=("$ip")
    done
  done
  [[ ${#routable[@]} -eq 0 ]] || { echo "      public DNS gives $address: ${routable[*]}"; return 1; }
}

check "the Tailscale node is online in the tailnet as magazzino" node_is_online_as_magazzino
check "the node's key never expires" node_key_never_expires
check "from the tailnet, the app answers healthy over HTTPS, with a valid certificate" app_answers_over_https_from_the_tailnet
check "public DNS gives the internet no route to the app" internet_finds_no_route_to_the_app
[[ -n $address ]] && echo "      the phone opens https://$address"

exit $((failures > 0))
