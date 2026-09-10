#!/usr/bin/env bash
set -e

IMAGE="${1:-${TEST_IMAGE:-yandex-disk:latest}}"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"

GREEN="\033[0;32m"
RED="\033[0;31m"
BLUE="\033[0;34m"
RESET="\033[0m"

FAILED=0
TOTAL=0

# Temporary workspace for volume tests
TEMP_DIR=$(mktemp -d 2>/dev/null || mktemp -d -t 'yadisk-test')
TEST_CONTAINER=""

cleanup() {
    if [ -n "$TEST_CONTAINER" ]; then
        docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
    fi
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        rm -rf "$TEMP_DIR" >/dev/null 2>&1 || true
    fi
}
trap cleanup EXIT

log_test() {
    TOTAL=$((TOTAL + 1))
    printf "Test %d: %s ... " "$TOTAL" "$1"
}

pass() {
    printf "%b\n" "${GREEN}PASS${RESET}"
}

fail() {
    printf "%b\n" "${RED}FAIL${RESET} ($1)"
    FAILED=$((FAILED + 1))
}

echo -e "${BLUE}=== Starting Test Suite for $IMAGE ($PLATFORM) ===${RESET}"
echo ""

# Test 1: CLI help command execution
log_test "yadisk help command execution"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" "$IMAGE" yadisk help 2>&1) && echo "$OUTPUT" | grep -q "Usage: yadisk"; then
    pass
else
    fail "Unexpected exit code or missing usage banner"
fi

# Test 2: Default user is non-root (yadisk, UID 1000)
log_test "Default user is non-root (yadisk:1000)"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" "$IMAGE" id 2>&1) && echo "$OUTPUT" | grep -q "uid=1000(yadisk)"; then
    pass
else
    fail "Expected uid=1000(yadisk), got: $OUTPUT"
fi

# Test 3: Custom PUID/PGID matching
log_test "Custom PUID/PGID matching (PUID=1001, PGID=1002)"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" -e PUID=1001 -e PGID=1002 "$IMAGE" id 2>&1) && echo "$OUTPUT" | grep -q "uid=1001" && echo "$OUTPUT" | grep -q "gid=1002"; then
    pass
else
    fail "Failed to map custom PUID/PGID, got: $OUTPUT"
fi

# Test 4: Read-Only Rootfs compatibility
log_test "Read-Only Rootfs mode (--read-only --tmpfs /tmp --tmpfs /run)"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" --read-only --tmpfs /tmp --tmpfs /run "$IMAGE" yadisk help 2>&1) && echo "$OUTPUT" | grep -q "Usage: yadisk"; then
    pass
else
    fail "Failed in read-only rootfs mode: $OUTPUT"
fi

# Test 5: Built-in symlinks integrity (/home/yadisk and /root)
log_test "Built-in symlinks integrity (/home/yadisk and /root)"
if docker run --rm --platform "$PLATFORM" "$IMAGE" bash -c '
    test -L /home/yadisk/.config/yandex-disk && \
    test -L /home/yadisk/Yandex.Disk
' >/dev/null 2>&1 && \
   docker run --rm --entrypoint "" --user root --platform "$PLATFORM" "$IMAGE" bash -c '
    test -L /root/.config/yandex-disk && \
    test -L /root/Yandex.Disk
' >/dev/null 2>&1; then
    pass
else
    fail "One or more symlinks are missing or inaccessible"
fi

# Test 6: Storage initialization on volume mount
log_test "Automatic storage directory creation (/data/config and /data/disk)"
if docker run --rm --platform "$PLATFORM" -v "$TEMP_DIR":/data "$IMAGE" yadisk help >/dev/null 2>&1 && \
   [ -d "$TEMP_DIR/config" ] && [ -d "$TEMP_DIR/disk" ]; then
    pass
else
    fail "Subdirectories /data/config or /data/disk were not created on mounted volume"
fi

# Test 7: Crash loop protection & graceful SIGTERM shutdown
log_test "Crash loop protection and graceful SIGTERM shutdown"
TEST_CONTAINER=$(docker run -d --platform "$PLATFORM" "$IMAGE")
sleep 2

# Verify container is alive (waiting instead of crash looping)
if [ "$(docker inspect -f '{{.State.Running}}' "$TEST_CONTAINER" 2>/dev/null)" = "true" ] && \
   docker logs "$TEST_CONTAINER" 2>&1 | grep -q "Yandex.Disk authentication token not found"; then
    # Stop container cleanly
    if docker stop --time 5 "$TEST_CONTAINER" >/dev/null 2>&1; then
        pass
    else
        fail "Container did not stop within grace period"
    fi
else
    fail "Container crashed or did not enter wait loop"
fi
docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
TEST_CONTAINER=""

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}=== All $TOTAL tests passed successfully! ===${RESET}"
    exit 0
else
    echo -e "${RED}=== $FAILED of $TOTAL tests failed! ===${RESET}"
    exit 1
fi
