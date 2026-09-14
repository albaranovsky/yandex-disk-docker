# Yandex.Disk CLI client in Docker

[![Docker Image Version](https://img.shields.io/github/v/release/albaranovsky/yandex-disk-docker?logo=github&label=version)](https://github.com/albaranovsky/yandex-disk-docker/releases)
[![Yandex.Disk CLI](https://img.shields.io/badge/yandex--disk-0.1.6.1080-blue?logo=yandex)](https://repo.yandex.ru/yandex-disk/)
[![Architecture](https://img.shields.io/badge/arch-amd64-blue)](https://hub.docker.com/r/albaranovsky/yandex-disk-docker)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![GitHub Source](https://img.shields.io/badge/GitHub-Repository-black?logo=github)](https://github.com/albaranovsky/yandex-disk-docker)

Lightweight and secure Docker image for the official **Yandex.Disk CLI** (`yandex-disk` v`0.1.6.1080`) client.  
Runs background synchronization inside an isolated Debian container, preserving correct host file ownership and
supporting read-only filesystems. Upstream packages are automatically tracked and verified with SHA256 checksums.

---

## Supported Tags

- [`latest`, `2.1.0`, `2.1`](Dockerfile) — Yandex.Disk CLI **v0.1.6.1080** on Debian Slim

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
- **Proper Signal Handling**: Uses `tini` as PID 1 for correct `SIGTERM`/`SIGINT` propagation and zombie process
  reaping.
- **Hardened Security**: Full support for Read-Only Rootfs (`--read-only`) and `--security-opt=no-new-privileges:true`.
- **Healthcheck**: Periodically monitors daemon health via `yadisk status`.
- **Supply Chain Security**: Built with cryptographic SLSA Provenance and SBOM attestation.

---

## Quick Start

### 1. First-Time Setup (OAuth Authorization)

Run interactive setup wizard to link your Yandex account:

```bash
docker run -it --rm -v "$(pwd)/data":/data albaranovsky/yandex-disk-docker:latest
```

Follow terminal instructions:

1. Open the verification link (e.g. `https://ya.ru/device`) in your browser.
2. Enter the displayed code to authorize access.
3. Accept default folder path (`/home/yadisk/Yandex.Disk`).
4. Select `n` for auto-start daemon (Docker manages container lifecycle).

Token and configuration will be saved to `./data/config`.

<!-- prettier-ignore -->
> 💡 **Security Tip (Protect OAuth Token):**
> The `./data/config` directory contains your persistent OAuth authentication token (`passwd`). On shared or multi-user
> Linux hosts, restrict access to your user only:
>
> ```bash
> chmod 700 data/config
> # or restrict the entire data directory:
> chmod 700 data
> ```

---

### 2. Start Synchronization

#### Using Docker Compose (Recommended)

A pre-configured [docker-compose.yml](docker-compose.yml) is included in the repository (includes 30-second stop grace
period and log rotation):

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

Start the service:

```bash
docker compose up -d
```

View logs:

```bash
docker compose logs -f
```

#### Using `docker run`

```bash
docker run -d \
  --name yandex-disk \
  --restart unless-stopped \
  --stop-timeout 30 \
  -v "$(pwd)/data":/data \
  albaranovsky/yandex-disk-docker:latest
```

---

## Management via CLI (`yadisk`)

Check synchronization status:

```bash
docker exec yandex-disk yadisk status
```

Trigger manual sync:

```bash
docker exec yandex-disk yadisk sync
```

View last synchronized files:

```bash
docker exec yandex-disk yadisk status --last
```

Publish file or folder to get a public link:

```bash
docker exec yandex-disk yadisk publish "Photos/vacation.zip"
```

Revoke public link:

```bash
docker exec yandex-disk yadisk unpublish "Photos/vacation.zip"
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

## Links

- [GitHub Repository & Source Code](https://github.com/albaranovsky/yandex-disk-docker)
- [Report an Issue / Bug Tracker](https://github.com/albaranovsky/yandex-disk-docker/issues)
- [Release Notes & Changelog](https://github.com/albaranovsky/yandex-disk-docker/releases)
