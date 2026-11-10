#!/usr/bin/env bash
set -e

if [ -n "${PUID:-}" ] || [ -n "${PGID:-}" ]; then
    echo "[!] PUID/PGID are no longer supported. Use Docker --user UID:GID or Compose user: UID:GID." >&2
    exit 1
fi

mkdir -p /data/config /data/disk || {
    echo "[!] Cannot create storage directories. Prepare writable /data/config and /data/disk on the host." >&2
    exit 1
}

exec "$@"
