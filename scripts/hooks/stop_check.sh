#!/bin/bash
#
# Claude Code Stop hook: in unattended mode (KEEL_UNATTENDED=1), keep the
# session at work until the build report says the build is complete or
# blocked. Exit 2 prevents the stop and tells the agent what to do next.
#
# A stop is allowed when the build report has not changed across 5 blocked
# stops in a row (the agent is stuck, and a person must look), so the hook
# cannot loop forever. The counter lives in .claude/stop_blocks and resets
# whenever the build report changes. In attended mode the hook does nothing.
#
# Input: the hook JSON on stdin (stop_hook_active).

set -euo pipefail

readonly REPORT="docs/BUILD_REPORT.md"
readonly COUNTER="${CLAUDE_PROJECT_DIR:-.}/.claude/stop_blocks"
readonly MAX_BLOCKS=5

#######################################
# Print the status line of the build report, or nothing.
#######################################
status_line() {
  if [[ -f "${REPORT}" ]]; then
    grep -m 1 -i '^Status:' "${REPORT}" || true
  fi
}

#######################################
# Print the number of blocked stops since the build report last changed.
# Arguments: the current hash of the build report.
#######################################
blocks_since_change() {
  local hash="$1"
  local stored_hash="" count=0
  if [[ -f "${COUNTER}" ]]; then
    read -r stored_hash count < "${COUNTER}" || true
  fi
  if [[ "${stored_hash}" != "${hash}" ]]; then
    count=0
  fi
  echo "${count}"
}

main() {
  if [[ "${KEEL_UNATTENDED:-0}" != "1" ]]; then
    exit 0
  fi
  jq -r '.stop_hook_active // false' > /dev/null 2>&1 || true
  local status hash count
  status="$(status_line)"
  case "${status}" in
    *complete* | *blocked*) rm -f "${COUNTER}"; exit 0 ;;
  esac
  hash="$(sha256sum "${REPORT}" 2> /dev/null | cut -c1-16 || echo none)"
  count="$(blocks_since_change "${hash}")"
  if [[ "${count}" -ge "${MAX_BLOCKS}" ]]; then
    echo "stop hook: ${MAX_BLOCKS} stops were blocked with no change to ${REPORT}; the session may stop now. Write 'Status: blocked at stage N: <reason>' through a docs-only PR so the watchdog does not restart the same failure." >&2
    exit 0
  fi
  mkdir -p "$(dirname "${COUNTER}")"
  echo "${hash} $((count + 1))" > "${COUNTER}"
  echo "unattended build: the status line in ${REPORT} is '${status:-absent}', not complete or blocked. Continue with /build-all from the first stage without an entry in the build report. If a stage failed 3 times, write 'Status: blocked at stage N: <reason>' through a docs-only PR to main (branch docs/build-status), merge it, and then stop." >&2
  exit 2
}

main "$@"
