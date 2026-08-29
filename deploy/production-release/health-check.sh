#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
[[ $# -ge 2 && $# -le 3 ]] || die "${EXIT_HEALTH}" "usage: $0 EXPECTED_COMMIT EXPECTED_IMAGE [COUNTS_BEFORE]"
expected_commit="$1" expected_image="$2" counts_before="${3:-}"
load_environment
current="$(readlink -f "${CURRENT_LINK}")"
wait_healthy "${current}" "${ENV_FILE}" postgres 60
wait_healthy "${current}" "${ENV_FILE}" license-api 60
compose_at "${current}" "${ENV_FILE}" ps
if ! verify_application_image_identity "${current}" "${ENV_FILE}" "${expected_image}" "${expected_commit}"; then
  die "${EXIT_HEALTH}" 'DEPLOY_SEMANTIC_FAILURE: deployment image identity check failed'
fi
health="$(curl -fsS https://license.aixcc.top/api/v1/health)" || die "${EXIT_HEALTH}" 'public API health failed'
expected_version="$(read_env_value "${ENV_FILE}" LICENSE_SERVICE_VERSION)"
[[ -n "${expected_version}" ]] || die "${EXIT_HEALTH}" 'expected service version is missing from production env'
printf '%s' "${health}" | grep -Fq '"status":"ok"' || die "${EXIT_HEALTH}" 'API status is not ok'
printf '%s' "${health}" | grep -Fq '"database":"ok"' || die "${EXIT_HEALTH}" 'API database is not ok'
printf '%s' "${health}" | grep -Fq "\"version\":\"${expected_version}\"" || die "${EXIT_HEALTH}" 'API version mismatch'
printf '%s' "${health}" | grep -Fq "\"buildCommit\":\"${expected_commit}\"" || die "${EXIT_HEALTH}" 'API buildCommit mismatch'
log "HEALTH_VERSION=${expected_version}"
log "HEALTH_BUILD_COMMIT=${expected_commit}"
admin_http="$(curl -sS -o /dev/null -w '%{http_code}' https://license.aixcc.top/admin/)"
[[ "${admin_http}" == 200 ]] || die "${EXIT_HEALTH}" "Admin HTTP ${admin_http}"
after="$(mktemp)"
trap 'rm -f -- "${after}"' EXIT
database_counts "${current}" "${ENV_FILE}" >"${after}"
owner_count="$(awk -F= '$1=="owners"{print $2}' "${after}")"
(( owner_count >= 1 )) || die "${EXIT_HEALTH}" 'OWNER count is below 1'
if [[ -n "${counts_before}" ]]; then
  require_file "${counts_before}"
  for name in owners licenses device_bindings license_events device_trials admin_audit_events client_releases; do
    before_value="$(awk -F= -v key="${name}" '$1==key{print $2}' "${counts_before}")"
    after_value="$(awk -F= -v key="${name}" '$1==key{print $2}' "${after}")"
    [[ -n "${before_value}" && -n "${after_value}" ]] || die "${EXIT_HEALTH}" "missing core count: ${name}"
    (( after_value >= before_value )) || die "${EXIT_HEALTH}" "core count decreased: ${name} ${before_value}->${after_value}"
  done
fi
log 'production API, PostgreSQL, Admin and core-count health checks passed'
