#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
require_root
load_environment
log "Current release: $(readlink -f "${CURRENT_LINK}" 2>/dev/null || printf 'not installed')"
log "API image: pmsystem-license-api:${PMSYSTEM_API_IMAGE_TAG:-unset}"
compose ps
log "Listening ports:"
ss -lntp | awk 'NR == 1 || $4 ~ /:(80|443|8080|5432)$/' || true
log "Recent API logs:"
compose logs --tail=50 license-api || true
log "Recent PostgreSQL logs:"
compose logs --tail=30 postgres || true
