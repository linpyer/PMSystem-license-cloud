#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "${SCRIPT_DIR}/common.sh"

require_root
for command_name in docker find sed; do require_command "${command_name}"; done
require_file "${RELEASE_ROOT}/RELEASE-VERSION.txt"
require_file "${RELEASE_ROOT}/RELEASE-GIT-COMMIT.txt"
require_file "${RELEASE_ROOT}/api-source/Dockerfile.offline-upgrade"
wheel_count="$(find "${RELEASE_ROOT}/api-source" -maxdepth 1 -type f -name 'ddrec_license_server-*.whl' | wc -l | tr -d ' ')"
[[ "${wheel_count}" == 1 ]] || fail "Release must contain exactly one API wheel"

require_file "${ENV_FILE}"
load_environment
version="$(tr -d '\r\n' <"${RELEASE_ROOT}/RELEASE-VERSION.txt")"
commit="$(tr -d '\r\n' <"${RELEASE_ROOT}/RELEASE-GIT-COMMIT.txt")"
[[ "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "Invalid release version"
[[ "${commit}" =~ ^[0-9a-f]{40}$ ]] || fail "Invalid release commit"

base_image="${DDREC_BASE_API_IMAGE:-}"
if [[ -z "${base_image}" && ( -L "${CURRENT_LINK}" || -d "${CURRENT_LINK}" ) ]]; then
  current_release="$(readlink -f "${CURRENT_LINK}")"
  current_compose="${current_release}/compose.yml"
  if [[ -f "${current_compose}" ]]; then
    current_container="$(docker compose --project-directory "${current_release}" --env-file "${ENV_FILE}" -f "${current_compose}" ps -q license-api)"
    [[ -n "${current_container}" ]] && base_image="$(docker inspect --format '{{.Config.Image}}' "${current_container}")"
  fi
fi
[[ -n "${base_image}" ]] || fail "Current production API image was not found; set DDREC_BASE_API_IMAGE after audit"
docker image inspect "${base_image}" >/dev/null 2>&1 || fail "Base API image is unavailable: ${base_image}"

target_tag="${version}-${commit:0:7}-production"
target_image="ddrec-license-api:${target_tag}"
docker build --pull=false \
  --file "${RELEASE_ROOT}/api-source/Dockerfile.offline-upgrade" \
  --tag "${target_image}" \
  --build-arg "BASE_API_IMAGE=${base_image}" \
  --build-arg "DDREC_VERSION=${version}" \
  --build-arg "DDREC_GIT_COMMIT=${commit}" \
  "${RELEASE_ROOT}/api-source"
docker run --rm --entrypoint python "${target_image}" -m pip check
platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "${target_image}")"
[[ "${platform}" == linux/amd64 ]] || fail "API image has unsupported platform ${platform}"

temporary_env="${ENV_FILE}.image-${commit:0:7}"
cp -a "${ENV_FILE}" "${temporary_env}"
sed -i -e "s/^DDREC_API_IMAGE_TAG=.*/DDREC_API_IMAGE_TAG=${target_tag}/" "${temporary_env}"
chmod 0600 "${temporary_env}"
mv -f "${temporary_env}" "${ENV_FILE}"
log "Built ${target_image} on the production server (${platform})"
