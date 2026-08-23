#!/usr/bin/env bash
set -Eeuo pipefail

DDREC_ROOT="${DDREC_ROOT:-/opt/pmsystem-license}"
ENV_FILE="${DDREC_ENV_FILE:-${DDREC_ROOT}/config/.env.production}"
CURRENT_LINK="${DDREC_ROOT}/current"
RELEASE_LOG_ROOT="${DDREC_ROOT}/logs/releases"
DEPLOY_LOCK="${DDREC_ROOT}/.deploy.lock"

EXIT_PREFLIGHT=10
EXIT_UPLOAD=20
EXIT_BACKUP=30
EXIT_DEPLOY=40
EXIT_MIGRATION=50
EXIT_HEALTH=60

log() {
  local message="$*"
  printf '[%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "${message}" | tee -a "${SERVER_LOG:-/dev/null}"
}

die() { local code="$1"; shift; log "ERROR: $*" >&2; exit "${code}"; }
require_root() { [[ "${EUID}" -eq 0 ]] || die "${EXIT_PREFLIGHT}" 'must run as root'; }
require_command() { command -v "$1" >/dev/null 2>&1 || die "${EXIT_PREFLIGHT}" "missing command: $1"; }
require_file() { [[ -f "$1" ]] || die "${EXIT_PREFLIGHT}" "missing file: $1"; }
require_dir() { [[ -d "$1" ]] || die "${EXIT_PREFLIGHT}" "missing directory: $1"; }

assert_root() {
  [[ "${DDREC_ROOT}" == '/opt/pmsystem-license' ]] \
    || die "${EXIT_PREFLIGHT}" "production root must remain /opt/pmsystem-license: ${DDREC_ROOT}"
}

load_environment() {
  require_file "${ENV_FILE}"
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
  DDREC_ADMIN_ROOT="${DDREC_ADMIN_ROOT:-/var/www/pmsystem-license/admin}"
  DDREC_LICENSE_NGINX_CONF="${DDREC_LICENSE_NGINX_CONF:-/etc/nginx/conf.d/pmsystem-license.conf}"
  DDREC_DOWNLOADS_HTTP_NGINX_CONF="${DDREC_DOWNLOADS_HTTP_NGINX_CONF:-/etc/nginx/conf.d/ddrec-downloads.conf}"
  DDREC_DOWNLOADS_HTTPS_NGINX_CONF="${DDREC_DOWNLOADS_HTTPS_NGINX_CONF:-/etc/nginx/conf.d/ddrec-downloads-https.conf}"
  export DDREC_ADMIN_ROOT DDREC_LICENSE_NGINX_CONF DDREC_DOWNLOADS_HTTP_NGINX_CONF DDREC_DOWNLOADS_HTTPS_NGINX_CONF
}

compose_at() {
  local release="$1" env="$2"
  shift 2
  docker compose --project-directory "${release}" --env-file "${env}" -f "${release}/compose.yml" "$@"
}

container_health() {
  local container="$1"
  docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "${container}"
}

wait_healthy() {
  local release="$1" env="$2" service="$3" timeout="${4:-120}" id status started
  id="$(compose_at "${release}" "${env}" ps -q "${service}")"
  [[ -n "${id}" ]] || die "${EXIT_HEALTH}" "container missing: ${service}"
  started="$(date +%s)"
  while true; do
    status="$(container_health "${id}")"
    [[ "${status}" == healthy ]] && return 0
    [[ "${status}" =~ ^(unhealthy|exited|dead)$ ]] && die "${EXIT_HEALTH}" "${service} is ${status}"
    (( $(date +%s) - started < timeout )) || die "${EXIT_HEALTH}" "timeout waiting for ${service}"
    sleep 2
  done
}

database_counts() {
  local release="$1" env="$2"
  compose_at "${release}" "${env}" exec -T postgres sh -lc \
    'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F "="' <<'SQL'
SELECT 'owners',count(*) FROM admin_users WHERE role='OWNER'
UNION ALL SELECT 'licenses',count(*) FROM licenses
UNION ALL SELECT 'device_bindings',count(*) FROM device_bindings
UNION ALL SELECT 'license_events',count(*) FROM license_events
UNION ALL SELECT 'device_trials',count(*) FROM device_trials
UNION ALL SELECT 'admin_audit_events',count(*) FROM admin_audit_events
UNION ALL SELECT 'client_releases',count(*) FROM client_releases;
SQL
}

read_env_value() {
  local file="$1" name="$2"
  sed -n "s/^${name}=//p" "${file}" | tail -1
}

safe_session() { [[ "$1" =~ ^[0-9]{8}-[0-9]{6}$ ]] || die "${EXIT_PREFLIGHT}" "invalid session id: $1"; }
