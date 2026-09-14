#!/usr/bin/env bash
# Container entrypoint: configures host volume permissions (PUID/PGID)
# and drops privileges to the dedicated 'yadisk' user.
set -e

CONFIG_DIR="/data/config"
DATA_DIR="/data/disk"

if [ "$(id -u)" -eq 0 ]; then
    # --- Privileged Mode (Root) ---
    # Detect which directory to inspect for host ownership (split vs unified mounts)
    CHECK_DIR="/data"
    if [ -d "/data/disk" ]; then
        CHECK_DIR="/data/disk"
    elif [ -d "/data/config" ]; then
        CHECK_DIR="/data/config"
    fi

    # Read numeric UID/GID from volume owner, fallback to 1000 if root or undetected
    PUID=${PUID:-$(stat -c '%u' "$CHECK_DIR" 2>/dev/null || echo 1000)}
    PGID=${PGID:-$(stat -c '%g' "$CHECK_DIR" 2>/dev/null || echo 1000)}
    [ "${PUID:-0}" -eq 0 ] && PUID=1000
    [ "${PGID:-0}" -eq 0 ] && PGID=1000

    # Match in-container yadisk user with host volume owner
    if [ "$PUID" -ne 1000 ] || [ "$PGID" -ne 1000 ]; then
        groupmod -o -g "$PGID" yadisk 2>/dev/null || true
        usermod -o -u "$PUID" -g "$PGID" yadisk 2>/dev/null || true
    fi

    # Ensure storage directories exist and ownership is correctly set
    mkdir -p "$CONFIG_DIR" "$DATA_DIR" 2>/dev/null || true
    chown -R yadisk:yadisk "$CONFIG_DIR" /home/yadisk 2>/dev/null || true
    chown yadisk:yadisk "$DATA_DIR" 2>/dev/null || true  # Non-recursive to avoid delay on large disks

    # Drop root privileges and execute command as yadisk user
    exec gosu yadisk "$@"
else
    # --- Unprivileged Mode (Non-Root / Rootless) ---
    # Container was started with custom UID (e.g. --user). Execute directly without gosu.
    mkdir -p "$CONFIG_DIR" "$DATA_DIR" 2>/dev/null || true
    exec "$@"
fi
