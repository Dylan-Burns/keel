#!/bin/bash
#
# Claude Code PreToolUse hook for Bash: block the commands that the repo
# rules forbid, whatever the permission list allows. Exit 2 blocks the call
# and shows the reason to the agent.
#
# Input: the hook JSON on stdin (tool_input.command).

set -euo pipefail

#######################################
# Print the command the agent wants to run, or nothing.
#######################################
requested_command() {
  jq -r '.tool_input.command // empty' 2> /dev/null || true
}

#######################################
# Block a command that matches a forbidden pattern.
# Arguments: the command, the pattern, the reason.
#######################################
block_if() {
  local command="$1"
  local pattern="$2"
  local reason="$3"
  if [[ "${command}" =~ ${pattern} ]]; then
    echo "blocked: ${reason}" >&2
    exit 2
  fi
}

#######################################
# Allow `rm -rf` only on generated directories (index, cache, logs, build
# output). Anything else is blocked.
# Arguments: the command.
#######################################
check_recursive_delete() {
  local command="$1"
  if [[ ! "${command}" =~ rm[[:space:]]+-[a-zA-Z]*(rf|fr|r[a-zA-Z]*f|f[a-zA-Z]*r) ]]; then
    return 0
  fi
  local word
  for word in ${command}; do
    case "${word}" in
      rm | -*) continue ;;
      index/* | cache/* | logs/* | dist/* | build/* | .pytest_cache* | .mypy_cache* | .ruff_cache* | web/node_modules* | web/dist* | web/test-results* | web/playwright-report* | htmlcov* | reports/*) continue ;;
      *)
        echo "blocked: rm -rf outside the generated directories (${word}); name the files or ask" >&2
        exit 2
        ;;
    esac
  done
}

main() {
  local command
  command="$(requested_command)"
  if [[ -z "${command}" ]]; then
    exit 0
  fi
  block_if "${command}" 'git[[:space:]]+push[^|;&]*([[:space:]]-f([[:space:]]|$)|--force|[[:space:]]\+[^[:space:]])' \
    "force pushes are forbidden (CLAUDE.md); open a fix commit instead"
  block_if "${command}" 'git[[:space:]]+push[^|;&]*[[:space:]](origin[[:space:]]+)?\+?(HEAD:|[a-zA-Z0-9_/.-]+:)?(refs/heads/)?main([[:space:]]|$)' \
    "pushes to main are forbidden; push the stage branch and open a PR"
  block_if "${command}" 'git[[:space:]]+commit[^|;&]*(--no-verify|[[:space:]]-n([[:space:]]|$))' \
    "commits must run the hooks; fix the findings instead of skipping them"
  check_recursive_delete "${command}"
  block_if "${command}" '(^|[[:space:]])corpus/edgar_corpus\.zip([[:space:]]|$).*(rm|mv)|(rm|mv)[[:space:]].*corpus/' \
    "nothing under corpus/ is deleted or moved"
  block_if "${command}" '(^|[[:space:]])sudo([[:space:]]|$)' \
    "sudo is not needed in this repo"
  block_if "${command}" '(^|[[:space:]/])\.env([[:space:]]|$)' \
    "the .env file is never read or printed; the secrets reach the process through the environment"
  block_if "${command}" 'pytest[^|;&]*(--deselect|-k[[:space:]]+"?not[[:space:]])' \
    "tests are not deselected to make a check green; fix the test or the code"
  exit 0
}

main "$@"
