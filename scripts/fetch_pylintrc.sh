#!/bin/bash
#
# Vendor Google's pylintrc into the repository root so pylint runs with the
# same configuration locally and in CI. Re-run to refresh; commit the change
# with a `build(deps)` commit and keep any local edits at the top of the file
# in a clearly marked block.

set -euo pipefail

readonly SOURCE_URL="https://google.github.io/styleguide/pylintrc"
readonly TARGET="${1:-pylintrc}"

main() {
  local tmp
  tmp="$(mktemp)"
  curl -fsSL "${SOURCE_URL}" -o "${tmp}"
  {
    echo "# Vendored from ${SOURCE_URL} on $(date -u +%Y-%m-%d) by scripts/fetch_pylintrc.sh."
    echo "# Local edits, if any, are listed below this header and nowhere else."
    echo
    cat "${tmp}"
  } > "${TARGET}"
  rm -f "${tmp}"
  echo "wrote ${TARGET} ($(wc -l < "${TARGET}") lines), sha256 $(sha256sum "${TARGET}" | cut -d' ' -f1)"
}

main "$@"
