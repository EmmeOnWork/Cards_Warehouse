#!/usr/bin/env bash
# The release: points the app's Application at the image of <commit>, in one commit by the
# GitHub bot that changes only image.tag. The pipeline runs it on the latest main, once the
# image of <commit> is published, then pushes the commit. In a Git repository:
#   bash gitops/promote.sh <commit> <previous head of main>
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

commit=$1 previous=$2
manifest=gitops/apps/cards-warehouse.yaml

# The image holds only app/. The whole push counts, not just its last commit.
if git diff --quiet "$previous" "$commit" -- app/; then
  echo "nothing to release: the push of $commit changes nothing in app/"
  exit 0
fi
# Two pipelines can end in the wrong order: an older commit never replaces a newer one.
# A commit counts as its own ancestor, so a pipeline run again releases nothing either.
released=$(sed -n 's/^ *tag: *//p' "$manifest")
if git merge-base --is-ancestor "$commit" "$released" 2>/dev/null; then
  echo "nothing to release: $released, already released, is $commit or newer"
  exit 0
fi

sed -i "s/^\( *tag:\).*/\1 $commit/" "$manifest"
# The identity GitHub shows as github-actions[bot]: the number is the bot's user id.
git -c user.name='github-actions[bot]' \
  -c user.email='41898282+github-actions[bot]@users.noreply.github.com' \
  commit --quiet --message "release: run $commit" -- "$manifest"
echo "released $commit"
