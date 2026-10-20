#!/usr/bin/env bash
# Propose (never auto-merge) upstream/companion changes as reviewable GitHub PRs.
set -euo pipefail

if [[ "$GITHUB_REPOSITORY" != "xuan2261/kaggle-tpu-lab" || "$GITHUB_REF_NAME" != "main" ]]; then
  echo "::error::This sync workflow may only operate from xuan2261/kaggle-tpu-lab main"
  exit 1
fi

case "$SOURCE" in
  upstream)
    source_url="https://github.com/ARahim3/kaggle-tpu-lab.git"
    ;;
  companion)
    source_url="https://github.com/Haz4rdovisk/kaggle-tpu-lab.git"
    ;;
  *)
    echo "::error::Unsupported SOURCE value"
    exit 1
    ;;
esac

prefix="sync/$SOURCE-"
open_count=$(gh pr list --state open --base main --limit 100 --json headRefName \
  --jq "[.[] | select(.headRefName | startswith(\"$prefix\"))] | length")
if [[ "$open_count" != "0" ]]; then
  echo "An open draft PR for $SOURCE already exists; not creating a duplicate."
  exit 0
fi

git remote add candidate "$source_url"
git fetch --no-tags candidate main
source_sha=$(git rev-parse candidate/main)
if git merge-base --is-ancestor "$source_sha" HEAD; then
  echo "Nothing new from $SOURCE ($source_sha)."
  exit 0
fi

short_sha=$(printf '%s' "$source_sha" | cut -c1-12)
new_branch="$prefix$short_sha"
if git ls-remote --exit-code --heads origin "$new_branch" >/dev/null 2>&1; then
  echo "::warning::Branch $new_branch already exists; review it manually."
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git switch -c "$new_branch"
if ! git merge --no-ff --no-edit -m "chore(sync): import $SOURCE $short_sha" candidate/main; then
  echo "::error::Manual merge conflict in $SOURCE; no branch pushed."
  git diff --name-only --diff-filter=U
  git merge --abort || true
  exit 1
fi

git push origin "HEAD:refs/heads/$new_branch"

body=$(cat <<EOF
## Automated proposal, not an approved release

Source: $source_url
Source commit: $source_sha
Fork base: main

This is a merge commit preserving source history, not a force push.
No automatic merge, deployment, Kaggle job or GCP resource was started.

### Before approval
- Review changed code, security, licenses and compatibility.
- Approve and complete any CI runs that GitHub marks approval-required.
- Run actual Kaggle TPU and Windows packaging smoke checks when needed.
- Resolve conflicting Companion settings manually.
EOF
)

if ! gh pr create --draft --head "$new_branch" --base main \
    --title "chore(sync): propose $SOURCE $short_sha" --body "$body"; then
  echo "::error::Branch $new_branch exists but PR creation failed."
  echo "If needed, enable GitHub Actions to create PRs under Settings > Actions > General."
  exit 1
fi

echo "Proposed a draft sync PR for $SOURCE at $short_sha."
