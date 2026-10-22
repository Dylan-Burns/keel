#!/bin/bash
#
# Deploy a released Keel image on the AWS pilot host (D-39). deploy-aws.yml
# runs this script as root through SSM Run Command; an engineer can run it
# by hand the same way. It is safe to run again: each step skips what is
# already in place.
#
# Steps: fetch the compose file, the Caddyfile, the backup script, and the
# systemd units of the release tag; pull the image; on the first run, fetch
# the corpus (release corpus-v1), the models, and the index (release
# index-v1, restored by `keel restore`); start the app and Caddy; wait for
# the new version on /api/health; enable the nightly timers.
#
# Usage: deploy_host.sh VERSION      (for example 0.2.1)
# Needs /opt/keel/.env with ANTHROPIC_API_KEY, KEEL_API_TOKEN, KEEL_HOSTNAME,
# and KEEL_BACKUP_BUCKET (infra/README.md).

set -euo pipefail

readonly REPO="Dylan-Burns/keel"
readonly IMAGE="ghcr.io/dylan-burns/keel"
readonly ROOT="/opt/keel"
readonly RAW="https://raw.githubusercontent.com/${REPO}"
readonly RELEASES="https://github.com/${REPO}/releases/download"

#######################################
# Print a progress line.
# Arguments:
#   message
#######################################
log() {
  echo "deploy: $*"
}

#######################################
# Download the deploy files of the release tag into ROOT.
# Arguments:
#   version
#######################################
fetch_files() {
  local version="$1"
  local file
  mkdir -p "${ROOT}/infra/systemd"
  for file in docker-compose.yml infra/Caddyfile infra/backup.sh \
    infra/systemd/keel-refresh.service infra/systemd/keel-refresh.timer \
    infra/systemd/keel-backup.service infra/systemd/keel-backup.timer; do
    curl -fsSL "${RAW}/v${version}/${file}" -o "${ROOT}/${file}"
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
  log "fetching the corpus"
  mkdir -p "${dest}"
  curl -fsSL "${RELEASES}/corpus-v1/edgar_corpus.zip" -o "${ROOT}/cache/corpus.zip"
  python3 - "${ROOT}/cache/corpus.zip" "${dest}" <<'PY'
import pathlib, sys, zipfile
archive, dest = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(archive) as z:
    for name in z.namelist():
        if "/" in name or "\\" in name or name.startswith("."):
            raise SystemExit(f"unexpected member {name!r}")
        (dest / name).write_bytes(z.read(name))
PY
  rm -f "${ROOT}/cache/corpus.zip"
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
  log "restoring the index from release index-v1"
  local name
  name="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/tags/index-v1" |
    python3 -c 'import json, sys
names = [a["name"] for a in json.load(sys.stdin)["assets"]]
print([n for n in names if n.endswith(".tar.gz")][0])')"
  curl -fsSL "${RELEASES}/index-v1/${name}" -o "${ROOT}/cache/${name}"
  curl -fsSL "${RELEASES}/index-v1/${name}.sha256" -o "${ROOT}/cache/${name}.sha256"
  chown -R "${APP_UID}:${APP_UID}" "${ROOT}/cache"
  keel_run app restore "/app/cache/${name}"
  rm -f "${ROOT}/cache/${name}" "${ROOT}/cache/${name}.sha256"
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
  local version="${1:?usage: deploy_host.sh VERSION}"
  if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "version must look like 1.2.3" >&2
    exit 1
  fi
  if [[ ! -f "${ROOT}/.env" ]]; then
    echo "${ROOT}/.env is missing (infra/README.md)" >&2
    exit 1
  fi
  cd "${ROOT}"
  mkdir -p corpus index cache logs demo/answer_cache
  fetch_files "${version}"
  set_image "${version}"
  log "pulling ${IMAGE}:${version}"
  docker compose pull app
  APP_UID="$(docker run --rm --entrypoint id "${IMAGE}:${version}" -u)"
  readonly APP_UID
  chown -R "${APP_UID}:${APP_UID}" index cache logs demo
  ensure_corpus
  ensure_models
  ensure_index
  chown -R "${APP_UID}:${APP_UID}" index cache logs demo
  docker compose --profile production up -d --remove-orphans
  wait_healthy "${version}"
  enable_timers
}

main "$@"
