#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common-release.sh
source "${SCRIPT_DIR}/common-release.sh"
require_root
assert_root
[[ $# -eq 1 ]] || die "${EXIT_PREFLIGHT}" 'usage: deploy-client-download-nginx.sh SESSION'
SESSION_ID="$1"
safe_session "${SESSION_ID}"
for cmd in install mv nginx python3 sha256sum; do require_command "${cmd}"; done
load_environment

expected="${SCRIPT_DIR}/client-download-nginx.conf"
active="${DDREC_DOWNLOADS_HTTPS_NGINX_CONF}"
[[ "${active}" == '/etc/nginx/conf.d/ddrec-downloads-https.conf' ]] \
  || die "${EXIT_PREFLIGHT}" "unexpected production download Nginx path: ${active}"
require_file "${expected}"
require_file "${active}"

transition_output="$(python3 "${SCRIPT_DIR}/verify-client-download-nginx-transition.py" \
  --active "${active}" --expected "${expected}")" \
  || die "${EXIT_DEPLOY}" 'client download Nginx transition is not approved'
printf '%s\n' "${transition_output}"
if [[ "${transition_output}" == *'=ALREADY_CURRENT' ]]; then
  nginx -t
  printf 'result=already-current\nactive=%s\n' "${active}"
  exit 0
fi

backup="${DDREC_ROOT}/backups/client-download-nginx-${SESSION_ID}"
[[ ! -e "${backup}" ]] || die "${EXIT_BACKUP}" "backup already exists: ${backup}"
install -d -m 0700 "${backup}"
install -m 0644 "${active}" "${backup}/active-before.conf"
install -m 0644 "${expected}" "${backup}/expected.conf"
sha256sum "${backup}/active-before.conf" "${backup}/expected.conf" >"${backup}/SHA256SUMS.txt"
sha256sum -c "${backup}/SHA256SUMS.txt" >/dev/null

candidate="$(dirname -- "${active}")/.$(basename -- "${active}").${SESSION_ID}.new"
restore="$(dirname -- "${active}")/.$(basename -- "${active}").${SESSION_ID}.restore"
cleanup() { rm -f -- "${candidate}" "${restore}"; }
trap cleanup EXIT
[[ ! -e "${candidate}" && ! -e "${restore}" ]] || die "${EXIT_DEPLOY}" 'Nginx staging path already exists'
install -m 0644 "${expected}" "${candidate}"
[[ "$(sha256sum "${candidate}" | awk '{print $1}')" == "$(sha256sum "${expected}" | awk '{print $1}')" ]] \
  || die "${EXIT_DEPLOY}" 'staged Nginx config hash mismatch'
mv -f -- "${candidate}" "${active}"

if ! nginx -t; then
  install -m 0644 "${backup}/active-before.conf" "${restore}"
  mv -f -- "${restore}" "${active}"
  nginx -t || true
  die "${EXIT_DEPLOY}" 'Nginx validation failed; previous config restored'
fi
nginx -s reload
python3 "${SCRIPT_DIR}/verify-client-download-nginx-transition.py" \
  --active "${active}" --expected "${expected}" >/dev/null \
  || die "${EXIT_DEPLOY}" 'active Nginx config does not match approved current rule after reload'
printf 'result=installed\nactive=%s\nbackup=%s\nsha256=%s\n' \
  "${active}" "${backup}" "$(sha256sum "${active}" | awk '{print $1}')"
