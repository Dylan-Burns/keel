#!/bin/bash
#
# First-boot setup for the Keel pilot host: Docker, the compose plugin, the
# AWS CLI for backups, and the /opt/keel directory. The application itself
# arrives through deploy.yml.

set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

main() {
  apt-get update
  apt-get install -y --no-install-recommends \
    docker.io docker-compose-v2 awscli unattended-upgrades
  systemctl enable --now docker
  usermod -aG docker ubuntu

  mkdir -p /opt/keel/corpus /opt/keel/index /opt/keel/cache /opt/keel/logs
  chown -R ubuntu:ubuntu /opt/keel

  # Keep the host patched without a reboot loop; Caddy and Docker restart on demand.
  dpkg-reconfigure -f noninteractive unattended-upgrades
}

main "$@"
