#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
[[ $# -eq 1 ]] || die "${EXIT_BACKUP}" "usage: $0 SESSION"
SESSION_ID="$1"
safe_session "${SESSION_ID}"
SERVER_LOG="${RELEASE_LOG_ROOT}/${SESSION_ID}.log"
for cmd in docker sha256sum tar install stat; do require_command "${cmd}"; done
load_environment
current="$(readlink -f "${CURRENT_LINK}")"
require_dir "${current}"

backup="${DDREC_ROOT}/backups/release-${SESSION_ID}"
[[ ! -e "${backup}" ]] || die "${EXIT_BACKUP}" "backup already exists: ${backup}"
install -d -m 0700 "${backup}"
printf '%s\n' "${current}" >"${backup}/current-release.txt"
cp -a "${ENV_FILE}" "${backup}/env.production"
chmod 0600 "${backup}/env.production"
cp -a "${current}/compose.yml" "${backup}/current-compose.yml"
compose_at "${current}" "${ENV_FILE}" config --images >"${backup}/compose-images.txt"
api_container="$(compose_at "${current}" "${ENV_FILE}" ps -q license-api)"
postgres_container="$(compose_at "${current}" "${ENV_FILE}" ps -q postgres)"
{
  printf 'currentRelease=%s\n' "${current}"
  printf 'apiImage=%s\n' "$(docker inspect --format '{{.Config.Image}}' "${api_container}")"
  printf 'apiImageId=%s\n' "$(docker inspect --format '{{.Image}}' "${api_container}")"
  printf 'apiRevision=%s\n' "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$(docker inspect --format '{{.Image}}' "${api_container}")")"
  printf 'postgresImage=%s\n' "$(docker inspect --format '{{.Config.Image}}' "${postgres_container}")"
  printf 'postgresImageId=%s\n' "$(docker inspect --format '{{.Image}}' "${postgres_container}")"
} >"${backup}/image-state.txt"
if [[ -d "${DDREC_ADMIN_ROOT}" ]]; then tar -C "$(dirname "${DDREC_ADMIN_ROOT}")" -czf "${backup}/admin.tar.gz" "$(basename "${DDREC_ADMIN_ROOT}")"; fi
if [[ -f "${DDREC_LICENSE_NGINX_CONF}" ]]; then cp -a "${DDREC_LICENSE_NGINX_CONF}" "${backup}/nginx.conf"; fi
nginx -T >"${backup}/nginx-full.txt" 2>&1
database_counts "${current}" "${ENV_FILE}" >"${backup}/counts-before.txt"

dump="${backup}/${POSTGRES_DB}.dump"
partial="${dump}.partial"
trap 'rm -f -- "${partial}"' EXIT
compose_at "${current}" "${ENV_FILE}" exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc >"${partial}" \
  || die "${EXIT_BACKUP}" 'pg_dump failed'
[[ -s "${partial}" ]] || die "${EXIT_BACKUP}" 'database dump is empty'
mv "${partial}" "${dump}"
sha256sum "${dump}" >"${dump}.sha256"
sha256sum -c "${dump}.sha256" >/dev/null
compose_at "${current}" "${ENV_FILE}" exec -T postgres pg_restore -l <"${dump}" >"${backup}/pg_restore.list"
[[ -s "${backup}/pg_restore.list" ]] || die "${EXIT_BACKUP}" 'pg_restore list is empty'
sha256sum "${backup}"/* >"${backup}/SHA256SUMS.txt"
trap - EXIT
log "backup=${backup}"
log "databaseDump=${dump}"
log "databaseDumpSize=$(stat -c%s "${dump}")"
log 'backup checksum and pg_restore list verification passed'
