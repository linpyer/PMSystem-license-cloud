#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in docker nginx openssl rsync curl tar gzip sha256sum systemctl ss getent awk df free; do
  require_command "${command_name}"
done

[[ "$(uname -m)" == "x86_64" ]] || fail "This release requires x86_64; found $(uname -m)"
systemctl is-active --quiet docker || fail "Docker service is not active"
docker compose version >/dev/null || fail "Docker Compose v2 is unavailable"
systemctl is-active --quiet nginx || fail "Nginx service is not active"
nginx -T 2>&1 | grep -Fq '/etc/nginx/conf.d/*.conf' || fail "Nginx does not include /etc/nginx/conf.d/*.conf"

log "System: $(. /etc/os-release && printf '%s %s' "${NAME:-Linux}" "${VERSION_ID:-unknown}")"
log "Architecture: $(uname -m)"
log "Docker: $(docker version --format '{{.Server.Version}}')"
log "Compose: $(docker compose version --short)"
log "Nginx: $(nginx -v 2>&1)"
df -h / "${PMSYSTEM_ROOT}" 2>/dev/null || df -h /
free -h

log "Listening ports (80, 443, 8080, 5432):"
ss -lntp | awk 'NR == 1 || $4 ~ /:(80|443|8080|5432)$/' || true

if systemctl is-active --quiet firewalld; then
  log "firewalld is active"
  firewall-cmd --list-services || true
  log "Required public services: ssh, http, https"
else
  log "WARNING: firewalld is not active"
fi

resolved="$(getent ahostsv4 license.aixcc.top | awk 'NR == 1 {print $1}')"
if [[ -n "${resolved}" ]]; then
  log "license.aixcc.top resolves to ${resolved}"
else
  log "WARNING: license.aixcc.top does not currently resolve"
fi

for directory in "${PMSYSTEM_ROOT}" "${PMSYSTEM_ROOT}/release" "${PMSYSTEM_ROOT}/config" \
  "${PMSYSTEM_ROOT}/secrets" "${PMSYSTEM_ROOT}/backups" /var/www/pmsystem-license/admin /var/www/certbot; do
  if [[ -e "${directory}" ]]; then
    log "Present: ${directory}"
  else
    log "Missing (will be created during initialization/install): ${directory}"
  fi
done

log "Alibaba Cloud security groups should expose only SSH, 80 and 443. Never expose 5432 or 8080."
log "Precheck completed without making system changes."
