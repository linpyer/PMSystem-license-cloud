#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
load_environment
current="$(readlink -f "${CURRENT_LINK}" 2>/dev/null || true)"
printf 'current=%s\n' "${current}"
printf 'diskAvailable=%s\n' "$(df -PB1 "${DDREC_ROOT}" | awk 'NR==2{print $4}')"
compose_at "${current}" "${ENV_FILE}" ps
curl -fsS https://license.aixcc.top/api/v1/health; echo
printf 'adminHttp=%s\n' "$(curl -sS -o /dev/null -w '%{http_code}' https://license.aixcc.top/admin/)"
printf 'downloadRoot=%s\n' "$(nginx -T 2>/dev/null | awk '/server_name[[:space:]]+download\.aixcc\.top/{s=1} s && /root \/var\/www\//{gsub(/;|^[[:space:]]*root[[:space:]]+/,""); print; exit}')"
database_counts "${current}" "${ENV_FILE}"
