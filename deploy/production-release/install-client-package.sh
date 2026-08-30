#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

ROOT=/opt/pmsystem-license
DOWNLOAD_ROOT=/var/www/ddrec-downloads
session=
file_name=
final=
expected_size=
expected_sha=
dry_run=false

while (($#)); do
  case "$1" in
    --session) session=${2-}; shift 2 ;;
    --file-name) file_name=${2-}; shift 2 ;;
    --final) final=${2-}; shift 2 ;;
    --size) expected_size=${2-}; shift 2 ;;
    --sha256) expected_sha=${2-}; shift 2 ;;
    --dry-run) dry_run=true; shift ;;
    *) echo "ERROR: unsupported client install argument: $1" >&2; exit 40 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo 'ERROR: client package installation requires root' >&2; exit 40; }
[[ $session =~ ^[0-9]{8}-[0-9]{6}$ ]] || { echo 'ERROR: invalid release session' >&2; exit 40; }
# NEW WRITE PATH: current production releases are iVRec-only. Historical DDREC
# packages remain readable in their immutable download locations, but this
# installer must never create a new DDREC package.
[[ $file_name =~ ^iVRec-[0-9]+\.[0-9]+\.[0-9]+-(standard|license)-Setup\.exe$ ]] || { echo 'ERROR: invalid current iVRec client package file name' >&2; exit 40; }
[[ $expected_size =~ ^[1-9][0-9]*$ ]] || { echo 'ERROR: invalid expected client package size' >&2; exit 40; }
expected_sha=${expected_sha^^}
[[ $expected_sha =~ ^[0-9A-F]{64}$ ]] || { echo 'ERROR: invalid expected client package SHA256' >&2; exit 40; }
[[ $(basename -- "$final") == "$file_name" ]] || { echo 'ERROR: final client file name mismatch' >&2; exit 40; }

case "$final" in
  "$DOWNLOAD_ROOT"/releases/stable/standard/*/*/iVRec-*-standard-Setup.exe) ;;
  "$DOWNLOAD_ROOT"/releases/stable/license/*/*/iVRec-*-license-Setup.exe) ;;
  *) echo 'ERROR: final client path is outside an approved stable lane' >&2; exit 40 ;;
esac

if [[ $dry_run == true ]]; then
  printf 'result=dry-run\nfileName=%s\nfinal=%s\nsize=%s\nsha256=%s\n' \
    "$file_name" "$final" "$expected_size" "$expected_sha"
  exit 0
fi

incoming_dir="$ROOT/incoming/client/$session"
canonical_incoming="$incoming_dir/$file_name"
legacy_incoming="$incoming_dir/$file_name.part"
incoming=
final_dir=$(dirname -- "$final")
staged="$final_dir/.$file_name.$session.part"

[[ -d $incoming_dir && ! -L $incoming_dir ]] || { echo 'ERROR: incoming client directory is missing or is a symlink' >&2; exit 40; }
[[ $(realpath -m -- "$canonical_incoming") == "$canonical_incoming" ]] || { echo 'ERROR: canonical incoming path escaped its root' >&2; exit 40; }
[[ $(realpath -m -- "$legacy_incoming") == "$legacy_incoming" ]] || { echo 'ERROR: legacy incoming path escaped its root' >&2; exit 40; }
[[ $(realpath -m -- "$final") == "$final" ]] || { echo 'ERROR: final path escaped its root' >&2; exit 40; }

exec 9>"$ROOT/.deploy.lock"
flock -n 9 || { echo 'ERROR: deployment lock busy' >&2; exit 40; }

verify_file() {
  local path=$1 label=$2 actual_size actual_sha
  [[ -f $path && ! -L $path ]] || { echo "ERROR: $label is missing, not regular, or is a symlink: $path" >&2; return 1; }
  actual_size=$(stat -c %s -- "$path")
  actual_sha=$(sha256sum -- "$path" | awk '{print toupper($1)}')
  [[ $actual_size == "$expected_size" ]] || { echo "ERROR: $label size mismatch: actual=$actual_size expected=$expected_size" >&2; return 1; }
  [[ $actual_sha == "$expected_sha" ]] || { echo "ERROR: $label SHA256 mismatch: actual=$actual_sha expected=$expected_sha" >&2; return 1; }
}

select_incoming() {
  local canonical_exists=false legacy_exists=false
  [[ -e $canonical_incoming ]] && canonical_exists=true
  [[ -e $legacy_incoming ]] && legacy_exists=true
  if [[ $canonical_exists == true && $legacy_exists == true ]]; then
    verify_file "$canonical_incoming" 'canonical incoming client package' || return 1
    verify_file "$legacy_incoming" 'legacy incoming client package' || return 1
    incoming=$canonical_incoming
  elif [[ $canonical_exists == true ]]; then
    incoming=$canonical_incoming
  else
    incoming=$legacy_incoming
  fi
}

select_incoming || { echo 'ERROR: canonical .exe and legacy .part conflict' >&2; exit 40; }

if [[ -e $final ]]; then
  verify_file "$final" 'existing immutable client package' || exit 40
  if [[ -n $incoming && -e $incoming ]]; then
    verify_file "$incoming" 'incoming client package' || exit 40
    rm -f -- "$incoming"
  fi
  if [[ $legacy_incoming != "$incoming" && -e $legacy_incoming ]]; then rm -f -- "$legacy_incoming"; fi
  printf 'result=reused\npath=%s\nsize=%s\nsha256=%s\n' "$final" "$expected_size" "$expected_sha"
  exit 0
fi

verify_file "$incoming" 'incoming client package' || exit 40
install -d -o root -g root -m 0755 -- "$final_dir"
[[ ! -L $final_dir ]] || { echo 'ERROR: final client directory must not be a symlink' >&2; exit 40; }
install -o root -g root -m 0644 -- "$incoming" "$staged"
verify_file "$staged" 'staged client package' || { rm -f -- "$staged"; exit 40; }
mv -T -- "$staged" "$final"
verify_file "$final" 'installed client package' || exit 40
rm -f -- "$incoming"
if [[ $legacy_incoming != "$incoming" && -e $legacy_incoming ]]; then rm -f -- "$legacy_incoming"; fi
printf 'result=installed\npath=%s\nsize=%s\nsha256=%s\n' "$final" "$expected_size" "$expected_sha"
