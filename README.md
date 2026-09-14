# yandex-disk-docker

[![CI & Build](https://github.com/albaranovsky/yandex-disk-docker/actions/workflows/ci.yml/badge.svg)](https://github.com/albaranovsky/yandex-disk-docker/actions/workflows/ci.yml)
[![Docker Pulls](https://img.shields.io/docker/pulls/albaranovsky/yandex-disk-docker?logo=docker)](https://hub.docker.com/r/albaranovsky/yandex-disk-docker)
[![Docker Image](https://img.shields.io/badge/GHCR-image-blue?logo=docker)](https://github.com/albaranovsky/yandex-disk-docker/pkgs/container/yandex-disk-docker)
[![Attestation](https://img.shields.io/badge/Attestation-Verified-success?logo=github)](https://github.com/albaranovsky/yandex-disk-docker/attestations)
[![Yandex.Disk](https://img.shields.io/badge/yandex--disk-0.1.6.1080-blue?logo=yandex)](https://repo.yandex.ru/yandex-disk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Docker image for the official **Yandex.Disk** command-line client (`yandex-disk` v`0.1.6.1080`).

Runs Yandex.Disk background synchronization inside a lightweight Debian Bookworm Slim container, keeping your files and
configuration on the host with correct user permissions. Upstream package releases are continuously tracked and verified
against the official Yandex repository.

---

## Features

- **Non-Root by Default**: Runs daemon under dedicated `yadisk:1000` user.
- **Automatic Setup Wizard**: Launches setup wizard automatically on interactive first run (`docker run -it`).
- **Automatic UID/GID Detection (PUID/PGID)**: Dynamically detects the owner of the mounted host folder and runs the
  daemon via `gosu`. No file permission conflicts on the host.
- **Unified Volume Mount `/data`**: Mount a single host folder (subdirectories `config` and `disk` are created
  automatically). Split mounting (`/data/config` and `/data/disk`) is also supported.
- **Convenient CLI Utility (`yadisk`)**: Built-in CLI wrapper with commands `status`, `sync`, `stop`, `token`, `setup`,
  `publish`, and `unpublish` without typing complex flags or config paths.
- **Crash Loop Protection**: When started unconfigured in background mode, the container waits instead of looping
  crashes, displaying clear setup instructions.
- **Graceful Shutdown**: Configured with 30-second stop timeout to ensure clean SQLite index commits without data
  corruption.
- **Hardened Security**: Full support for Read-Only Rootfs (`--read-only`) and `--security-opt=no-new-privileges:true`.
- **Healthcheck**: Periodically monitors daemon health via `yadisk status`.
- **Supply Chain Security**: Built with cryptographic SLSA Provenance and SBOM attestation.

---

## Volume Structure

- **Option 1 (Recommended, unified storage):**
  - `/data` — Root storage directory (automatically contains `/data/config` and `/data/disk`).
    ```bash
    -v "$(pwd)/data":/data
    ```
- **Option 2 (Separate volumes for config and disk):**
  - `/data/config` — Configuration and authentication token.
  - `/data/disk` — Synchronized files directory.
    ```bash
    -v "$(pwd)/config":/data/config -v "$(pwd)/disk":/data/disk
    ```

---

## Quick Start

### 1. Obtain the Image

**Option A: Pre-built image from Docker Hub or GHCR (fastest):**

```bash
# From Docker Hub:
docker pull albaranovsky/yandex-disk-docker:latest

# Or from GitHub Container Registry (GHCR):
docker pull ghcr.io/albaranovsky/yandex-disk-docker:latest
```

**Option B: Build locally from source:**

```bash
docker build -t yandex-disk:latest .
```

---

### 2. First-Time Setup & Authentication

Thanks to interactive TTY auto-detection, the setup wizard starts **automatically** when run interactively:

```bash
# Option A: Using Makefile (fastest)
make setup

# Option B: Using docker run directly
docker run -it --rm -v "$(pwd)/data":/data albaranovsky/yandex-disk-docker:latest
```

The wizard will prompt:

1. **Use proxy server?** (Usually `N`, or configure if needed).
2. **Open link in browser** (e.g., `https://ya.ru/device`), authorize access, and enter the code into the terminal.
3. **Path to Yandex.Disk folder**: Press Enter to use default (`/home/yadisk/Yandex.Disk`, automatically linked to
   `/data/disk`).
4. **Start daemon on system boot?** Choose `n` (Docker manages container lifecycle).

Token and configuration will be saved to `./data/config`.

> [!TIP] **Security Tip (Protect OAuth Token):** The `./data/config` directory contains your persistent OAuth
> authentication token (`passwd`). On shared or multi-user Linux hosts, restrict access to your user only:
>
> ```bash
> chmod 700 data/config
> # or restrict the entire data directory:
> chmod 700 data
> ```

---

### 3. Start the Synchronization Daemon

#### Option A: Using Docker Compose (Recommended)

A pre-configured [docker-compose.yml](docker-compose.yml) is included in the repository:

```yaml
services:
  yandex-disk:
    image: albaranovsky/yandex-disk-docker:latest
    container_name: yandex-disk
    restart: unless-stopped
    stop_grace_period: 30s
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
    volumes:
      - ./data:/data
```

Start service:

```bash
docker compose up -d
# or via Makefile:
make up
```

View logs:

```bash
docker compose logs -f
# or via Makefile:
make logs
```

---

#### Option B: Using `docker run`

With automatic UID/GID detection and unified volume mounting, the command is simple:

```bash
docker run -d \
  --name yandex-disk \
  --restart unless-stopped \
  --stop-timeout 30 \
  -v "$(pwd)/data":/data \
  albaranovsky/yandex-disk-docker:latest
```

With directory exclusions and proxy:

```bash
docker run -d \
  --name yandex-disk \
  --restart unless-stopped \
  --stop-timeout 30 \
  -e EXCLUDE="tmp,Trash,Cache" \
  -e PROXY="http://proxy.example.com:3128" \
  -v "$(pwd)/data":/data \
  albaranovsky/yandex-disk-docker:latest
```

---

## Makefile Shortcuts

A [Makefile](Makefile) is included for convenient everyday management:

| Category            | Command        | Action                                     |
| :------------------ | :------------- | :----------------------------------------- |
| **Service Control** | `make up`      | Start daemon in background                 |
|                     | `make down`    | Gracefully stop the daemon                 |
|                     | `make restart` | Restart the daemon                         |
| **Operations**      | `make status`  | Check synchronization status               |
|                     | `make sync`    | Trigger manual synchronization             |
|                     | `make logs`    | Stream logs in real time                   |
| **Authentication**  | `make setup`   | Run interactive authentication wizard      |
|                     | `make token`   | Obtain OAuth authentication token directly |
| **Build & Test**    | `make build`   | Build Docker image                         |
|                     | `make pull`    | Pull latest image from registry            |
|                     | `make test`    | Run automated integration test suite       |
| **Debugging**       | `make shell`   | Open bash shell inside container           |

---

## Useful Commands

To execute commands inside a running container, use the built-in `yadisk` CLI utility. It automatically passes
configuration paths and drops privileges to the non-root user:

Check synchronization status:

```bash
docker exec yandex-disk yadisk status
# or via Makefile:
make status
```

View last synchronized files:

```bash
docker exec yandex-disk yadisk status --last
```

Trigger manual synchronization:

```bash
docker exec yandex-disk yadisk sync
# or via Makefile:
make sync
```

Obtain OAuth authentication token directly:

```bash
# In a running container:
docker exec -it yandex-disk yadisk token

# Or before starting the service (standalone):
make token
# or with docker run:
docker run -it --rm -v "$(pwd)/data":/data albaranovsky/yandex-disk-docker:latest yadisk token
```

Publish file or folder to get a public link:

```bash
docker exec yandex-disk yadisk publish "Photos/vacation.zip"
```

Revoke public link:

```bash
docker exec yandex-disk yadisk unpublish "Photos/vacation.zip"
```

Show CLI help:

```bash
docker exec yandex-disk yadisk help
```

---

## Environment Variables

| Variable  | Default           | Description                                                                                         |
| :-------- | :---------------- | :-------------------------------------------------------------------------------------------------- |
| `EXCLUDE` | `""`              | Comma-separated list of directories to exclude (e.g. `tmp,backup`)                                  |
| `PROXY`   | `""`              | Proxy server settings (`http://...`, `socks5://...`, or format `TYPE,SERVER,PORT[,LOGIN,PASSWORD]`) |
| `PUID`    | _(auto-detected)_ | Host user UID (detected from volume owner; override only if needed)                                 |
| `PGID`    | _(auto-detected)_ | Host user GID (detected from volume owner; override only if needed)                                 |

---

## Advanced Settings

### Read-Only Rootfs Mode

For hardened environments where containers cannot modify their own root filesystem, run with `read_only: true`:

**Using Docker Compose:**

```yaml
services:
  yandex-disk:
    image: albaranovsky/yandex-disk-docker:latest
    container_name: yandex-disk
    restart: unless-stopped
    stop_grace_period: 30s
    read_only: true
    tmpfs:
      - /tmp
      - /run
    volumes:
      - ./data:/data
```

**Using `docker run`:**

```bash
docker run -d \
  --name yandex-disk \
  --restart unless-stopped \
  --stop-timeout 30 \
  --read-only \
  --tmpfs /tmp \
  --tmpfs /run \
  -v "$(pwd)/data":/data \
  albaranovsky/yandex-disk-docker:latest
```

---

## Testing

The project includes an automated integration test suite ([tests/test.sh](tests/test.sh)) containing 15 test cases that
validate:

- CLI help banner and documentation of all commands (`status`, `sync`, `stop`, `start`, `setup`, `token`, `publish`,
  `unpublish`)
- Default non-root user permissions (`yadisk:1000`)
- Dynamic host UID/GID mapping (`PUID`/`PGID`)
- Direct unprivileged non-root mode (`--user 1001:1002`)
- Read-Only Rootfs compatibility (`--read-only --tmpfs /tmp --tmpfs /run`)
- Symlink integrity (`/home/yadisk/.config/yandex-disk`, `/home/yadisk/Yandex.Disk`, `/root/Yandex.Disk`, etc.)
- Automatic storage directory initialization on volume mount (`/data/config` and `/data/disk`)
- Split volume mounts support (`/data/config` and `/data/disk` as separate mount targets)
- Graceful container shutdown on `SIGTERM` and crash-loop prevention
- Unauthenticated status check behavior (`yadisk status`)
- Daemon start flag preservation (`yadisk start --read-only`)
- Daemon startup attempt when authentication token is present
- Storage write permission check failure handling (`.yadisk_rw_test`)
- Environment variables propagation (`EXCLUDE` and `PROXY`)

Run the test suite locally:

```bash
make test
```

Or test a specific image directly:

```bash
./tests/test.sh albaranovsky/yandex-disk-docker:latest
```
