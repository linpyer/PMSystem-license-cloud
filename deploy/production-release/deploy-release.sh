#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
for cmd in flock docker nginx curl sha256sum tar install rsync sed awk grep; do require_command "${cmd}"; done

SESSION_ID='' archive='' archive_sha='' expected_commit='' approve_migration=false allow_nginx_change=false
while (($#)); do
  case "$1" in
    --session) SESSION_ID="$2"; shift 2 ;;
    --archive) archive="$2"; shift 2 ;;
    --sha256) archive_sha="$2"; shift 2 ;;
    --commit) expected_commit="$2"; shift 2 ;;
    --approve-migration) approve_migration=true; shift ;;
    --allow-nginx-change) allow_nginx_change=true; shift ;;
    *) die "${EXIT_PREFLIGHT}" "unknown argument: $1" ;;
  esac
done
safe_session "${SESSION_ID}"
install -d -m 0750 "${RELEASE_LOG_ROOT}"
SERVER_LOG="${RELEASE_LOG_ROOT}/${SESSION_ID}.log"
exec 9>"${DEPLOY_LOCK}"
flock -n 9 || die "${EXIT_DEPLOY}" 'another production release is running'
log "session=${SESSION_ID}"
load_environment

staging="${DDREC_ROOT}/release/.staging-${SESSION_ID}"
cleanup_staging() { [[ -d "${staging}" ]] && rm -rf -- "${staging}" || true; }
trap cleanup_staging EXIT
bash "${SCRIPT_DIR}/verify-release.sh" "${archive}" "${archive_sha}" "${expected_commit}" "${staging}"
version="$(tr -d '\r\n' <"${staging}/RELEASE-VERSION.txt")"
release_id="${version}-${expected_commit:0:7}"
final="${DDREC_ROOT}/release/${release_id}"

if [[ -d "${final}" ]]; then
  installed_commit="$(tr -d '\r\n' <"${final}/RELEASE-GIT-COMMIT.txt")"
  [[ "${installed_commit}" == "${expected_commit}" ]] || die "${EXIT_DEPLOY}" 'immutable release directory conflict'
  rm -rf -- "${staging}"
elif [[ -e "${final}" ]]; then
  die "${EXIT_DEPLOY}" 'immutable release path exists and is not a directory'
else
  mv "${staging}" "${final}"
fi
trap - EXIT

current="$(readlink -f "${CURRENT_LINK}")"
if [[ "${current}" == "${final}" ]] && curl -fsS https://license.aixcc.top/api/v1/health | grep -Fq "\"buildCommit\":\"${expected_commit}\""; then
  log "release already deployed: ${release_id}"
  exit 0
fi

release_nginx="${final}/nginx/ddrec-license.conf"
if [[ -f "${release_nginx}" && -f "${DDREC_LICENSE_NGINX_CONF}" ]] && ! cmp -s "${release_nginx}" "${DDREC_LICENSE_NGINX_CONF}"; then
  ${allow_nginx_change} || die "${EXIT_DEPLOY}" 'Nginx configuration changed; explicit audited deployment is required'
fi

postgres_container="$(compose_at "${current}" "${ENV_FILE}" ps -q postgres)"
current_postgres_image="$(docker inspect --format '{{.Config.Image}}' "${postgres_container}")"
api_container="$(compose_at "${current}" "${ENV_FILE}" ps -q license-api)"
current_api_image="$(docker inspect --format '{{.Config.Image}}' "${api_container}")"
[[ -n "${current_api_image}" ]] || die "${EXIT_DEPLOY}" 'could not determine current API image'
release_postgres_image="$(awk '/^[[:space:]]*postgres:/{s=1} s && /^[[:space:]]*image:/{gsub(/^[[:space:]]*image:[[:space:]]*/,""); print; exit}' "${final}/compose.yml")"
[[ "${release_postgres_image}" == "${current_postgres_image}" ]] \
  || die "${EXIT_DEPLOY}" "PostgreSQL image change prohibited: ${current_postgres_image} -> ${release_postgres_image}"

bash "${SCRIPT_DIR}/backup-production.sh" "${SESSION_ID}"
backup="${DDREC_ROOT}/backups/release-${SESSION_ID}"
counts_before="${backup}/counts-before.txt"
switch_started=false
migration_executed=false
rollback_on_error() {
  code=$?
  if (( code != 0 )); then
    if ${migration_executed}; then
      log 'deployment failed after Migration; automatic application/database rollback is prohibited'
      log "backup retained at ${backup}; manual compatibility and recovery audit required"
    elif ${switch_started}; then
      log 'deployment failed without Migration; attempting automatic application rollback'
      if bash "${SCRIPT_DIR}/rollback-release.sh" "${SESSION_ID}" "${backup}"; then log 'production restored and healthy'; else log 'automatic rollback failed; manual recovery required'; fi
    fi
  fi
  exit "${code}"
}
trap rollback_on_error ERR
target_api_tag="${version}-${expected_commit:0:7}-production"
target_api_image="ddrec-license-api:${target_api_tag}"
docker build --pull=false \
  --file "${final}/api-source/Dockerfile.offline-upgrade" \
  --tag "${target_api_image}" \
  --build-arg "BASE_API_IMAGE=${current_api_image}" \
  --build-arg "DDREC_VERSION=${version}" \
  --build-arg "DDREC_GIT_COMMIT=${expected_commit}" \
  "${final}/api-source"
image_commit="$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${target_api_image}")"
image_environment="$(docker image inspect --format '{{index .Config.Labels "com.ddrec.environment"}}' "${target_api_image}")"
image_platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "${target_api_image}")"
[[ "${image_commit}" == "${expected_commit}" ]] || die "${EXIT_DEPLOY}" 'server-built API image commit mismatch'
[[ "${image_environment}" == production ]] || die "${EXIT_DEPLOY}" 'server-built API image environment mismatch'
[[ "${image_platform}" == linux/amd64 ]] || die "${EXIT_DEPLOY}" "server-built API image platform mismatch: ${image_platform}"
docker run --rm --entrypoint python "${target_api_image}" -m pip check

new_env="${DDREC_ROOT}/config/.env.production.release-${SESSION_ID}"
cp -a "${ENV_FILE}" "${new_env}"
sed -i \
  -e "s/^DDREC_API_IMAGE_TAG=.*/DDREC_API_IMAGE_TAG=${target_api_tag}/" \
  -e "s/^PMSYSTEM_API_IMAGE_TAG=.*/PMSYSTEM_API_IMAGE_TAG=${target_api_tag}/" \
  -e "s/^LICENSE_SERVICE_VERSION=.*/LICENSE_SERVICE_VERSION=${version}/" \
  -e "s/^LICENSE_BUILD_COMMIT=.*/LICENSE_BUILD_COMMIT=${expected_commit}/" "${new_env}"
chmod 0600 "${new_env}"
compose_at "${final}" "${new_env}" config --quiet

db_current="$(compose_at "${final}" "${new_env}" run --rm --no-deps license-api alembic current 2>/dev/null | sed -n 's/ .*//p' | tail -1)"
db_head="$(compose_at "${final}" "${new_env}" run --rm --no-deps license-api alembic heads 2>/dev/null | sed -n 's/ .*//p' | tail -1)"
[[ -n "${db_current}" && -n "${db_head}" ]] || die "${EXIT_MIGRATION}" 'could not read Alembic revisions'
if [[ "${db_current}" != "${db_head}" ]]; then
  log "pendingMigration=${db_current}->${db_head}"
  ${approve_migration} || die "${EXIT_MIGRATION}" 'pending Migration requires explicit approval'
  compose_at "${final}" "${new_env}" run --rm --no-deps license-api alembic upgrade head
  touch "${backup}/migration-executed"
  migration_executed=true
fi

admin_parent="$(dirname "${DDREC_ADMIN_ROOT}")"
admin_stage="${admin_parent}/.admin-${SESSION_ID}"
[[ ! -e "${admin_stage}" ]] || die "${EXIT_DEPLOY}" 'Admin staging path exists'
install -d -m 0755 "${admin_stage}"
rsync -a --delete "${final}/admin/" "${admin_stage}/"
require_file "${admin_stage}/index.html"

previous="${current}"
switch_started=true
mv -f "${new_env}" "${ENV_FILE}"
ln -sfn "${final}" "${CURRENT_LINK}.new-${SESSION_ID}"
mv -Tf "${CURRENT_LINK}.new-${SESSION_ID}" "${CURRENT_LINK}"
admin_failed="${admin_parent}/.admin-previous-${SESSION_ID}"
mv "${DDREC_ADMIN_ROOT}" "${admin_failed}"
mv "${admin_stage}" "${DDREC_ADMIN_ROOT}"

compose_at "${final}" "${ENV_FILE}" up -d --no-deps --pull never license-api
wait_healthy "${final}" "${ENV_FILE}" license-api 120

if [[ -f "${release_nginx}" ]] && ! cmp -s "${release_nginx}" "${DDREC_LICENSE_NGINX_CONF}"; then
  cp -a "${DDREC_LICENSE_NGINX_CONF}" "${backup}/nginx-before-change.conf"
  install -m 0644 "${release_nginx}" "${DDREC_LICENSE_NGINX_CONF}"
  if ! nginx -t; then cp -a "${backup}/nginx-before-change.conf" "${DDREC_LICENSE_NGINX_CONF}"; nginx -t; die "${EXIT_DEPLOY}" 'new Nginx configuration failed validation'; fi
  systemctl reload nginx
  log 'Nginx configuration changed, validated and reloaded'
else
  log 'Nginx configuration unchanged; reload skipped'
fi

bash "${SCRIPT_DIR}/health-check.sh" "${expected_commit}" "${counts_before}"
trap - ERR
log "release deployed successfully: ${release_id}"
log "previousRelease=${previous}"
log "backup=${backup}"
