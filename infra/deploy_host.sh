#!/bin/bash
#
# Deploy a released Keel image on the AWS pilot host (D-39). deploy-aws.yml
# runs this script as root through SSM Run Command; an engineer can run it
# by hand the same way. It is safe to run again: each step skips what is
# already in place.
#
# Steps: copy the compose file, the Caddyfile, the backup script, and the
# systemd units from the release bundle; pull the image; on the first run,
# fetch the corpus and the index archive from the S3 bucket (keel/bootstrap/)
# and the models, and restore the index with `keel restore`; start the app
# and Caddy; wait for the new version on /api/health; enable the nightly
# timers.
#
# Usage: deploy_host.sh VERSION BUNDLE_DIR
#   (for example 0.4.1 /tmp/keel_bundle)
# Needs /opt/keel/.env with ANTHROPIC_API_KEY, KEEL_API_TOKEN, KEEL_HOSTNAME,
# and KEEL_BACKUP_BUCKET (infra/README.md).

set -euo pipefail

readonly IMAGE="ghcr.io/dylan-burns/keel"
readonly ROOT="/opt/keel"
# The repository is private: deploy-aws.yml ships the deploy files as a
# bundle, and the corpus and index archives sit in the S3 bucket.
readonly AWS=/snap/bin/aws

#######################################
# Print a progress line.
# Arguments:
#   message
#######################################
log() {
  echo "deploy: $*"
}

#######################################
# Copy the deploy files of the release bundle into ROOT.
# Arguments:
#   bundle directory
#######################################
fetch_files() {
  local bundle="$1"
  local file
  mkdir -p "${ROOT}/infra/systemd"
  for file in docker-compose.yml infra/Caddyfile infra/backup.sh \
    infra/systemd/keel-refresh.service infra/systemd/keel-refresh.timer \
    infra/systemd/keel-backup.service infra/systemd/keel-backup.timer; do
    cp "${bundle}/${file}" "${ROOT}/${file}"
  done
  chmod 755 "${ROOT}/infra/backup.sh"
}

#######################################
# Point KEEL_IMAGE in .env at the release, so the app and the timers use it.
# Arguments:
#   version
#######################################
set_image() {
  local version="$1"
  local env_file="${ROOT}/.env"
  if grep -q '^KEEL_IMAGE=' "${env_file}"; then
    sed -i "s#^KEEL_IMAGE=.*#KEEL_IMAGE=${IMAGE}:${version}#" "${env_file}"
  else
    echo "KEEL_IMAGE=${IMAGE}:${version}" >>"${env_file}"
  fi
}

#######################################
# Run a keel command in a one-off app container.
# Arguments:
#   extra docker compose run options and the keel arguments
#######################################
keel_run() {
  docker compose run --rm --no-deps "$@"
}

#######################################
# Extract the corpus zip of release corpus-v1 when the corpus is absent.
#######################################
ensure_corpus() {
  local dest="${ROOT}/corpus/edgar"
  if [[ -f "${dest}/manifest.json" ]]; then
    return
  fi
  log "fetching the corpus from the bucket"
  # Root runs this step, and the app can write corpus/, so the zip lands in
  # a root-only temp dir and every write refuses to follow a symlink.
  if [[ -L "${ROOT}/corpus" || -L "${dest}" ]]; then
    echo "corpus path is a symlink; refusing to extract" >&2
    exit 1
  fi
  mkdir -p "${dest}"
  local tmp
  tmp="$(mktemp -d)"
  "${AWS}" s3 cp --only-show-errors \
    "s3://${BUCKET}/keel/bootstrap/edgar_corpus.zip" "${tmp}/corpus.zip"
  python3 - "${tmp}/corpus.zip" "${dest}" <<'PY'
import os, sys, zipfile
archive, dest = sys.argv[1], sys.argv[2]
flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
with zipfile.ZipFile(archive) as z:
    for name in z.namelist():
        if "/" in name or "\\" in name or name.startswith("."):
            raise SystemExit(f"unexpected member {name!r}")
        fd = os.open(os.path.join(dest, name), flags, 0o644)
        with os.fdopen(fd, "wb") as out:
            out.write(z.read(name))
PY
  rm -r "${tmp}"
}

#######################################
# Download the pinned models into the cache volume when absent.
#######################################
ensure_models() {
  if [[ -d "${ROOT}/cache/hf/hub" ]]; then
    return
  fi
  log "downloading the models"
  # doctor exits non-zero on unrelated checks, so test the cache instead.
  keel_run -e HF_HUB_OFFLINE=0 app doctor --download-models || true
  if [[ ! -d "${ROOT}/cache/hf/hub" ]]; then
    echo "the model download failed" >&2
    exit 1
  fi
}

#######################################
# Restore the index archive of release index-v1 when no build is current.
#######################################
ensure_index() {
  if [[ -e "${ROOT}/index/current" ]]; then
    return
  fi
  log "restoring the index from the bucket (index-v1)"
  local name
  name="$("${AWS}" s3 ls "s3://${BUCKET}/keel/bootstrap/index-v1/" |
    awk '$4 ~ /\.tar\.gz$/ {print $4}' | sort | tail -n 1)"
  # Root downloads into its own temp dir (not the app's cache/), which the
  # restore container reads through a read-only mount.
  local tmp
  tmp="$(mktemp -d)"
  "${AWS}" s3 cp --only-show-errors \
    "s3://${BUCKET}/keel/bootstrap/index-v1/${name}" "${tmp}/${name}"
  "${AWS}" s3 cp --only-show-errors \
    "s3://${BUCKET}/keel/bootstrap/index-v1/${name}.sha256" \
    "${tmp}/${name}.sha256"
  chmod 755 "${tmp}"
  chmod 644 "${tmp}/${name}" "${tmp}/${name}.sha256"
  keel_run -v "${tmp}:/restore:ro" app restore "/restore/${name}"
  rm -r "${tmp}"
}

#######################################
# Wait until /api/health reports the version.
# Arguments:
#   version
#######################################
wait_healthy() {
  local version="$1"
  local _
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8000/api/health | grep -q "\"${version}\""; then
      log "version ${version} is live"
      return
    fi
    sleep 5
  done
  log "version ${version} did not answer within 5 minutes"
  docker compose logs --tail 50 app
  return 1
}

#######################################
# Install and start the nightly refresh and backup timers.
#######################################
enable_timers() {
  cp "${ROOT}"/infra/systemd/keel-* /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now keel-refresh.timer keel-backup.timer
}

main() {
  local version="${1:?usage: deploy_host.sh VERSION BUNDLE_DIR}"
  local bundle="${2:?usage: deploy_host.sh VERSION BUNDLE_DIR}"
  if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "version must look like 1.2.3" >&2
    exit 1
  fi
  if [[ ! -f "${ROOT}/.env" ]]; then
    echo "${ROOT}/.env is missing (infra/README.md)" >&2
    exit 1
  fi
  cd "${ROOT}"
  BUCKET="$(sed -n 's/^KEEL_BACKUP_BUCKET=//p' .env)"
  readonly BUCKET
  mkdir -p corpus index cache logs state demo/answer_cache
  fetch_files "${bundle}"
  set_image "${version}"
  log "pulling ${IMAGE}:${version}"
  docker compose pull app
  APP_UID="$(docker run --rm --entrypoint id "${IMAGE}:${version}" -u)"
  readonly APP_UID
  chown -R "${APP_UID}:${APP_UID}" index cache logs state demo
  # The company dictionary starts as the image's copy; keel add extends it
  # in state/, which survives deploys. The app user copies it inside a
  # container, so root never writes into state/, which the app controls.
  docker run --rm --user "${APP_UID}" -v "${ROOT}/state:/app/state" \
    --entrypoint cp "${IMAGE}:${version}" -n /app/config/companies.yaml \
    /app/state/companies.yaml
  ensure_corpus
  ensure_models
  ensure_index
  chown -R "${APP_UID}:${APP_UID}" corpus index cache logs state demo
  docker compose --profile production up -d --remove-orphans
  wait_healthy "${version}"
  enable_timers
}

main "$@"
