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

echo 'Help with read-only rootfs'
OUTPUT=$(run --read-only --tmpfs /tmp --tmpfs /run "$IMAGE" yadisk help)
contains 'Usage: yadisk'

echo 'Home symlinks for explicit setup'
# Expand HOME inside the container, not on the host.
# shellcheck disable=SC2016
run "$IMAGE" bash -c 'test -L "$HOME/.config/yandex-disk" && test -L "$HOME/Yandex.Disk"'

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

echo 'Official client can be invoked without a token'
OUTPUT=$(run "$IMAGE" yadisk status 2>&1 || true)
contains "file with OAuth token hasn't been found"

# Replace only the client to test storage, read-only rootfs, argv, and tini signals
# without an account, network access, or a real synchronization session.
mkdir -p "$TEMP_DIR/config" "$TEMP_DIR/disk"
printf dummy-token > "$TEMP_DIR/config/passwd"
cat > "$TEMP_DIR/client" <<'EOF'
#!/usr/bin/env bash
if [ "${CLIENT_WAIT:-}" = 1 ]; then
    trap 'exit 0' SIGTERM SIGINT
    echo 'Client ready'
    while true; do
        sleep 3600 &
        wait $!
    done
fi
printf '<%s>\n' "$@"
EOF
chmod 755 "$TEMP_DIR/client"

echo 'Split storage and foreground arguments with read-only rootfs'
OUTPUT=$(run --user "$HOST_ID" --read-only --tmpfs /tmp --tmpfs /run \
    -v "$TEMP_DIR/config:/data/config" -v "$TEMP_DIR/disk:/data/disk" \
    -v "$TEMP_DIR/client:/usr/local/bin/yandex-disk:ro" \
    -e EXCLUDE=dir1,dir2 -e PROXY=https,proxy.local,8080 \
    "$IMAGE" yadisk start --read-only)
contains '<--dir=/data/disk>'
contains '<--auth=/data/config/passwd>'
contains '<--no-daemon>'
contains '<--exclude-dirs=dir1,dir2>'
contains '<--proxy=https,proxy.local,8080>'
contains '<--read-only>'

echo 'SIGTERM reaches the foreground client through tini'
TEST_CONTAINER=$(docker run -d --platform "$PLATFORM" --user "$HOST_ID" \
    -v "$TEMP_DIR/config:/data/config" -v "$TEMP_DIR/disk:/data/disk" \
    -v "$TEMP_DIR/client:/usr/local/bin/yandex-disk:ro" \
    -e CLIENT_WAIT=1 "$IMAGE")
for ((attempt = 0; attempt < 100; attempt++)); do
    OUTPUT=$(docker logs "$TEST_CONTAINER" 2>&1)
    [[ "$OUTPUT" != *'Client ready'* ]] || break
    sleep 0.1
done
contains 'Client ready'
docker stop --time 5 "$TEST_CONTAINER" >/dev/null
[ "$(docker inspect --format '{{.State.ExitCode}}' "$TEST_CONTAINER")" -eq 0 ]

echo 'All container checks passed'
