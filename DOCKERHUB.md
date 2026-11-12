# Yandex.Disk CLI client in Docker

[![CI & Build](https://github.com/albaranovsky/yandex-disk-docker/actions/workflows/ci.yml/badge.svg)](https://github.com/albaranovsky/yandex-disk-docker/actions/workflows/ci.yml)
[![Docker Image Version](https://img.shields.io/github/v/release/albaranovsky/yandex-disk-docker?logo=github&label=version)](https://github.com/albaranovsky/yandex-disk-docker/releases)
[![Attestation](https://img.shields.io/badge/Attestation-Verified-success?logo=github)](https://github.com/albaranovsky/yandex-disk-docker/attestations)
[![Yandex.Disk CLI](https://img.shields.io/badge/yandex--disk-0.1.6.1081-blue?logo=yandex)](https://repo.yandex.ru/yandex-disk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Official **Yandex.Disk CLI v0.1.6.1081** in a Debian Slim container. Runs as UID/GID **1000:1000** by default,
uses `tini` for signal handling, and verifies the upstream package with SHA256.

## Prepare storage and authenticate

Create storage as the host user who should own synchronized files:

```bash
mkdir -p data/config data/disk
chmod 700 data/config

docker run -it --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/data":/data \
  yadisk/yandex-disk:latest yadisk token
```

Open the authorization link and follow the terminal instructions. The token is saved to `data/config/passwd`.
Keep this directory private. The container does not change ownership or permissions of host files.

## Start synchronization

```bash
docker run -d --platform linux/amd64 \
  --name yandex-disk --restart unless-stopped --stop-timeout 30 \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/data":/data \
  yadisk/yandex-disk:latest
```

Use the same UID/GID for authentication and synchronization. Without a nonempty token, startup exits with an error;
authenticate before starting a service with a restart policy.

For Compose, set `user:` to the storage owner's numeric UID/GID:

```yaml
services:
  yandex-disk:
    image: yadisk/yandex-disk:latest
    platform: linux/amd64
    user: "1000:1000" # Replace with the host storage owner's UID:GID
    container_name: yandex-disk
    restart: unless-stopped
    stop_grace_period: 30s
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: "3"
    volumes:
      - ./data:/data
```

Two separate mounts to `/data/config` and `/data/disk` are also supported. Prepare host directories before starting.

## Commands and options

```bash
docker exec yandex-disk yadisk status --last
docker exec yandex-disk yadisk sync
docker exec yandex-disk yadisk publish "/data/disk/Photos/vacation.zip"
docker exec yandex-disk yadisk unpublish "/data/disk/Photos/vacation.zip"
docker exec yandex-disk yadisk help
```

Synchronization runs with `--no-daemon`, which ignores `config.cfg`. The wrapper supplies storage paths explicitly.
Set `EXCLUDE=tmp,cache`, `PROXY=https,proxy.example.com,3128`, or pass CLI arguments via
`yadisk start --read-only`. `EXCLUDE` applies only to `yadisk start`; `PROXY` is passed to all client commands.
Empty variables add no option; the client's default proxy mode is `auto`. Other commands use `config.cfg` when present.
For standalone synchronization, pass exclusions explicitly with `yadisk sync --exclude-dirs=tmp,cache`.
File arguments use paths inside the container; host paths are not translated.
`yadisk token FILE` writes to the selected file, but startup checks and uses `$CONFIG_DIR/passwd`
(`/data/config/passwd` by default).

Override `CONFIG_DIR` (default `/data/config`) and `DATA_DIR` (default `/data/disk`) with absolute container paths if needed.
Mount writable storage at those paths. Empty or unset values use the defaults. Entrypoint creates the selected directories;
the wrapper uses them for setup, token creation, synchronization, and management commands. Built-in home-directory symlinks
retain the default paths, so use `yadisk` commands with custom storage paths.
See the [official command reference](https://yandex.ru/support/yandex-360/customers/disk/desktop/linux/ru/cli-commands.html).

Read-only rootfs is enabled with `--read-only`, writable storage, and `--tmpfs /tmp --tmpfs /run`. The container also supports
`--security-opt=no-new-privileges:true`. The client flag `--read-only` controls cloud synchronization separately.

## Migration from 2.x

Remove `PUID`/`PGID`; use Docker `--user UID:GID` or Compose `user: "UID:GID"` instead. Prepare storage ownership
on the host. Automatic user mapping, ownership repair, interactive setup on startup, and waiting for a token have been
removed. Nonempty legacy variables produce an error. Existing tokens and synchronized data can be reused.

## Supply chain verification

Published images include SBOM and provenance attestations:

```bash
docker scout attestation list yadisk/yandex-disk:latest
gh attestation verify oci://ghcr.io/albaranovsky/yandex-disk-docker:latest --owner albaranovsky
```

[Source and full documentation](https://github.com/albaranovsky/yandex-disk-docker) ·
[Report an issue](https://github.com/albaranovsky/yandex-disk-docker/issues)
