#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in docker curl; do require_command "${command_name}"; done
load_environment
verify_private_key_readable
require_value DDREC_API_IMAGE_TAG
docker image inspect "ddrec-license-api:${DDREC_API_IMAGE_TAG}" >/dev/null 2>&1 || fail "API image is not loaded"
docker image inspect postgres:17.5-alpine >/dev/null 2>&1 || fail "PostgreSQL image is not loaded"

log "Starting PostgreSQL without registry pulls"
compose up -d --pull never postgres
wait_for_health postgres 120
log "Database is healthy. Run migrate.sh before first API startup or after schema changes."
log "Starting license API without registry pulls"
compose up -d --pull never license-api
wait_for_health license-api 120
curl --fail --silent --show-error http://127.0.0.1:8080/api/v1/health/ready >/dev/null
log "License API is ready on 127.0.0.1:8080"
