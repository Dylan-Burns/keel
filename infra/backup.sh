#!/bin/bash
#
# Nightly backup of the Keel state to an S3 bucket (chapter 27.2).
# Copies a consistent snapshot of the SQLite index, the vectors, the manifest,
# the audit log, and the export log. Restore procedure: infra/README.md.
#
# Required environment (from /opt/keel/.env):
#   KEEL_BACKUP_BUCKET   s3 bucket name
# Optional:
#   KEEL_DATA_DIR        defaults to /opt/keel

set -euo pipefail

readonly DATA_DIR="${KEEL_DATA_DIR:-/opt/keel}"
readonly BUCKET="${KEEL_BACKUP_BUCKET:?KEEL_BACKUP_BUCKET is required}"
STAMP="$(date -u +%Y-%m-%dT%H%M%SZ)"
readonly STAMP
WORK_DIR="$(mktemp -d)"
readonly WORK_DIR

#######################################
# Remove the temporary directory on exit.
# Globals:
#   WORK_DIR
#######################################
cleanup() {
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

#######################################
# Write a consistent copy of the SQLite index with the online backup API.
# Arguments:
#   source path, destination path
#######################################
snapshot_sqlite() {
  local source="$1"
  local dest="$2"
  docker compose -f "${DATA_DIR}/docker-compose.yml" run --rm --no-deps \
    -v "${WORK_DIR}:/backup" app \
    python -c "import sqlite3; src = sqlite3.connect('${source}'); dst = sqlite3.connect('/backup/$(basename "${dest}")'); src.backup(dst); dst.close(); src.close()"
}

main() {
  local index_dir="${DATA_DIR}/index/current"
  local archive="${WORK_DIR}/keel-${STAMP}.tar.gz"
  local members=(chunks.sqlite vectors.npy manifest.json)
  local log

  if [[ ! -d "${index_dir}" ]]; then
    echo "no index at ${index_dir}; nothing to back up" >&2
    exit 1
  fi

  snapshot_sqlite "/app/index/current/chunks.sqlite" "${WORK_DIR}/chunks.sqlite"
  cp "${index_dir}/vectors.npy" "${index_dir}/manifest.json" "${WORK_DIR}/"
  for log in audit.jsonl exports.jsonl; do
    if [[ -f "${DATA_DIR}/logs/${log}" ]]; then
      cp "${DATA_DIR}/logs/${log}" "${WORK_DIR}/"
      members+=("${log}")
    fi
  done

  tar -czf "${archive}" -C "${WORK_DIR}" "${members[@]}"
  sha256sum "${archive}" > "${archive}.sha256"

  aws s3 cp "${archive}" "s3://${BUCKET}/keel/${STAMP}/" --only-show-errors
  aws s3 cp "${archive}.sha256" "s3://${BUCKET}/keel/${STAMP}/" --only-show-errors
  echo "backup ${STAMP} written to s3://${BUCKET}/keel/${STAMP}/"
}

main "$@"
