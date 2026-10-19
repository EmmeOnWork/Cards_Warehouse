#!/usr/bin/env bash
# Unit tests of gitops/promote.sh, each in a throwaway Git repository that holds the real
# Application manifest: no GitHub, no cluster, a few seconds. Inside the toolbox:
#   make gitops-check
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd)
promote=$here/../promote.sh
manifest=gitops/apps/cards-warehouse.yaml
failures=0
check() { # check "<behaviour>" <command...>
  if "${@:2}"; then echo "PASS  $1"; else echo "FAIL  $1"; failures=$((failures + 1)); fi
}

repo=
new_repo() { # a repository whose first commit holds the manifest and an app
  repo=$(mktemp -d)
  git -C "$repo" init --quiet
  mkdir -p "$repo/gitops/apps" "$repo/app"
  cp "$here/../apps/cards-warehouse.yaml" "$repo/gitops/apps/"
  change app/main.py 'version 1' >/dev/null
}
change() { # change <file> <content>: commits the new content, as a person, and prints the commit
  echo "$2" >"$repo/$1"
  git -C "$repo" add --all
  git -C "$repo" -c user.name=Manuel -c user.email=manuel@example.com commit --quiet --message "change $1"
  last_commit
}
last_commit() { git -C "$repo" rev-parse HEAD; }
promote() { (cd "$repo" && bash "$promote" "$@"); }
tag() { sed -n 's/^ *tag: *//p' "$repo/$manifest"; }

a_commit_that_changes_the_app_becomes_the_tag_in_a_bot_commit_of_one_line() {
  local before pushed bot='github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>'
  new_repo
  before=$(last_commit)
  pushed=$(change app/main.py 'version 2')

  promote "$pushed" "$before" || return 1

  [[ $(tag) == "$pushed" ]] || { echo "      tag: $(tag)"; return 1; }
  [[ $(git -C "$repo" show --format= --numstat HEAD) == $'1\t1\t'"$manifest" ]] || {
    git -C "$repo" show --stat HEAD
    return 1
  }
  [[ $(git -C "$repo" show --no-patch --format='%an <%ae>|%cn <%ce>' HEAD) == "$bot|$bot" ]] || {
    git -C "$repo" show --no-patch --format=fuller HEAD
    return 1
  }
}

# A note or a README is not a new version of the app: no release commit, no pod restarted.
# The same goes for the revert of a release commit, which is how a release is undone.
a_push_that_changes_nothing_in_the_app_releases_nothing() {
  local before pushed
  new_repo
  before=$(last_commit)
  pushed=$(change README.md 'notes')

  promote "$pushed" "$before" || return 1

  [[ $(last_commit) == "$pushed" ]] || { git -C "$repo" log --oneline -3; return 1; }
}

# Two pushes in a row, A then B: if B's pipeline ends first, A's must not bring back the older app.
a_commit_older_than_the_one_released_is_not_released() {
  local first a b released
  new_repo
  first=$(last_commit)
  a=$(change app/main.py 'version 2')
  b=$(change app/main.py 'version 3')
  promote "$b" "$a" >/dev/null || return 1
  released=$(last_commit)

  promote "$a" "$first" || return 1

  [[ $(last_commit) == "$released" && $(tag) == "$b" ]] || { echo "      tag: $(tag)"; return 1; }
}

check "a commit that changes the app becomes image.tag, in a bot commit that changes only that line" \
  a_commit_that_changes_the_app_becomes_the_tag_in_a_bot_commit_of_one_line
check "a push that changes nothing in app/ releases nothing" \
  a_push_that_changes_nothing_in_the_app_releases_nothing
check "a commit older than the one released is not released" \
  a_commit_older_than_the_one_released_is_not_released

exit $((failures > 0))
