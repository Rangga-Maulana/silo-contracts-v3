#!/usr/bin/env bash
# Reads lines: "<full_commit_sha> <subject>" from stdin.
# Writes markdown bullets "- <subject> (#<pr>)" when GitHub links the commit to a PR;
# otherwise "- <subject> ([<short>](commit-url))" so the label stays short but the link always works.
# Strips a trailing " (#N)" from subject before re-appending PR from the API.
set -euo pipefail

REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"

strip_trailing_pr_suffix() {
  sed -E 's/ \(#[0-9]+\)$//'
}

short_sha() {
  local sha="$1"
  git rev-parse --short "$sha" 2>/dev/null || printf '%.7s' "$sha"
}

pr_for_commit() {
  local sha="$1"
  gh api \
    --method GET \
    -H "Accept: application/vnd.github+json" \
    -H "X-GitHub-Api-Version: 2022-11-28" \
    "repos/${REPO}/commits/${sha}/pulls" \
    --jq '
      [.[] | select(.merged_at != null)] as $m
      | if ($m | length) > 0 then ($m | max_by(.number) | .number | tostring)
        elif length > 0 then .[0].number | tostring
        else empty end' 2>/dev/null || true
}

while IFS= read -r line || [[ -n "${line:-}" ]]; do
  [[ -z "${line:-}" ]] && continue
  sha="${line%% *}"
  subject="${line#* }"
  clean_subject=$(printf '%s\n' "$subject" | strip_trailing_pr_suffix)
  pr=$(pr_for_commit "$sha")
  if [[ -n "$pr" ]]; then
    printf -- '- %s (#%s)\n' "$clean_subject" "$pr"
  else
    s=$(short_sha "$sha")
    printf -- '- %s ([%s](https://github.com/%s/commit/%s))\n' "$subject" "$s" "$REPO" "$sha"
  fi
done
