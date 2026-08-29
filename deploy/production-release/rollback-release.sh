#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
[[ $# -eq 2 ]] || die "${EXIT_DEPLOY}" "usage: $0 SESSION BACKUP_DIR"
SESSION_ID="$1" backup="$2"
safe_session "${SESSION_ID}"
[[ "${backup}" == "${DDREC_ROOT}/backups/release-${SESSION_ID}" ]] || die "${EXIT_DEPLOY}" 'unsafe rollback backup path'
[[ ! -e "${backup}/migration-executed" ]] || die "${EXIT_MIGRATION}" 'automatic rollback prohibited after migration'
require_file "${backup}/current-release.txt"
require_file "${backup}/env.production"
load_environment
previous="$(tr -d '\r\n' <"${backup}/current-release.txt")"
[[ "${previous}" == "${DDREC_ROOT}/release/"* ]] || die "${EXIT_DEPLOY}" 'unsafe previous release path'
require_dir "${previous}"
cp -a "${backup}/env.production" "${ENV_FILE}.rollback-${SESSION_ID}"
chmod 0600 "${ENV_FILE}.rollback-${SESSION_ID}"
mv -f "${ENV_FILE}.rollback-${SESSION_ID}" "${ENV_FILE}"
ln -sfn "${previous}" "${CURRENT_LINK}.rollback-${SESSION_ID}"
mv -Tf "${CURRENT_LINK}.rollback-${SESSION_ID}" "${CURRENT_LINK}"
if [[ -f "${backup}/admin.tar.gz" ]]; then
  admin_parent="$(dirname "${DDREC_ADMIN_ROOT}")"
  rm_target="${admin_parent}/.admin-failed-${SESSION_ID}"
  [[ ! -e "${rm_target}" ]] || die "${EXIT_DEPLOY}" 'rollback admin temporary path exists'
  mv "${DDREC_ADMIN_ROOT}" "${rm_target}"
  tar -xzf "${backup}/admin.tar.gz" -C "${admin_parent}"
fi
compose_at "${previous}" "${ENV_FILE}" up -d --no-deps --pull never license-api
wait_healthy "${previous}" "${ENV_FILE}" license-api 120
previous_commit="$(read_env_value "${ENV_FILE}" LICENSE_BUILD_COMMIT)"
previous_api_tag="$(read_env_value "${ENV_FILE}" DDREC_API_IMAGE_TAG)"
[[ -n "${previous_api_tag}" ]] || die "${EXIT_DEPLOY}" 'rollback env does not define DDREC_API_IMAGE_TAG'
previous_api_image="ddrec-license-api:${previous_api_tag}"
bash "${SCRIPT_DIR}/health-check.sh" "${previous_commit}" "${previous_api_image}"
log "automatic application rollback restored ${previous}"
