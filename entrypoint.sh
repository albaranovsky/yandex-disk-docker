#!/usr/bin/env bash
set -e

CONFIG_DIR="/data/config"
DATA_DIR="/data/disk"

# --- 1. Setup Host Permissions (PUID/PGID) ---
if [ "$(id -u)" -eq 0 ]; then
    CHECK_DIR="/data"
    if [ -d "/data/disk" ]; then
        CHECK_DIR="/data/disk"
    elif [ -d "/data/config" ]; then
        CHECK_DIR="/data/config"
    fi

    PUID=${PUID:-$(stat -c '%u' "$CHECK_DIR" 2>/dev/null || echo 1000)}
    PGID=${PGID:-$(stat -c '%g' "$CHECK_DIR" 2>/dev/null || echo 1000)}
    [ "${PUID:-0}" -eq 0 ] && PUID=1000
    [ "${PGID:-0}" -eq 0 ] && PGID=1000

    if [ "$PUID" -ne 1000 ] || [ "$PGID" -ne 1000 ]; then
        groupmod -o -g "$PGID" yadisk 2>/dev/null || true
        usermod -o -u "$PUID" -g "$PGID" yadisk 2>/dev/null || true
    fi

    mkdir -p "$CONFIG_DIR" "$DATA_DIR" 2>/dev/null || true
    chown -R yadisk:yadisk "$CONFIG_DIR" /home/yadisk 2>/dev/null || true
    chown yadisk:yadisk "$DATA_DIR" 2>/dev/null || true

    RUN_CMD=(gosu yadisk)
else
    mkdir -p "$CONFIG_DIR" "$DATA_DIR" 2>/dev/null || true
    RUN_CMD=()
fi

# --- 2. Custom Command Delegation ---
if [ $# -gt 0 ] && [ "$1" != "start" ]; then
    case "$1" in
        status|sync|stop|setup|token)
            exec "${RUN_CMD[@]}" yadisk "$@"
            ;;
        *)
            exec "${RUN_CMD[@]}" "$@"
            ;;
    esac
fi

# --- 3. Authentication Verification ---
if [ ! -f "$CONFIG_DIR/passwd" ]; then
    if [ -t 0 ]; then
        cat << 'EOF'
=================================================================
[i] Configuration not found. Interactive terminal detected.
    Launching Yandex.Disk setup wizard...
=================================================================
EOF
        "${RUN_CMD[@]}" yadisk setup || exit $?
        echo ""
        echo "[i] Setup completed. Starting daemon..."
    else
        cat << 'EOF'
=================================================================
[!] ERROR: Yandex.Disk authentication token not found in /data/config!
    Run setup wizard to authenticate:

    docker run -it --rm -v $(pwd)/data:/data <image> setup
    # or via Makefile:
    make setup
=================================================================
EOF
        trap 'exit 0' SIGTERM SIGINT
        while true; do
            sleep 3600 &
            wait $!
        done
    fi
fi

# --- 4. Write Access Verification ---
if ! "${RUN_CMD[@]}" touch "$CONFIG_DIR/.yadisk_rw_test" 2>/dev/null || \
   ! "${RUN_CMD[@]}" touch "$DATA_DIR/.yadisk_rw_test" 2>/dev/null; then
    cat << EOF
=================================================================
[!] ERROR: Storage directories are not writable by user yadisk [$PUID:$PGID]!
    Please verify host folder permissions for $CONFIG_DIR and $DATA_DIR.
=================================================================
EOF
    rm -f "$CONFIG_DIR/.yadisk_rw_test" "$DATA_DIR/.yadisk_rw_test" 2>/dev/null || true
    exit 1
fi
rm -f "$CONFIG_DIR/.yadisk_rw_test" "$DATA_DIR/.yadisk_rw_test"

# --- 5. Start Background Daemon ---
EXTRA_ARGS=()
[ -n "$EXCLUDE" ] && EXTRA_ARGS+=(--exclude-dirs="$EXCLUDE")

echo "[i] Starting Yandex.Disk daemon (UID:$PUID:GID:$PGID)..."
exec "${RUN_CMD[@]}" yadisk --no-daemon "${EXTRA_ARGS[@]}"
