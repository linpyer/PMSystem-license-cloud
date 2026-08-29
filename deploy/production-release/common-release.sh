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

# Docker Compose gives exported shell variables precedence over --env-file.
# Keep every production compose substitution, plus application identity values
# carried by the service env file, out of the compose subprocess environment so
# the explicitly selected release env file remains the sole source of truth.
COMPOSE_MANAGED_ENV_VARS=(
  DDREC_API_IMAGE_TAG
  DDREC_COMPOSE_PROJECT_NAME
  DDREC_ENV_FILE
  DDREC_LICENSE_SIGNING_PRIVATE_KEY_HOST_PATH
  DDREC_POSTGRES_VOLUME_NAME
  DDREC_UPDATE_DOWNLOAD_ROOT_HOST
  DDREC_UPDATE_SIGNING_PUBLIC_KEY_HOST_PATH
  POSTGRES_DB
  POSTGRES_PASSWORD
  POSTGRES_USER
  LICENSE_SERVICE_VERSION
  LICENSE_BUILD_COMMIT
)

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
  (
    local name
    for name in "${COMPOSE_MANAGED_ENV_VARS[@]}"; do
      unset "${name}"
    done
    docker compose --project-directory "${release}" --env-file "${env}" -f "${release}/compose.yml" "$@"
  )
}

verify_application_image_identity() {
  local release="$1" env="$2" expected_image="$3" expected_commit="$4"
  local compose_images compose_image container running_image running_image_id
  local expected_image_id oci_revision output code
  require_file "${SCRIPT_DIR}/verify-api-image-identity.py"

  compose_images="$(compose_at "${release}" "${env}" config --images)"
  compose_image="$(printf '%s\n' "${compose_images}" | grep '^ddrec-license-api:' || true)"
  [[ "$(printf '%s\n' "${compose_image}" | sed '/^$/d' | wc -l)" -eq 1 ]] \
    || die "${EXIT_DEPLOY}" 'could not resolve exactly one API image from Compose'
  container="$(compose_at "${release}" "${env}" ps -q license-api)"
  [[ -n "${container}" ]] || die "${EXIT_DEPLOY}" 'license-api container is missing'
  running_image="$(docker inspect --format '{{.Config.Image}}' "${container}")"
  running_image_id="$(docker inspect --format '{{.Image}}' "${container}")"
  expected_image_id="$(docker image inspect --format '{{.Id}}' "${expected_image}")"
  oci_revision="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${running_image_id}")"

  set +e
  output="$(python3 "${SCRIPT_DIR}/verify-api-image-identity.py" \
    --expected-image "${expected_image}" \
    --compose-image "${compose_image}" \
    --running-image "${running_image}" \
    --running-image-id "${running_image_id}" \
    --expected-image-id "${expected_image_id}" \
    --oci-revision "${oci_revision}" \
    --expected-commit "${expected_commit}" 2>&1)"
  code=$?
  set -e
  [[ -n "${output}" ]] && printf '%s\n' "${output}" | tee -a "${SERVER_LOG:-/dev/null}"
  (( code == 0 )) || return "${code}"
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
