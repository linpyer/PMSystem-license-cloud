#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in install rsync sha256sum nginx cmp ln readlink; do require_command "${command_name}"; done
source_release="$(readlink -f "${1:-${RELEASE_ROOT}}")"
require_directory "${source_release}"
for item in compose.yml env.production.example README.md SERVER-PREPARATION.md DISASTER_RECOVERY.md SHA256SUMS.txt admin nginx scripts RELEASE-VERSION.txt; do
  [[ -e "${source_release}/${item}" ]] || fail "Release item is missing: ${item}"
done
(cd "${source_release}" && sha256sum -c SHA256SUMS.txt)

version="$(tr -d '\r\n' < "${source_release}/RELEASE-VERSION.txt")"
[[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Invalid release version: ${version}"
target="${DDREC_ROOT}/release/${version}"
if [[ "${source_release}" != "${target}" ]]; then
  [[ ! -e "${target}" ]] || fail "Release ${version} is already installed at ${target}"
  install -d -m 750 "${target}"
  rsync -a "${source_release}/" "${target}/"
fi

install -d -m 750 "${DDREC_ROOT}" "${DDREC_ROOT}/release" "${DDREC_ROOT}/backups" "${DDREC_ROOT}/scripts"
install -d -m 700 "${DDREC_ROOT}/config" "${DDREC_ROOT}/secrets"
install -d -m 755 /var/www/ddrec-license/admin /var/www/certbot
ln -sfn "${target}" "${CURRENT_LINK}"
rsync -a --delete "${target}/admin/" /var/www/ddrec-license/admin/
find /var/www/ddrec-license/admin -type d -exec chmod 755 {} +
find /var/www/ddrec-license/admin -type f -exec chmod 644 {} +
install -m 755 "${target}/scripts/"*.sh "${DDREC_ROOT}/scripts/"

nginx_target=/etc/nginx/conf.d/ddrec-license.conf
nginx_source="${target}/nginx/ddrec-license.conf"
if [[ ! -e "${nginx_target}" ]]; then
  install -m 644 "${nginx_source}" "${nginx_target}"
  log "Installed initial HTTP Nginx configuration"
elif ! cmp -s "${nginx_source}" "${nginx_target}"; then
  install -m 644 "${nginx_source}" "${nginx_target}.new"
  log "Existing Nginx configuration was preserved; compare ${nginx_target}.new manually"
fi
nginx -t
log "Release ${version} installed and current symlink updated. Containers were not started."
