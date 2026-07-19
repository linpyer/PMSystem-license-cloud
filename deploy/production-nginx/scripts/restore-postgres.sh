#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in docker sha256sum; do require_command "${command_name}"; done
load_environment
require_value POSTGRES_DB
require_value POSTGRES_USER
require_value POSTGRES_PASSWORD
wait_for_health postgres 20

backup_dir="${PMSYSTEM_ROOT}/backups"
[[ "${backup_dir}" == /opt/pmsystem-license/backups ]] \
  || fail "Unsafe backup directory: ${backup_dir}"
backup_file="${1:-}"
target_database="${2:-}"
[[ -n "${backup_file}" && -n "${target_database}" ]] \
  || fail "Usage: $0 <backup.dump> <pmsystem_license_restore_NAME>"
case "${backup_file}" in
  "${backup_dir}"/*.dump) ;;
  *) fail "Backup must be a .dump file inside ${backup_dir}" ;;
esac
require_file "${backup_file}"
require_file "${backup_file}.sha256"
sha256sum --check "${backup_file}.sha256"
[[ "${target_database}" != "${POSTGRES_DB}" ]] \
  || fail "Direct production database restore is prohibited"
[[ "${target_database}" =~ ^pmsystem_license_restore_[a-zA-Z0-9_]+$ ]] \
  || fail "Target must be a dedicated temporary restore database"
[[ -t 0 ]] || fail "Restore confirmation requires an interactive terminal"
expected="RESTORE-TEST ${target_database}"
printf 'Restore %s into %s. Type exactly: %s\n> ' \
  "${backup_file}" "${target_database}" "${expected}"
read -r confirmation
[[ "${confirmation}" == "${expected}" ]] || fail "Restore cancelled"

if compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  psql -U "${POSTGRES_USER}" -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='${target_database}'" | grep -q 1; then
  fail "Target database already exists; it will not be overwritten"
fi

created=false
completed=false
cleanup_incomplete() {
  if ${created} && ! ${completed}; then
    compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
      dropdb -U "${POSTGRES_USER}" --if-exists "${target_database}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_incomplete EXIT
compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  createdb -U "${POSTGRES_USER}" "${target_database}"
created=true
compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  pg_restore -U "${POSTGRES_USER}" -d "${target_database}" --no-owner --no-privileges \
  <"${backup_file}"
compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  psql -U "${POSTGRES_USER}" -d "${target_database}" -v ON_ERROR_STOP=1 \
  -c "SELECT version_num FROM alembic_version;" \
  -c "SELECT COUNT(*) AS licenses FROM licenses;" \
  -c "SELECT COUNT(*) AS audit_events FROM admin_audit_events;"
completed=true
trap - EXIT
log "Temporary restore validated and retained for review: ${target_database}"
log "No production database or Docker volume was replaced"
