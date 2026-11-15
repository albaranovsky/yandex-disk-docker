#!/usr/bin/env bash
set -e

CONFIG_DIR="${CONFIG_DIR:-/data/config}"
DATA_DIR="${DATA_DIR:-/data/disk}"

if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    echo "[!] PUID/PGID are no longer supported. Use Docker --user UID:GID or Compose user: UID:GID." >&2
    exit 1
fi

mkdir -p "$CONFIG_DIR" "$DATA_DIR" || {
    echo "[!] Cannot create storage directories. Prepare writable $CONFIG_DIR and $DATA_DIR on the host." >&2
    exit 1
}

exec "$@"
