#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
require_command docker
load_environment
check_private_key
log "Ensuring PostgreSQL is running without registry pulls"
compose up -d --pull never postgres
wait_for_health postgres 120
log "Current Alembic revision before upgrade:"
compose run --rm --no-deps license-api alembic current
log "Applying Alembic upgrade head"
compose run --rm --no-deps license-api alembic upgrade head
log "Alembic revision after upgrade:"
compose run --rm --no-deps license-api alembic current
log "Database migration completed. No downgrade was run."
