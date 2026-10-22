#!/bin/bash
#
# Demo pre-flight: the machine-checkable items of the checklist in chapter
# 21.1. Run it the night before the demo and again 30 minutes before. The
# items that need a person (the 3 live questions, the offline drill, the
# printed answers, the power and sleep settings, the hotspot, the sticky
# note) stay manual; the script lists them at the end.
#
# Usage: scripts/demo_preflight.sh [--skip-tests] [--no-start] [--port N]
#   --skip-tests  skip `make test` (it takes minutes)
#   --no-start    never start `keel serve`; a stopped service is a failure
#   --port N      the port of `keel serve` (default 8000)
#
# The script starts `keel serve` in the background when nothing answers on
# the port, and leaves it running for the demo (the PID and the log path are
# printed). It never prints a secret: the checks report set or absent only.
#
# Exit code: 0 when no check failed (warnings allowed), 1 when one failed.
# Requires: uv, curl, jq, df, a checkout of the repository.

set -euo pipefail

readonly MIN_FREE_KB=$((2 * 1024 * 1024))
readonly GOLDEN_QUESTIONS=28
readonly SERVE_WAIT_SECONDS=180

SKIP_TESTS=0
NO_START=0
PORT=8000
BASE_URL=""
LOG_DIR=""
INDEX_VERSION=""

# Parallel arrays for the summary table (bash 3.2 has no associative arrays).
CHECK_NAMES=()
CHECK_STATUSES=()
CHECK_DETAILS=()

#######################################
# Record 1 check result and print it as it happens.
# Globals:
#   CHECK_NAMES, CHECK_STATUSES, CHECK_DETAILS (appended)
# Arguments:
#   The check name, the status (pass, warn, or fail), the detail.
#######################################
record() {
  CHECK_NAMES+=("$1")
  CHECK_STATUSES+=("$2")
  CHECK_DETAILS+=("$3")
  printf '%-5s %s: %s\n' "$2" "$1" "$3"
}

#######################################
# Print the usage line from the header and exit.
# Arguments:
#   The exit code.
#######################################
usage() {
  echo "usage: scripts/demo_preflight.sh [--skip-tests] [--no-start] [--port N]"
  exit "$1"
}

#######################################
# Read the command-line flags into the globals.
# Globals:
#   SKIP_TESTS, NO_START, PORT, BASE_URL (set)
# Arguments:
#   The script arguments.
#######################################
parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --skip-tests) SKIP_TESTS=1 ;;
      --no-start) NO_START=1 ;;
      --port)
        [[ $# -ge 2 && "$2" =~ ^[0-9]+$ ]] || usage 2
        PORT="$2"
        shift
        ;;
      -h | --help) usage 0 ;;
      *) usage 2 ;;
    esac
    shift
  done
  BASE_URL="http://127.0.0.1:${PORT}"
}

#######################################
# Item 1: `make test` (ruff, mypy, pylint, pytest with coverage).
# Globals:
#   SKIP_TESTS, LOG_DIR
#######################################
check_tests() {
  if [[ "${SKIP_TESTS}" -eq 1 ]]; then
    record "make test" "warn" \
      "skipped (--skip-tests); run it once before the demo"
    return
  fi
  local log="${LOG_DIR}/preflight_make_test.log"
  echo "running make test (log: ${log})"
  if make test > "${log}" 2>&1; then
    local summary
    summary="$(grep -E '[0-9]+ passed' "${log}" | tail -n 1 || true)"
    record "make test" "pass" "${summary:-passed}"
  else
    record "make test" "fail" "see ${log}"
  fi
}

#######################################
# Print 1 jq result of a JSON text, or nothing when the text is not JSON.
# Arguments:
#   The jq filter, the JSON text.
# Outputs:
#   The raw jq output on stdout.
#######################################
json_get() {
  jq -r "$1" <<< "$2" 2> /dev/null || true
}

#######################################
# Return 0 when the text is a JSON object.
# Arguments:
#   The text.
#######################################
is_object() {
  jq -e 'type == "object"' <<< "$1" > /dev/null 2>&1
}

#######################################
# Item 2: `keel doctor`, plus its clock row as its own line.
#######################################
check_doctor() {
  local json
  if ! json="$(HF_HUB_OFFLINE=1 uv run keel doctor --json 2> /dev/null)"; then
    if [[ -z "${json}" ]]; then
      record "keel doctor" "fail" "the command did not run"
      record "clock" "fail" "no doctor output"
      return
    fi
  fi
  # $s is a jq variable, not a shell one.
  # shellcheck disable=SC2016
  local names='[.[] | select(.status == $s) | .name] | join(", ")'
  local fails warns
  fails="$(jq -r --arg s fail "${names}" <<< "${json}" 2> /dev/null || true)"
  warns="$(jq -r --arg s warn "${names}" <<< "${json}" 2> /dev/null || true)"
  if [[ -n "${fails}" ]]; then
    record "keel doctor" "fail" "failed: ${fails}"
  elif [[ -n "${warns}" ]]; then
    record "keel doctor" "warn" "warnings: ${warns}"
  else
    record "keel doctor" "pass" "every check ok"
  fi
  # The clock against the newest corpus filing (E-F-12): doctor computes it.
  local clock_status clock_detail
  local clock='.[] | select(.name == "clock")'
  clock_status="$(json_get "${clock} | .status" "${json}")"
  clock_detail="$(json_get "${clock} | .detail" "${json}")"
  case "${clock_status}" in
    ok) record "clock" "pass" "${clock_detail}" ;;
    "") record "clock" "warn" "doctor reported no clock row" ;;
    *) record "clock" "warn" "${clock_detail}" ;;
  esac
}

#######################################
# Item 2 (disk): more than 2 GB free on the volume of the repository.
#######################################
check_disk() {
  local free_kb
  free_kb="$(df -Pk . | awk 'NR == 2 { print $4 }')"
  local free_gb
  free_gb="$(awk -v kb="${free_kb}" 'BEGIN { printf "%.1f", kb / 1048576 }')"
  if [[ "${free_kb}" -gt "${MIN_FREE_KB}" ]]; then
    record "free disk" "pass" "${free_gb} GB free (minimum 2 GB)"
  else
    record "free disk" "fail" "${free_gb} GB free, below 2 GB"
  fi
}

#######################################
# Return 0 when a Keel /api/health answers at the URL.
# Arguments:
#   The base URL.
#######################################
healthy() {
  local body
  body="$(curl --silent --fail --max-time 3 "$1/api/health" 2> /dev/null)" \
    || return 1
  [[ "$(json_get '.status' "${body}")" == "ok" ]]
}

#######################################
# Find a running Keel on PORT to PORT+10, the range `keel serve` moves
# through when a port is busy.
# Globals:
#   PORT, BASE_URL (set when found)
# Returns:
#   0 when found, else 1.
#######################################
find_running() {
  local port
  for ((port = PORT; port <= PORT + 10; port++)); do
    if healthy "http://127.0.0.1:${port}"; then
      BASE_URL="http://127.0.0.1:${port}"
      return 0
    fi
  done
  return 1
}

#######################################
# Start `keel serve` in the background unless it already answers, and wait
# for /api/health. A busy port moves the service up to 10 ports higher, so
# the URL comes from the startup line of the log.
# Globals:
#   NO_START, PORT, LOG_DIR, BASE_URL (set)
#######################################
check_serve() {
  if find_running; then
    record "keel serve" "pass" "already running at ${BASE_URL}"
    return
  fi
  if [[ "${NO_START}" -eq 1 ]]; then
    record "keel serve" "fail" "nothing answers at ${BASE_URL} (--no-start)"
    return
  fi
  local log="${LOG_DIR}/preflight_serve.log"
  nohup uv run keel serve --port "${PORT}" > "${log}" 2>&1 &
  local pid=$!
  local waited=0
  while [[ "${waited}" -lt "${SERVE_WAIT_SECONDS}" ]]; do
    local url
    url="$(grep -o -m 1 -E 'serves at http://[^ ]+' "${log}" 2> /dev/null \
      | sed 's/^serves at //' || true)"
    if [[ -n "${url}" ]]; then
      BASE_URL="${url}"
    fi
    if healthy "${BASE_URL}"; then
      record "keel serve" "pass" \
        "started at ${BASE_URL}, PID ${pid}, log ${log}"
      return
    fi
    if ! kill -0 "${pid}" 2> /dev/null; then
      record "keel serve" "fail" "the process exited; see ${log}"
      return
    fi
    sleep 2
    waited=$((waited + 2))
  done
  record "keel serve" "fail" \
    "no /api/health after ${SERVE_WAIT_SECONDS} s; see ${log}"
}

#######################################
# /api/health: the process runs and reports its version.
# Globals:
#   BASE_URL
#######################################
check_health() {
  local body
  if ! body="$(curl --silent --fail --max-time 5 "${BASE_URL}/api/health")" \
    || ! is_object "${body}"; then
    record "/api/health" "fail" "no answer at ${BASE_URL}"
    return
  fi
  local status version
  status="$(json_get '.status // empty' "${body}")"
  version="$(json_get '.version // empty' "${body}")"
  if [[ "${status}" == "ok" ]]; then
    record "/api/health" "pass" "status ok, keel ${version}"
  else
    record "/api/health" "fail" "status '${status}'"
  fi
}

#######################################
# Item 3: /api/ready reports ready with the version of index/current.
# Globals:
#   BASE_URL, INDEX_VERSION (set)
#######################################
check_ready() {
  local expected="" manifest="index/current/manifest.json"
  if [[ -f "${manifest}" ]]; then
    expected="$(json_get '.index_version // empty' "$(cat "${manifest}")")"
  fi
  local body
  # HTTP 503 means index_corrupt; the body still says why.
  if ! body="$(curl --silent --max-time 10 "${BASE_URL}/api/ready")" \
    || [[ -z "${body}" ]]; then
    record "/api/ready" "fail" "no answer at ${BASE_URL}"
    return
  fi
  if ! is_object "${body}"; then
    record "/api/ready" "fail" "not a Keel response at ${BASE_URL}"
    return
  fi
  local ready failed
  ready="$(json_get '.ready' "${body}")"
  INDEX_VERSION="$(json_get '.index_version // empty' "${body}")"
  failed="$(json_get '[.checks // {} | to_entries[]
    | select(.value != true) | .key] | join(", ")' "${body}")"
  if [[ "${ready}" != "true" ]]; then
    record "/api/ready" "fail" \
      "ready false; failed checks: ${failed:-none named}"
  elif [[ -n "${expected}" && "${INDEX_VERSION}" != "${expected}" ]]; then
    record "/api/ready" "fail" \
      "index ${INDEX_VERSION}, expected ${expected} from index/current"
  else
    record "/api/ready" "pass" "ready, index ${INDEX_VERSION}"
  fi
  if [[ -z "${INDEX_VERSION}" ]]; then
    INDEX_VERSION="${expected}"
  fi
}

#######################################
# Count the golden questions with an entry in the answer cache, with the
# cache key of decision D-29.
# Arguments:
#   The index version.
# Outputs:
#   "<found> <total>" on stdout.
#######################################
count_cached() {
  uv run python - "$1" << 'PY'
"""Count the golden questions with an entry in the answer cache."""
import pathlib
import sys

import yaml

from keel import cache
from keel import config

settings = config.load_settings()
golden = yaml.safe_load(pathlib.Path("eval/golden.yaml").read_text("utf-8"))
store = cache.AnswerCache(pathlib.Path(settings.cache.answers_dir))
questions = [q["question"] for q in golden["questions"]]
found = sum(
    store.path(
        cache.cache_key(
            q, sys.argv[1], settings.llm.prompt_version, settings.llm.model
        )
    ).is_file()
    for q in questions
)
print(found, len(questions))
PY
}

#######################################
# Item 4: the answer cache holds the 28 golden questions. `keel warm-cache`
# lands in stage 15; before it exists the check reports that.
# Globals:
#   INDEX_VERSION, LOG_DIR
#######################################
check_cache() {
  if ! uv run keel --help 2> /dev/null | grep -q -E '^ +warm-cache '; then
    record "answer cache" "warn" \
      "pending stage 15 (keel warm-cache is absent)"
    return
  fi
  if [[ -z "${INDEX_VERSION}" ]]; then
    record "answer cache" "fail" "no index version to compute the cache keys"
    return
  fi
  local counts log="${LOG_DIR}/preflight_cache.log"
  if ! counts="$(count_cached "${INDEX_VERSION}" 2> "${log}")"; then
    record "answer cache" "fail" "the count failed; see ${log}"
    return
  fi
  local found="" total=""
  read -r found total <<< "${counts}" || true
  if [[ ! "${found}" =~ ^[0-9]+$ || ! "${total}" =~ ^[0-9]+$ ]]; then
    record "answer cache" "fail" "unexpected count output; see ${log}"
    return
  fi
  if [[ "${total}" -ne "${GOLDEN_QUESTIONS}" ]]; then
    record "answer cache" "warn" \
      "the golden set has ${total} questions, the checklist expects 28"
  fi
  if [[ "${found}" -ge "${total}" && "${total}" -gt 0 ]]; then
    record "answer cache" "pass" "${found} of ${total} golden questions cached"
  else
    record "answer cache" "fail" \
      "${found} of ${total} golden questions cached; run keel warm-cache"
  fi
}

#######################################
# Item 7: the recording and the static export exist (a warning when absent).
#######################################
check_fallbacks() {
  if [[ -s demo/recording.mp4 ]]; then
    record "recording" "pass" "demo/recording.mp4 present; play it once"
  elif [[ -s demo/recording.webm ]]; then
    record "recording" "warn" \
      "draft webm present; convert to recording.mp4"
  else
    record "recording" "warn" "demo/recording.mp4 missing"
  fi
  if [[ -d demo/static ]] && [[ -n "$(ls -A demo/static 2> /dev/null)" ]]; then
    record "static export" "pass" "demo/static/ present; open it once"
  else
    record "static export" "warn" "demo/static/ missing or empty"
  fi
}

#######################################
# Print the summary table and the manual items.
# Outputs:
#   The table on stdout.
# Returns:
#   1 when a check failed, else 0.
#######################################
summarize() {
  local passes=0 warns=0 fails=0 i
  echo
  echo "| Check | Result | Detail |"
  echo "| --- | --- | --- |"
  for i in "${!CHECK_NAMES[@]}"; do
    echo "| ${CHECK_NAMES[i]} | ${CHECK_STATUSES[i]} | ${CHECK_DETAILS[i]} |"
    case "${CHECK_STATUSES[i]}" in
      pass) passes=$((passes + 1)) ;;
      warn) warns=$((warns + 1)) ;;
      *) fails=$((fails + 1)) ;;
    esac
  done
  echo
  echo "pass ${passes}, warn ${warns}, fail ${fails}"
  echo
  echo "Manual items of chapter 21.1:"
  echo "- run the 3 example questions live and read every citation once"
  echo "- block the provider host for 1 question and confirm the offline drill"
  echo "- play demo/recording.mp4 and open demo/static/"
  echo "- print the 3 answers"
  echo "- caffeinate -dims, power connected"
  echo "- close other apps, mute notifications, browser zoom 125%"
  echo "- hotspot on standby, tested once"
  echo "- the request ID of the last live answer on a sticky note"
  if [[ "${fails}" -gt 0 ]]; then
    return 1
  fi
  return 0
}

#######################################
# Run every check from the repository root and print the summary.
# Globals:
#   LOG_DIR (set)
# Arguments:
#   The script arguments.
#######################################
main() {
  parse_args "$@"
  cd "$(dirname "$0")/.."
  LOG_DIR="logs"
  mkdir -p "${LOG_DIR}"
  check_tests
  check_doctor
  check_disk
  check_serve
  check_health
  check_ready
  check_cache
  check_fallbacks
  summarize
}

main "$@"
