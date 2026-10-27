#!/bin/bash
#
# The example request: send 1 business question to Keel through the live
# flow of the web page, and print the answer. Like the page, it streams the
# answer (server-sent events) and skips the answer cache, so the server
# makes exactly 1 model request for it (about 0.10 USD).
#
# Usage: scripts/example_request.sh [--json | --raw] [--url URL] ["question"]
#   --json    print the full final record (answer, retrieval, audit)
#   --raw     print the raw server-sent events as they arrive
#   --url     the base URL of Keel (default http://127.0.0.1:8000); the
#             deployed site works too
#   question  default: the Apple, Tesla, and JPMorgan risk factor question
#
# Without a flag the script shows each stream event on stderr as it arrives,
# then prints a summary: the direct answer, the findings per company, the
# gaps, the citation count, and the audit line with the model request count.
#
# Start the server first: `make demo`, or `uv run keel serve`, with
# ANTHROPIC_API_KEY set and KEEL_OFFLINE unset.
#
# The bearer token comes from KEEL_API_TOKEN in the environment. The script
# never prints it.
#
# Requires: curl, jq.

set -euo pipefail

readonly DEFAULT_QUESTION="What are the primary risk factors facing Apple, \
Tesla, and JPMorgan, and how do they compare?"

# The jq filter of the default summary output.
readonly SUMMARY_FILTER='
"Question: \(.question)",
"Outcome:  \(.outcome)    Confidence: \(.answer.confidence // "n/a")",
"",
(.answer.direct_answer // .message // ""),
"",
(.answer.company_findings // [] | .[] |
  "\(.company) (\(.ticker))",
  (.findings[] |
    "  - \(.point)\(if .unverified then " [unverified]" else "" end)")),
"",
"Gaps:",
(.answer.gaps // [] | .[] | "  - \(.)"),
"",
"Citations validated: \(.citations_resolved // [] | length)",
"Model requests: \(.audit.model_requests)    Model: \(.audit.model)",
"Cost: $\(.audit.cost_usd)    Latency: \(.audit.latency_ms.total) ms",
"Request ID: \(.request_id)"
'

#######################################
# Print the usage line to stderr and exit.
# Arguments:
#   The exit code.
#######################################
usage() {
  echo 'Usage: scripts/example_request.sh [--json | --raw]' \
    '[--url URL] ["question"]' >&2
  exit "$1"
}

#######################################
# Read the stream on stdin, report progress on stderr, and print the final
# record on stdout.
# Outputs:
#   The JSON of the final event.
# Returns:
#   1 when the stream holds an error event or no final event.
#######################################
read_stream() {
  local line name="" deltas=0 final=""
  while IFS= read -r line; do
    line="${line%$'\r'}"
    case "${line}" in
      'event: '*) name="${line#event: }" ;;
      'data: '*)
        if [[ "${name}" == answer_delta ]]; then
          deltas=$((deltas + 1))
          continue
        fi
        if ((deltas > 0)); then
          echo "[answer_delta] x ${deltas}" >&2
          deltas=0
        fi
        case "${name}" in
          final)
            echo '[final] answer complete' >&2
            final="${line#data: }"
            ;;
          error)
            echo "[error] ${line#data: }" >&2
            return 1
            ;;
          done) ;;
          *) echo "[${name}]" >&2 ;;
        esac
        ;;
    esac
  done
  if [[ -z "${final}" ]]; then
    echo 'The stream ended before the answer was complete.' >&2
    return 1
  fi
  printf '%s\n' "${final}"
}

#######################################
# Send the question and print the answer.
# Globals:
#   KEEL_API_TOKEN (read)
# Arguments:
#   The command line.
#######################################
main() {
  local mode=summary
  local base_url=http://127.0.0.1:8000
  local question="${DEFAULT_QUESTION}"

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --json) mode=json ;;
      --raw) mode=raw ;;
      --url)
        [[ $# -ge 2 ]] || usage 2
        base_url="${2%/}"
        shift
        ;;
      -h | --help) usage 0 ;;
      -*) usage 2 ;;
      *) question="$1" ;;
    esac
    shift
  done

  if [[ -z "${KEEL_API_TOKEN:-}" ]]; then
    echo 'KEEL_API_TOKEN is not set. Export it, or run: set -a; . ./.env' >&2
    exit 1
  fi

  # The body of the web page: stream, and never serve the answer cache.
  local body
  body="$(jq -n --arg q "${question}" \
    '{question: $q, options: {use_cache: false}}')"
  local request=(curl -sS -N --fail-with-body -X POST "${base_url}/api/ask"
    -H "Authorization: Bearer ${KEEL_API_TOKEN}"
    -H 'Content-Type: application/json'
    -H 'Accept: text/event-stream'
    -d "${body}")

  if [[ "${mode}" == raw ]]; then
    "${request[@]}"
    return
  fi

  local record
  record="$("${request[@]}" | read_stream)"
  if [[ "${mode}" == json ]]; then
    jq . <<<"${record}"
  else
    echo >&2
    jq -r "${SUMMARY_FILTER}" <<<"${record}"
  fi
}

main "$@"
