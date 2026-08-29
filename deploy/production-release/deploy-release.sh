#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
for cmd in flock docker nginx curl sha256sum tar install rsync sed awk grep python3; do require_command "${cmd}"; done

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
export SERVER_LOG

staging="${DDREC_ROOT}/release/.staging-${SESSION_ID}"
new_env=''
uploaded=true
backup_created=false
release_installed=false
container_recreated=false
current_switched=false
database_modified=false
admin_replaced=false
deployment_identity_verified=false
deployment_succeeded=false
rollback_attempted=false
rollback_healthy=false
report_state() {
  log "DDREC_STATE Uploaded=${uploaded} BackupCreated=${backup_created} ReleaseInstalled=${release_installed} ContainerRecreated=${container_recreated} DeploymentIdentityVerified=${deployment_identity_verified} DeploymentSucceeded=${deployment_succeeded} CurrentSwitched=${current_switched} DatabaseModified=${database_modified} MigrationExecuted=${migration_executed:-false} AdminReplaced=${admin_replaced} RollbackAttempted=${rollback_attempted} RollbackHealthy=${rollback_healthy}"
}
cleanup_ephemeral() {
  [[ -n "${staging}" && -d "${staging}" ]] && rm -rf -- "${staging}" || true
  if [[ -n "${new_env}" && -f "${new_env}" && "${current_switched}" == false ]]; then rm -f -- "${new_env}"; fi
}
on_exit() {
  code=$?
  cleanup_ephemeral
  report_state
  exit "${code}"
}
trap on_exit EXIT
bash "${SCRIPT_DIR}/verify-release.sh" "${archive}" "${archive_sha}" "${expected_commit}" "${staging}"
version="$(tr -d '\r\n' <"${staging}/RELEASE-VERSION.txt")"
release_id="${version}-${expected_commit:0:7}"
final="${DDREC_ROOT}/release/${release_id}"
target_api_tag="${version}-${expected_commit:0:7}-production"
target_api_image="ddrec-license-api:${target_api_tag}"

if [[ -d "${final}" ]]; then
  installed_commit="$(tr -d '\r\n' <"${final}/RELEASE-GIT-COMMIT.txt")"
  [[ "${installed_commit}" == "${expected_commit}" ]] || die "${EXIT_DEPLOY}" 'immutable release directory conflict'
  installed_version="$(tr -d '\r\n' <"${final}/RELEASE-VERSION.txt")"
  [[ "${installed_version}" == "${version}" ]] || die "${EXIT_DEPLOY}" 'immutable release version conflict'
  python3 "${SCRIPT_DIR}/verify-immutable-release.py" \
    --installed "${final}" --staging "${staging}" --archive-sha "${archive_sha}" \
    || die "${EXIT_DEPLOY}" 'immutable release content conflict'
  rm -rf -- "${staging}"
elif [[ -e "${final}" ]]; then
  die "${EXIT_DEPLOY}" 'immutable release path exists and is not a directory'
else
  printf '%s\n' "${archive_sha,,}" >"${staging}/.DDREC-ARCHIVE-SHA256"
  chmod 0444 "${staging}/.DDREC-ARCHIVE-SHA256"
  mv "${staging}" "${final}"
  release_installed=true
fi
staging=''

current="$(readlink -f "${CURRENT_LINK}")"
if [[ "${current}" == "${final}" ]] && curl -fsS https://license.aixcc.top/api/v1/health | grep -Fq "\"buildCommit\":\"${expected_commit}\""; then
  if verify_application_image_identity "${final}" "${ENV_FILE}" "${target_api_image}" "${expected_commit}"; then
    deployment_identity_verified=true
    deployment_succeeded=true
    log "release already deployed with verified image identity: ${release_id}"
    exit 0
  fi
  die "${EXIT_DEPLOY}" 'DEPLOY_SEMANTIC_FAILURE: current release health metadata matches but image identity does not'
fi

${allow_nginx_change} && die "${EXIT_DEPLOY}" '--allow-nginx-change is disabled for application releases; use the separate audited Nginx deployment workflow'
nginx_changed=false
audit_nginx_config() {
  local name="$1" expected="$2" active="$3" audit_output='' audit_code=0
  set +e
  audit_output="$(python3 "${SCRIPT_DIR}/audit-nginx-config.py" \
    --name "${name}" --expected "${expected}" --active "${active}" 2>&1)"
  audit_code=$?
  set -e
  [[ -n "${audit_output}" ]] && printf '%s\n' "${audit_output}" | tee -a "${SERVER_LOG}"
  if (( audit_code == EXIT_DEPLOY )); then
    nginx_changed=true
  elif (( audit_code != 0 )); then
    die "${EXIT_PREFLIGHT}" "Nginx comparison failed for ${name} with exit ${audit_code}"
  fi
}
audit_nginx_config 'ddrec-downloads-http.conf' \
  "${final}/nginx/ddrec-downloads-http.conf" "${DDREC_DOWNLOADS_HTTP_NGINX_CONF}"
audit_nginx_config 'ddrec-downloads-https.conf' \
  "${final}/nginx/ddrec-downloads-https.conf.template" "${DDREC_DOWNLOADS_HTTPS_NGINX_CONF}"
log 'nginxConfig=ddrec-license.conf policy=bootstrap-template excludedFromProductionComparison=true'
${nginx_changed} && die "${EXIT_DEPLOY}" 'Nginx semantic configuration changed; separate explicit audited deployment is required'

postgres_container="$(compose_at "${current}" "${ENV_FILE}" ps -q postgres)"
current_postgres_image_raw="$(docker inspect --format '{{.Config.Image}}' "${postgres_container}")"
current_postgres_image_id="$(docker inspect --format '{{.Image}}' "${postgres_container}")"
current_postgres_repo_digests="$(docker image inspect --format '{{json .RepoDigests}}' "${current_postgres_image_id}")"
api_container="$(compose_at "${current}" "${ENV_FILE}" ps -q license-api)"
current_api_image="$(docker inspect --format '{{.Config.Image}}' "${api_container}")"
[[ -n "${current_api_image}" ]] || die "${EXIT_DEPLOY}" 'could not determine current API image'
release_postgres_image_raw="$(awk '/^[[:space:]]*postgres:/{s=1} s && /^[[:space:]]*image:/{gsub(/^[[:space:]]*image:[[:space:]]*/,""); print; exit}' "${final}/compose.yml")"
printf -v current_postgres_image_q '%q' "${current_postgres_image_raw}"
printf -v release_postgres_image_q '%q' "${release_postgres_image_raw}"
log "PostgreSQLCurrentShellEscaped=${current_postgres_image_q} TargetShellEscaped=${release_postgres_image_q}"
set +e
postgres_guard_output="$(python3 "${SCRIPT_DIR}/verify-postgres-image.py" \
  --current "${current_postgres_image_raw}" \
  --target "${release_postgres_image_raw}" \
  --current-image-id "${current_postgres_image_id}" \
  --current-repo-digests "${current_postgres_repo_digests}" 2>&1)"
postgres_guard_code=$?
set -e
[[ -n "${postgres_guard_output}" ]] && printf '%s\n' "${postgres_guard_output}" | tee -a "${SERVER_LOG}"
if (( postgres_guard_code == EXIT_DEPLOY )); then
  die "${EXIT_DEPLOY}" 'PostgreSQL image change prohibited; use the separate database maintenance workflow'
elif (( postgres_guard_code != 0 )); then
  die "${EXIT_DEPLOY}" 'Unable to verify PostgreSQL image identity'
fi

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
      rollback_attempted=true
      if bash "${SCRIPT_DIR}/rollback-release.sh" "${SESSION_ID}" "${backup}"; then rollback_healthy=true; log 'production restored and healthy'; else log 'automatic rollback failed; manual recovery required'; fi
    fi
  fi
  exit "${code}"
}
trap rollback_on_error ERR
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
pending_migration=false
if [[ "${db_current}" != "${db_head}" ]]; then
  log "pendingMigration=${db_current}->${db_head}"
  audit_output=''
  set +e
  audit_output="$(python3 "${SCRIPT_DIR}/audit-pending-migrations.py" \
    --versions "${final}/api-source/alembic/versions" --current "${db_current}" --head "${db_head}" 2>&1)"
  audit_code=$?
  set -e
  [[ -n "${audit_output}" ]] && printf '%s\n' "${audit_output}" | tee -a "${SERVER_LOG}"
  if (( audit_code == EXIT_MIGRATION )); then
    die "${EXIT_MIGRATION}" 'pending migration contains destructive operations; manual audit required'
  elif (( audit_code != 0 )); then
    die "${EXIT_PREFLIGHT}" "pending migration audit failed with exit ${audit_code}"
  fi
  ${approve_migration} || die "${EXIT_MIGRATION}" 'pending Migration requires explicit approval'
  pending_migration=true
else
  log "pendingMigration=0 current=${db_current} head=${db_head}; destructive audit skipped"
fi

bash "${SCRIPT_DIR}/backup-production.sh" "${SESSION_ID}"
backup_created=true
if ${pending_migration}; then
  compose_at "${final}" "${new_env}" run --rm --no-deps license-api alembic upgrade head
  touch "${backup}/migration-executed"
  migration_executed=true
  database_modified=true
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
new_env=''
ln -sfn "${final}" "${CURRENT_LINK}.new-${SESSION_ID}"
mv -Tf "${CURRENT_LINK}.new-${SESSION_ID}" "${CURRENT_LINK}"
current_switched=true
admin_failed="${admin_parent}/.admin-previous-${SESSION_ID}"
mv "${DDREC_ADMIN_ROOT}" "${admin_failed}"
mv "${admin_stage}" "${DDREC_ADMIN_ROOT}"
admin_replaced=true

compose_at "${final}" "${ENV_FILE}" up -d --no-deps --pull never license-api
container_recreated=true
wait_healthy "${final}" "${ENV_FILE}" license-api 120
if verify_application_image_identity "${final}" "${ENV_FILE}" "${target_api_image}" "${expected_commit}"; then
  deployment_identity_verified=true
else
  die "${EXIT_DEPLOY}" 'DEPLOY_SEMANTIC_FAILURE: running API image identity does not match target release'
fi
postgres_container_after="$(compose_at "${final}" "${ENV_FILE}" ps -q postgres)"
postgres_image_id_after="$(docker inspect --format '{{.Image}}' "${postgres_container_after}")"
[[ "${postgres_container_after}" == "${postgres_container}" && "${postgres_image_id_after}" == "${current_postgres_image_id}" ]] \
  || die "${EXIT_DEPLOY}" 'PostgreSQL container or Image ID changed unexpectedly during application release'
log "PostgreSQLIdentity=unchanged Container=${postgres_container_after} ImageId=${postgres_image_id_after}"

log 'Nginx is outside the application release transaction; configuration write and reload skipped'

bash "${SCRIPT_DIR}/health-check.sh" "${expected_commit}" "${target_api_image}" "${counts_before}"
deployment_succeeded=true
trap - ERR
log "release deployed successfully: ${release_id}"
log "previousRelease=${previous}"
log "backup=${backup}"
