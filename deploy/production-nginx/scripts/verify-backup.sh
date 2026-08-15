#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in docker sha256sum find sort cut sed date; do
  require_command "${command_name}"
done
load_environment
require_value POSTGRES_DB
require_value POSTGRES_USER
require_value POSTGRES_PASSWORD
wait_for_health postgres 20

backup_dir="${DDREC_ROOT}/backups"
assert_backup_directory "${backup_dir}"
require_directory "${backup_dir}"

backup_file="${1:-}"
if [[ -z "${backup_file}" ]]; then
  backup_file="$(find "${backup_dir}" -maxdepth 1 -type f -name '*.dump' -printf '%T@ %p\n' \
    | sort -nr | cut -d' ' -f2- | sed -n '1p')"
fi
[[ -n "${backup_file}" ]] || fail "No PostgreSQL backup was found"
case "${backup_file}" in
  "${backup_dir}"/*.dump) ;;
  *) fail "Backup must be a .dump file inside ${backup_dir}" ;;
esac
require_file "${backup_file}"
require_file "${backup_file}.sha256"
sha256sum --check "${backup_file}.sha256"

suffix="$(date -u +'%Y%m%d%H%M%S')_${RANDOM}"
database="ddrec_license_restore_verify_${suffix}"
cleanup() {
  compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
    dropdb -U "${POSTGRES_USER}" --if-exists "${database}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  createdb -U "${POSTGRES_USER}" "${database}"
compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  pg_restore -U "${POSTGRES_USER}" -d "${database}" --no-owner --no-privileges \
  <"${backup_file}"
for table in alembic_version licenses device_bindings license_events admin_users admin_audit_events; do
  compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
    psql -U "${POSTGRES_USER}" -d "${database}" -tAc \
    "SELECT 1 FROM information_schema.tables WHERE table_name='${table}'" \
    | grep -q 1 || fail "Restored backup is missing table: ${table}"
done
compose exec -T -e PGPASSWORD="${POSTGRES_PASSWORD}" postgres \
  psql -U "${POSTGRES_USER}" -d "${database}" -v ON_ERROR_STOP=1 \
  -tAc "SELECT version_num FROM alembic_version" >/dev/null
log "Backup checksum and temporary restore verification succeeded"
