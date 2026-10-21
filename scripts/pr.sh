#!/bin/bash
#
# Pull request operations through the GitHub REST API (`gh api`). The GitHub
# proxy of a Claude Code cloud session rejects GraphQL, and with it `gh pr`
# and `gh issue`, so every PR step in the build goes through this script.
# It works the same on a laptop.
#
# Usage:
#   scripts/pr.sh open <title> <body-file>     open a PR from the current branch to main; prints the number
#   scripts/pr.sh number                       print the open PR number for the current branch, or nothing
#   scripts/pr.sh wait <number> [minutes]      wait until every check on the PR head completes (default 45)
#   scripts/pr.sh merge <number>               rebase merge; GitHub refuses it while a required check is red
#   scripts/pr.sh status <number>              print the checks and the mergeable state once
# Requires: gh (with GH_TOKEN or the session proxy), git, jq.

set -euo pipefail

#######################################
# Print owner/repo from the origin remote.
#######################################
repo_slug() {
  git remote get-url origin | sed -E 's#.*github\.com[:/]##; s#\.git$##'
}

#######################################
# Print the current branch name.
#######################################
current_branch() {
  git rev-parse --abbrev-ref HEAD
}

#######################################
# Open a PR from the current branch to main.
# Arguments: title, body file.
#######################################
open_pr() {
  local title="$1"
  local body_file="$2"
  local branch
  branch="$(current_branch)"
  if [[ "${branch}" == "main" ]]; then
    echo "refusing to open a PR from main" >&2
    exit 1
  fi
  git push --set-upstream origin "${branch}" > /dev/null 2>&1 || git push origin "${branch}"
  gh api "repos/$(repo_slug)/pulls" \
    -f title="${title}" -f head="${branch}" -f base=main -F body=@"${body_file}" \
    --jq .number
}

#######################################
# Print the open PR number for the current branch, if any.
#######################################
pr_number() {
  local slug
  slug="$(repo_slug)"
  gh api "repos/${slug}/pulls?state=open&head=${slug%%/*}:$(current_branch)" --jq '.[0].number // empty'
}

#######################################
# Print one line per check run on the PR head and the mergeable state.
# Arguments: PR number.
#######################################
status_pr() {
  local number="$1"
  local slug sha
  slug="$(repo_slug)"
  sha="$(gh api "repos/${slug}/pulls/${number}" --jq .head.sha)"
  gh api --paginate "repos/${slug}/commits/${sha}/check-runs" \
    --jq '.check_runs[] | "\(.name): \(.status) \(.conclusion // "")"'
  echo "mergeable_state: $(gh api "repos/${slug}/pulls/${number}" --jq .mergeable_state)"
}

#######################################
# Wait until every check run on the PR head has completed, then until GitHub
# reports the PR as mergeable. Exit 1 on a failed check or a timeout.
# Arguments: PR number, timeout in minutes (default 45).
#######################################
wait_pr() {
  local number="$1"
  local minutes="${2:-45}"
  local slug sha deadline runs pending failed state
  slug="$(repo_slug)"
  sha="$(gh api "repos/${slug}/pulls/${number}" --jq .head.sha)"
  deadline=$(( $(date +%s) + minutes * 60 ))
  while true; do
    runs="$(gh api --paginate "repos/${slug}/commits/${sha}/check-runs" --jq '.check_runs[] | "\(.status)|\(.conclusion // "")|\(.name)"')"
    pending="$(printf '%s\n' "${runs}" | grep -c -v '^completed|' || true)"
    failed="$(printf '%s\n' "${runs}" | grep -E '^completed\|(failure|cancelled|timed_out|action_required)\|' || true)"
    if [[ -n "${failed}" ]]; then
      echo "failed checks on PR #${number}:" >&2
      printf '%s\n' "${failed}" | cut -d'|' -f3 >&2
      exit 1
    fi
    if [[ -n "${runs}" && "${pending}" -eq 0 ]]; then
      state="$(gh api "repos/${slug}/pulls/${number}" --jq .mergeable_state)"
      case "${state}" in
        clean)
          echo "PR #${number}: every check passed, mergeable"
          return 0
          ;;
        dirty)
          echo "PR #${number} has a merge conflict with main; rebase and push" >&2
          exit 1
          ;;
      esac
    fi
    if [[ "$(date +%s)" -ge "${deadline}" ]]; then
      echo "timed out after ${minutes} minutes; ${pending} checks still pending, state ${state:-unknown}" >&2
      exit 1
    fi
    sleep 30
  done
}

#######################################
# Rebase-merge the PR. Branch protection makes GitHub refuse the merge while
# a required check is red or the branch is behind main.
# Arguments: PR number.
#######################################
merge_pr() {
  local number="$1"
  local slug
  slug="$(repo_slug)"
  gh api -X PUT "repos/${slug}/pulls/${number}/merge" -f merge_method=rebase --jq .merged
  git checkout main > /dev/null
  git pull --ff-only origin main > /dev/null
  echo "PR #${number} merged; main is up to date"
}

main() {
  local command="${1:-}"
  case "${command}" in
    open) open_pr "${2:?title is required}" "${3:?body file is required}" ;;
    number) pr_number ;;
    status) status_pr "${2:?PR number is required}" ;;
    wait) wait_pr "${2:?PR number is required}" "${3:-45}" ;;
    merge) merge_pr "${2:?PR number is required}" ;;
    *)
      sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
      exit 1
      ;;
  esac
}

main "$@"
