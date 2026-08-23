#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
require_root
release_path="$(readlink -f "${1:-${RELEASE_ROOT}}")"

bash "${SCRIPT_DIR}/precheck.sh"
bash "${SCRIPT_DIR}/build-api-image.sh"
require_file "${ENV_FILE}"
load_environment
verify_private_key_readable
bash "${SCRIPT_DIR}/install-release.sh" "${release_path}"

# Refresh paths after current is switched by install-release.
exec_scripts="${DDREC_ROOT}/current/scripts"
load_environment
compose up -d --pull never postgres
wait_for_health postgres 120
bash "${exec_scripts}/migrate.sh"
bash "${exec_scripts}/register-signing-key.sh"
bash "${exec_scripts}/start.sh"
nginx -t
systemctl reload nginx
bash "${exec_scripts}/verify.sh"
log "HTTP deployment completed. Apply Certbot only after DNS and public HTTP checks succeed."
