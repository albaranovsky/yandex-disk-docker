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

# shellcheck disable=SC2329
cleanup() {
    if [ -n "$TEST_CONTAINER" ]; then
        docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
    fi
    if [ -n "$TEMP_DIR" ] && [ -d "$TEMP_DIR" ]; then
        # Ensure permissions allow full directory removal
        chmod -R 777 "$TEMP_DIR" 2>/dev/null || true
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
    local reason="$1"
    local output="${2:-}"
    printf "%b\n" "${RED}FAIL${RESET} ($reason)"
    if [ -n "$output" ]; then
        echo -e "${RED}--- Diagnostic Output ---${RESET}"
        printf "%s\n" "$output"
        echo -e "${RED}-------------------------${RESET}"
    fi
    FAILED=$((FAILED + 1))
}

wait_for_log() {
    local container="$1"
    local pattern="$2"
    local timeout="${3:-10}"
    local count=0
    local max_count=$((timeout * 10))

    while [ "$count" -lt "$max_count" ]; do
        if docker logs "$container" 2>&1 | grep -q "$pattern"; then
            return 0
        fi
        sleep 0.1
        count=$((count + 1))
    done
    return 1
}

echo -e "${BLUE}=== Starting Test Suite for $IMAGE ($PLATFORM) ===${RESET}"
echo ""

# Test 1: CLI help command execution
log_test "yadisk help command execution"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" "$IMAGE" yadisk help 2>&1) && echo "$OUTPUT" | grep -q "Usage: yadisk"; then
    pass
else
    fail "Unexpected exit code or missing usage banner" "$OUTPUT"
fi

# Test 2: Default user is non-root (yadisk, UID 1000)
log_test "Default user is non-root (yadisk:1000)"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" "$IMAGE" id 2>&1) && echo "$OUTPUT" | grep -q "uid=1000(yadisk)"; then
    pass
else
    fail "Expected uid=1000(yadisk)" "$OUTPUT"
fi

# Test 3: Custom PUID/PGID matching
log_test "Custom PUID/PGID matching (PUID=1001, PGID=1002)"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" -e PUID=1001 -e PGID=1002 "$IMAGE" id 2>&1) && echo "$OUTPUT" | grep -q "uid=1001" && echo "$OUTPUT" | grep -q "gid=1002"; then
    pass
else
    fail "Failed to map custom PUID/PGID" "$OUTPUT"
fi

# Test 4: Read-Only Rootfs compatibility
log_test "Read-Only Rootfs mode (--read-only --tmpfs /tmp --tmpfs /run)"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" --read-only --tmpfs /tmp --tmpfs /run "$IMAGE" yadisk help 2>&1) && echo "$OUTPUT" | grep -q "Usage: yadisk"; then
    pass
else
    fail "Failed in read-only rootfs mode" "$OUTPUT"
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
T6_DIR="$TEMP_DIR/t6"
mkdir -p "$T6_DIR"
if docker run --rm --platform "$PLATFORM" -v "$T6_DIR":/data "$IMAGE" yadisk help >/dev/null 2>&1 && \
   [ -d "$T6_DIR/config" ] && [ -d "$T6_DIR/disk" ]; then
    pass
else
    fail "Subdirectories /data/config or /data/disk were not created on mounted volume"
fi

# Test 7: Crash loop protection & graceful SIGTERM shutdown
log_test "Crash loop protection and graceful SIGTERM shutdown"
TEST_CONTAINER=$(docker run -d --platform "$PLATFORM" "$IMAGE")
if wait_for_log "$TEST_CONTAINER" "Yandex.Disk authentication token not found" 10; then
    if docker stop --time 5 "$TEST_CONTAINER" >/dev/null 2>&1; then
        pass
    else
        OUTPUT=$(docker logs "$TEST_CONTAINER" 2>&1 || true)
        fail "Container did not stop within grace period" "$OUTPUT"
    fi
else
    OUTPUT=$(docker logs "$TEST_CONTAINER" 2>&1 || true)
    fail "Container crashed or did not enter wait loop" "$OUTPUT"
fi
docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
TEST_CONTAINER=""

# Test 8: All CLI commands present in yadisk help
log_test "All CLI commands documented in yadisk help"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" "$IMAGE" yadisk help 2>&1) && \
   echo "$OUTPUT" | grep -q "status" && \
   echo "$OUTPUT" | grep -q "sync" && \
   echo "$OUTPUT" | grep -q "stop" && \
   echo "$OUTPUT" | grep -q "start" && \
   echo "$OUTPUT" | grep -q "setup" && \
   echo "$OUTPUT" | grep -q "token" && \
   echo "$OUTPUT" | grep -q "publish" && \
   echo "$OUTPUT" | grep -q "unpublish"; then
    pass
else
    fail "One or more commands missing from yadisk help output" "$OUTPUT"
fi

# Test 9: CLI command execution (yadisk status)
log_test "CLI command execution (yadisk status)"
OUTPUT=$(docker run --rm --platform "$PLATFORM" "$IMAGE" yadisk status 2>&1 || true)
if echo "$OUTPUT" | grep -q "file with OAuth token hasn't been found"; then
    pass
else
    fail "Unexpected output from yadisk status" "$OUTPUT"
fi

# Test 10: Start command with extra flags (yadisk start --read-only)
log_test "Daemon start flag preservation (yadisk start --read-only)"
TEST_CONTAINER=$(docker run -d --platform "$PLATFORM" "$IMAGE" yadisk start --read-only)
if wait_for_log "$TEST_CONTAINER" "Yandex.Disk authentication token not found" 10; then
    if docker stop --time 5 "$TEST_CONTAINER" >/dev/null 2>&1; then
        pass
    else
        OUTPUT=$(docker logs "$TEST_CONTAINER" 2>&1 || true)
        fail "Container did not stop cleanly" "$OUTPUT"
    fi
else
    OUTPUT=$(docker logs "$TEST_CONTAINER" 2>&1 || true)
    fail "Container failed to start with yadisk start --read-only" "$OUTPUT"
fi
docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
TEST_CONTAINER=""

# Test 11: Direct unprivileged user mode (--user 1001:1002)
log_test "Direct unprivileged user mode (--user 1001:1002)"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" --user 1001:1002 "$IMAGE" id 2>&1) && \
   echo "$OUTPUT" | grep -q "uid=1001" && echo "$OUTPUT" | grep -q "gid=1002"; then
    pass
else
    fail "Direct unprivileged user execution failed" "$OUTPUT"
fi

# Test 12: Split volume mounts (/data/config and /data/disk)
log_test "Split volume mounts (/data/config and /data/disk)"
T12_CONF="$TEMP_DIR/t12_conf"
T12_DISK="$TEMP_DIR/t12_disk"
mkdir -p "$T12_CONF" "$T12_DISK"
if OUTPUT=$(docker run --rm --platform "$PLATFORM" -v "$T12_CONF":/data/config -v "$T12_DISK":/data/disk "$IMAGE" yadisk help 2>&1) && \
   echo "$OUTPUT" | grep -q "Usage: yadisk"; then
    pass
else
    fail "Split volume mounts failed" "$OUTPUT"
fi

# Test 13: Daemon startup when authentication token is present
log_test "Daemon startup when authentication token is present"
T13_DIR="$TEMP_DIR/t13"
mkdir -p "$T13_DIR/config" "$T13_DIR/disk"
echo "dummy_token" > "$T13_DIR/config/passwd"
TEST_CONTAINER=$(docker run -d --platform "$PLATFORM" -v "$T13_DIR":/data "$IMAGE")
if wait_for_log "$TEST_CONTAINER" "Starting Yandex.Disk daemon" 10; then
    pass
else
    OUTPUT=$(docker logs "$TEST_CONTAINER" 2>&1 || true)
    fail "Daemon did not attempt to start with token present" "$OUTPUT"
fi
docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
TEST_CONTAINER=""

# Test 14: Storage write permission check failure handling
log_test "Storage write permission check failure handling"
T14_DIR="$TEMP_DIR/t14"
mkdir -p "$T14_DIR/config" "$T14_DIR/disk"
echo "dummy_token" > "$T14_DIR/config/passwd"
chmod 555 "$T14_DIR/disk"
OUTPUT=$(docker run --rm --platform "$PLATFORM" --user 1000:1000 -v "$T14_DIR":/data "$IMAGE" yadisk start 2>&1 || true)
chmod 777 "$T14_DIR/disk"
if echo "$OUTPUT" | grep -q "ERROR: Yandex.Disk storage directories are not writable"; then
    pass
else
    fail "Storage write permission check did not fail as expected" "$OUTPUT"
fi

# Test 15: Environment variables propagation (EXCLUDE and PROXY)
log_test "Environment variables propagation (EXCLUDE and PROXY)"
T15_DIR="$TEMP_DIR/t15"
mkdir -p "$T15_DIR/config" "$T15_DIR/disk"
echo "dummy_token" > "$T15_DIR/config/passwd"
OUTPUT=$(docker run --rm --platform "$PLATFORM" -v "$T15_DIR":/data \
    -e EXCLUDE="dir1,dir2" \
    -e PROXY="http://proxy.local:8080" \
    "$IMAGE" bash -c "bash -x /usr/local/bin/yadisk start 2>&1 || true")
if echo "$OUTPUT" | grep -q -- "--exclude-dirs=dir1,dir2" && \
   echo "$OUTPUT" | grep -q -- "--proxy=http://proxy.local:8080"; then
    pass
else
    fail "Environment variables EXCLUDE or PROXY not propagated to yandex-disk CLI" "$OUTPUT"
fi

echo ""
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}=== All $TOTAL tests passed successfully! ===${RESET}"
    exit 0
else
    echo -e "${RED}=== $FAILED of $TOTAL tests failed! ===${RESET}"
    exit 1
fi
