#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"
require_root
for command_name in docker sha256sum find; do require_command "${command_name}"; done
load_environment
require_value POSTGRES_DB
require_value POSTGRES_USER
require_value POSTGRES_PASSWORD
expected_database="${DDREC_EXPECTED_PRODUCTION_DB:-ddrec_license}"
[[ "${POSTGRES_DB}" == "${expected_database}" ]] \
  || fail "Refusing to back up unexpected database: ${POSTGRES_DB}"
wait_for_health postgres 20

backup_dir="${DDREC_ROOT}/backups"
assert_backup_directory "${backup_dir}"
install -d -m 750 "${backup_dir}"
timestamp="$(date -u +'%Y-%m-%dT%H%M%SZ')"
final="${backup_dir}/${POSTGRES_DB}_${timestamp}.dump"
partial="${final}.partial"
trap 'rm -f -- "${partial}"' EXIT
log "Starting PostgreSQL backup for ${POSTGRES_DB}"
compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -Fc >"${partial}"
[[ -s "${partial}" ]] || fail "Backup output is empty"
mv "${partial}" "${final}"
sha256sum "${final}" >"${final}.sha256"
trap - EXIT
log "Backup completed: ${final}"

if [[ -n "${1:-}" ]]; then
  [[ "${1}" =~ ^[1-9][0-9]*$ ]] || fail "Retention days must be a positive integer"
  find "${backup_dir}" -maxdepth 1 -type f \( -name '*.dump' -o -name '*.dump.sha256' \) -mtime "+${1}" -print -delete
  log "Expired backup files older than ${1} days were removed only from ${backup_dir}"
fi
