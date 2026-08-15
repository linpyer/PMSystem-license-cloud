#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ -z "${DDREC_ROOT:-}" && -d /opt/pmsystem-license/config && ! -d /opt/ddrec-license/config ]]; then
  DDREC_ROOT=/opt/pmsystem-license
fi
DDREC_ROOT="${DDREC_ROOT:-/opt/ddrec-license}"
ENV_FILE="${DDREC_ENV_FILE:-${DDREC_ROOT}/config/.env.production}"
CURRENT_LINK="${DDREC_ROOT}/current"
SCRIPT_RELEASE_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ -f "${SCRIPT_RELEASE_ROOT}/compose.yml" ]]; then
  RELEASE_ROOT="${SCRIPT_RELEASE_ROOT}"
elif [[ -L "${CURRENT_LINK}" || -d "${CURRENT_LINK}" ]]; then
  RELEASE_ROOT="$(readlink -f "${CURRENT_LINK}")"
else
  RELEASE_ROOT="${SCRIPT_RELEASE_ROOT}"
fi
COMPOSE_FILE="${DDREC_COMPOSE_FILE:-${RELEASE_ROOT}/compose.yml}"

log() { printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*"; }
fail() { log "ERROR: $*" >&2; exit 1; }
require_root() { [[ "${EUID}" -eq 0 ]] || fail "Run this command as root"; }
require_command() { command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"; }
require_file() { [[ -f "$1" ]] || fail "Required file not found: $1"; }
require_directory() { [[ -d "$1" ]] || fail "Required directory not found: $1"; }
require_value() { local name="$1"; [[ -n "${!name:-}" ]] || fail "Required value is empty: ${name}"; }

assert_production_root() {
  case "${DDREC_ROOT}" in
    /opt/ddrec-license|/opt/pmsystem-license) ;;
    *) fail "Unsafe production root: ${DDREC_ROOT}" ;;
  esac
}

assert_backup_directory() {
  local directory="$1"
  assert_production_root
  [[ "${directory}" == "${DDREC_ROOT}/backups" ]] \
    || fail "Unsafe backup directory: ${directory}"
}

load_environment() {
  require_file "${ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  DDREC_ADMIN_ROOT="${DDREC_ADMIN_ROOT:-/var/www/ddrec-license/admin}"
  DDREC_LICENSE_NGINX_CONF="${DDREC_LICENSE_NGINX_CONF:-/etc/nginx/conf.d/ddrec-license.conf}"
  DDREC_LICENSE_SIGNING_PRIVATE_KEY_HOST_PATH="${DDREC_LICENSE_SIGNING_PRIVATE_KEY_HOST_PATH:-${DDREC_ROOT}/secrets/production_ed25519_private.pem}"
  export DDREC_ENV_FILE="${ENV_FILE}"
}

compose() {
  require_file "${COMPOSE_FILE}"
  docker compose --project-directory "${RELEASE_ROOT}" --env-file "${ENV_FILE}" -f "${COMPOSE_FILE}" "$@"
}

wait_for_health() {
  local service="$1" timeout_seconds="${2:-120}" container_id status started
  container_id="$(compose ps -q "${service}")"
  [[ -n "${container_id}" ]] || fail "Container was not created for ${service}"
  started="$(date +%s)"
  while true; do
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container_id}")"
    [[ "${status}" == "healthy" ]] && return 0
    [[ "${status}" == "exited" || "${status}" == "dead" || "${status}" == "unhealthy" ]] && fail "${service} is ${status}"
    (( $(date +%s) - started < timeout_seconds )) || fail "Timed out waiting for ${service} health"
    sleep 2
  done
}

check_private_key() {
  local path="${DDREC_LICENSE_SIGNING_PRIVATE_KEY_HOST_PATH:-${DDREC_ROOT}/secrets/production_ed25519_private.pem}" owner group mode
  require_file "${path}"
  owner="$(stat -c '%u' "${path}")"
  group="$(stat -c '%g' "${path}")"
  mode="$(stat -c '%a' "${path}")"
  [[ "${owner}" == "0" ]] || fail "Private key owner must be root (uid 0), got uid ${owner}"
  [[ "${group}" == "10001" ]] || fail "Private key group must be gid 10001, got gid ${group}"
  [[ "${mode}" == "640" ]] || fail "Private key mode must be 640, got ${mode}"
}

verify_private_key_readable() {
  local path="${DDREC_LICENSE_SIGNING_PRIVATE_KEY_HOST_PATH:-${DDREC_ROOT}/secrets/production_ed25519_private.pem}"
  require_command docker
  require_value DDREC_API_IMAGE_TAG
  check_private_key
  docker image inspect "ddrec-license-api:${DDREC_API_IMAGE_TAG}" >/dev/null 2>&1 \
    || fail "API image is not loaded: ddrec-license-api:${DDREC_API_IMAGE_TAG}"
  docker run --rm --pull never \
    --user 10001:10001 \
    --entrypoint python \
    --volume "${path}:/run/secrets/license_signing_private_key.pem:ro" \
    "ddrec-license-api:${DDREC_API_IMAGE_TAG}" \
    -c "from pathlib import Path; Path('/run/secrets/license_signing_private_key.pem').read_bytes(); print('signing key readable')" \
    || fail "The license-api runtime user cannot read the production signing key"
}
