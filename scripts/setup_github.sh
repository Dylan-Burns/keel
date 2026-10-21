#!/bin/bash
#
# Create the GitHub repository and apply the branch protection that
# CONTRIBUTING.md describes. Idempotent: safe to re-run.
#
# Usage: scripts/setup_github.sh <owner> <repo> [public|private]
# Requires: gh (authenticated), git, a committed repository in the cwd.

set -euo pipefail

readonly OWNER="${1:?owner is required}"
readonly REPO="${2:?repo is required}"
readonly VISIBILITY="${3:-private}"

#######################################
# Create the repository if it does not exist and push main.
#######################################
create_repo() {
  if gh repo view "${OWNER}/${REPO}" > /dev/null 2>&1; then
    echo "repository ${OWNER}/${REPO} exists"
  else
    gh repo create "${OWNER}/${REPO}" "--${VISIBILITY}" \
      --description "Grounded answers to business questions about SEC filings from one LLM call" \
      --source . --remote origin --push
  fi
  gh repo edit "${OWNER}/${REPO}" \
    --enable-issues --enable-projects=false --enable-wiki=false \
    --delete-branch-on-merge --enable-rebase-merge --enable-squash-merge=false \
    --enable-merge-commit=false --enable-auto-merge
}

#######################################
# Publish the corpus zip as a release asset so a cloud session or the pilot
# host can download it without the laptop (section 29.11).
#######################################
upload_corpus() {
  local zip="corpus/edgar_corpus.zip"
  if [[ ! -f "${zip}" ]]; then
    echo "no ${zip}; skip the corpus release (keel bootstrap needs KEEL_CORPUS__URL instead)"
    return
  fi
  if gh release view corpus-v1 --repo "${OWNER}/${REPO}" > /dev/null 2>&1; then
    echo "release corpus-v1 exists"
  else
    gh release create corpus-v1 "${zip}" --repo "${OWNER}/${REPO}" \
      --title "corpus v1" --notes "EDGAR corpus for Keel. Not a software release." \
      --prerelease
  fi
}

#######################################
# Require CI, linear history, and resolved conversations on main.
# Required approvals stay at 0 for a single maintainer; raise to 1 with a
# second maintainer (CONTRIBUTING.md).
#######################################
protect_main() {
  gh api --method PUT "repos/${OWNER}/${REPO}/branches/main/protection" \
    --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "contexts": [
      "python lint, format, types",
      "python tests and coverage",
      "dependency audit",
      "web lint, types, tests, build",
      "web e2e",
      "markdown, yaml, shell, dashes",
      "conventional commits",
      "gitleaks",
      "docker build"
    ]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false,
    "required_approving_review_count": 0
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "required_conversation_resolution": true
}
JSON
}

#######################################
# Environments that gate secrets: eval (nightly provider calls) and
# production (manual deploy with a required reviewer).
#######################################
create_environments() {
  gh api --method PUT "repos/${OWNER}/${REPO}/environments/eval" > /dev/null
  gh api --method PUT "repos/${OWNER}/${REPO}/environments/production" \
    --input - <<JSON > /dev/null
{
  "reviewers": [{"type": "User", "id": $(gh api "users/${OWNER}" --jq .id)}],
  "deployment_branch_policy": {"protected_branches": true, "custom_branch_policies": false}
}
JSON
  echo "environments eval and production created; add secrets with: gh secret set NAME --env production"
}

main() {
  create_repo
  protect_main
  create_environments
  upload_corpus
  echo "done. Next: gh secret set ANTHROPIC_API_KEY --env eval"
}

main "$@"
