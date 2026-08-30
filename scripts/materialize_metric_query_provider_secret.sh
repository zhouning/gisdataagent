#!/bin/sh
set -eu

source_path=${1:-}
destination_path=${2:-}

case "$source_path" in
  /*) ;;
  *) echo "provider secret source must be absolute" >&2; exit 2 ;;
esac
case "$destination_path" in
  /*) ;;
  *) echo "provider secret destination must be absolute" >&2; exit 2 ;;
esac

if [ ! -f "$source_path" ] || [ ! -s "$source_path" ]; then
  echo "provider secret source is missing or empty" >&2
  exit 2
fi
if [ -L "$destination_path" ]; then
  echo "provider secret destination must not be a symlink" >&2
  exit 2
fi

destination_directory=$(dirname "$destination_path")
mkdir -p "$destination_directory"
umask 077
temporary_path=$(mktemp "${destination_path}.XXXXXX")

cleanup() {
  if [ -n "${temporary_path:-}" ]; then
    rm -f "$temporary_path"
  fi
}
trap cleanup EXIT HUP INT TERM

cp "$source_path" "$temporary_path"
chmod 0400 "$temporary_path"
mv -f "$temporary_path" "$destination_path"
temporary_path=""

file_mode=$(stat -c '%a' "$destination_path" 2>/dev/null || stat -f '%Lp' "$destination_path")
file_owner=$(stat -c '%u' "$destination_path" 2>/dev/null || stat -f '%u' "$destination_path")
if [ "$file_mode" != "400" ] || [ "$file_owner" != "$(id -u)" ]; then
  echo "provider secret ownership materialization failed" >&2
  exit 2
fi

trap - EXIT HUP INT TERM
exit 0
