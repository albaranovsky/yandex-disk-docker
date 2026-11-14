#!/usr/bin/env bash
# Container checks; script argument handling is covered by test_scripts.py.
set -euo pipefail

IMAGE="${1:-${TEST_IMAGE:-yandex-disk:latest}}"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
HOST_ID="$(id -u):$(id -g)"
TEMP_DIR=$(mktemp -d)
TEST_CONTAINER=""

# shellcheck disable=SC2329
cleanup() {
    if [ -n "$TEST_CONTAINER" ]; then
        docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
    fi
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

run() {
    docker run --rm --platform "$PLATFORM" "$@"
}

contains() {
    if [[ "$OUTPUT" != *"$1"* ]]; then
        printf 'Expected output containing: %s\nActual output:\n%s\n' "$1" "$OUTPUT" >&2
        exit 1
    fi
}

echo "Checking $IMAGE ($PLATFORM)"

echo 'Default user and explicit --user override'
[ "$(run "$IMAGE" id -u)" -eq 1000 ]
OUTPUT=$(run --user 1001:1002 "$IMAGE" id)
contains 'uid=1001'
contains 'gid=1002'

echo 'Official client help with read-only rootfs and no token'
OUTPUT=$(run --read-only --tmpfs /tmp --tmpfs /run "$IMAGE" yadisk start --help)
[ -n "$OUTPUT" ]

echo 'Home symlinks for explicit setup'
# Expand HOME inside the container, not on the host.
# shellcheck disable=SC2016
run "$IMAGE" bash -ec '
    test -L "$HOME/.config/yandex-disk"
    test "$HOME/.config/yandex-disk" -ef /data/config
    test -L "$HOME/Yandex.Disk"
    test "$HOME/Yandex.Disk" -ef /data/disk
    test -d "$HOME/.config/yandex-disk"
    test -w "$HOME/.config/yandex-disk"
    test -d "$HOME/Yandex.Disk"
    test -w "$HOME/Yandex.Disk"
'

echo 'Writable unified storage with explicit host UID/GID'
mkdir -p "$TEMP_DIR/unified"
run --user "$HOST_ID" -v "$TEMP_DIR/unified:/data" "$IMAGE" \
    bash -c 'printf test > /data/config/write-test && printf test > /data/disk/write-test'
[ -f "$TEMP_DIR/unified/config/write-test" ]
[ -f "$TEMP_DIR/unified/disk/write-test" ]

echo 'Missing token fails instead of waiting or starting setup'
if OUTPUT=$(run "$IMAGE" 2>&1); then
    echo 'Unauthenticated startup unexpectedly succeeded' >&2
    exit 1
fi
contains 'Run make setup'

echo 'Legacy PUID/PGID require migration'
if OUTPUT=$(run -e PUID=1001 "$IMAGE" yadisk help 2>&1); then
    echo 'Legacy PUID unexpectedly accepted' >&2
    exit 1
fi
contains 'no longer supported'

echo 'Writable split storage with read-only rootfs'
mkdir -p "$TEMP_DIR/config" "$TEMP_DIR/disk"
run --user "$HOST_ID" --read-only --tmpfs /tmp --tmpfs /run \
    -v "$TEMP_DIR/config:/data/config" -v "$TEMP_DIR/disk:/data/disk" \
    "$IMAGE" bash -ec 'printf config > /data/config/probe; printf disk > /data/disk/probe'
[ "$(cat "$TEMP_DIR/config/probe")" = config ]
[ "$(cat "$TEMP_DIR/disk/probe")" = disk ]

echo 'Entrypoint prepares custom storage paths with spaces'
# shellcheck disable=SC2016
run --user "$HOST_ID" --read-only --tmpfs /tmp --tmpfs /storage:mode=1777 \
    -e 'CONFIG_DIR=/storage/custom config' -e 'DATA_DIR=/storage/custom disk' \
    "$IMAGE" bash -ec 'printf config > "$CONFIG_DIR/probe"; printf disk > "$DATA_DIR/probe"'

# A controlled foreground process checks signal delivery without an account.
printf dummy-token > "$TEMP_DIR/config/passwd"
cat > "$TEMP_DIR/client" <<'EOF'
#!/usr/bin/env bash
trap 'exit 0' SIGTERM SIGINT
echo 'Client ready'
while true; do
    sleep 3600 &
    wait $!
done
EOF
chmod 755 "$TEMP_DIR/client"

echo 'SIGTERM reaches the foreground process without forced kill'
TEST_CONTAINER=$(docker run -d --platform "$PLATFORM" --user "$HOST_ID" \
    -v "$TEMP_DIR/config:/data/config" -v "$TEMP_DIR/disk:/data/disk" \
    -v "$TEMP_DIR/client:/usr/local/bin/yandex-disk:ro" \
    "$IMAGE")
for ((attempt = 0; attempt < 100; attempt++)); do
    OUTPUT=$(docker logs "$TEST_CONTAINER" 2>&1)
    [[ "$OUTPUT" != *'Client ready'* ]] || break
    sleep 0.1
done
contains 'Client ready'
docker stop --timeout 5 "$TEST_CONTAINER" >/dev/null
[ "$(docker inspect --format '{{.State.ExitCode}}' "$TEST_CONTAINER")" -eq 0 ]

echo 'All container checks passed'
