#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
require_root
load_environment
verify_private_key_readable
compose up -d --pull never
wait_for_health postgres 120
wait_for_health license-api 120
log "Services reconciled with the current Compose configuration and image tag."
