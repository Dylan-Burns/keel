#!/bin/bash
#
# Claude Code PostToolUse hook: after Edit or Write, format the
# edited file and report lint findings back to the agent. Python files go
# through ruff format and ruff check; TypeScript and JavaScript files under
# web/ through prettier and eslint (gts); shell files through shellcheck.
# Exit 2 sends the findings to the
# agent so it fixes them before it moves on. Any other exit code is ignored.
#
# Input: the hook JSON on stdin (tool_input.file_path).

set -euo pipefail

#######################################
# Print the path of the file the tool touched, or nothing.
#######################################
edited_path() {
  jq -r '.tool_input.file_path // empty' 2> /dev/null || true
}

#######################################
# Format and lint one Python file. Returns 1 when findings remain.
#######################################
check_python() {
  local path="$1"
  uv run --no-sync ruff format --quiet "${path}" || true
  if ! uv run --no-sync ruff check --fix --quiet "${path}"; then
    uv run --no-sync ruff check "${path}" >&2 || true
    return 1
  fi
}

#######################################
# Format and lint one TypeScript or JavaScript file under web/. Returns 1 on findings.
#######################################
check_javascript() {
  local path="$1"
  case "${path}" in
    */node_modules/* | */dist/*) return 0 ;;
  esac
  npx --prefix web prettier --log-level silent --write "${path}" || true
  if ! npx --prefix web eslint --quiet "${path}"; then
    npx --prefix web eslint "${path}" >&2 || true
    return 1
  fi
}

#######################################
# Lint one shell file. Returns 1 on findings.
#######################################
check_shell() {
  local path="$1"
  if ! command -v shellcheck > /dev/null 2>&1; then
    return 0
  fi
  if ! shellcheck "${path}" >&2; then
    return 1
  fi
}

main() {
  local path
  path="$(edited_path)"
  if [[ -z "${path}" || ! -f "${path}" ]]; then
    exit 0
  fi
  local status=0
  case "${path}" in
    *.py) check_python "${path}" || status=1 ;;
    *.ts | *.tsx | *.js | *.mjs | *.cjs) check_javascript "${path}" || status=1 ;;
    *.sh) check_shell "${path}" || status=1 ;;
  esac
  # The two byte sequences are the em dash and the en dash in UTF-8.
  if grep -q $'\xe2\x80\x94\\|\xe2\x80\x93' "${path}" 2> /dev/null; then
    echo "${path}: contains an em dash or an en dash; replace it (CLAUDE.md)" >&2
    status=1
  fi
  if [[ "${status}" -ne 0 ]]; then
    echo "fix the findings above in ${path} before you continue" >&2
    exit 2
  fi
}

main "$@"
