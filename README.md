# yandex-disk-docker

[![Docker Hub](https://img.shields.io/badge/Docker_Hub-image-blue?logo=docker)](https://hub.docker.com/r/yadisk/yandex-disk)
[![GHCR](https://img.shields.io/badge/GHCR-image-blue?logo=github)](https://github.com/albaranovsky/yandex-disk-docker/pkgs/container/yandex-disk-docker)
[![Yandex.Disk](https://img.shields.io/badge/yandex--disk-0.1.6.1081-blue?logo=yandex)](https://repo.yandex.ru/yandex-disk/)

Docker image for the official **Yandex.Disk CLI v0.1.6.1081**. Configuration and synchronized files persist on the host.
Runs as **UID/GID 1000:1000** by default; select another user with Compose `user:` or Docker `--user`.
Only `linux/amd64` is supported; other architectures require emulation.

Images: `yadisk/yandex-disk` (Docker Hub) or `ghcr.io/albaranovsky/yandex-disk-docker` (GHCR).
Documentation on `main` may describe unreleased changes; consult the documentation for your image's release tag.

## Quick start with Compose

Create storage as the host user who should own the files:

```bash
mkdir -p data/config data/disk
chmod 700 data/config
id -u
id -g
```

Save the following as `compose.yaml`, replacing `1000:1000` with the IDs printed above:

```yaml
services:
  yandex-disk:
    image: yadisk/yandex-disk:latest
    platform: linux/amd64
    user: "1000:1000"
    restart: unless-stopped
    stop_grace_period: 30s
    volumes:
      - ./data:/data
    logging:
      driver: json-file
      options:
        max-size: 10m
        max-file: "3"
```

Authenticate, open the link shown in the terminal, and follow the instructions:

```bash
docker compose run --rm yandex-disk yadisk token
docker compose up -d
docker compose exec yandex-disk yadisk status
```

For the interactive setup wizard, use `yadisk setup` instead of `yadisk token`.
Choose `/data/disk` as the synchronization directory and decline system autostart.
Authenticate before starting the service; missing credentials cause startup to fail and the restart policy to retry.
For `docker run` examples, see the [Docker Hub instructions](DOCKERHUB.md#quick-start).

## Storage and permissions

| Container path | Contents |
| --- | --- |
| `/data/config` | Authorization and client settings; keep private |
| `/data/disk` | Synchronized files |

The selected user must be able to read and write both directories. The container does not repair host ownership
or permissions. Use the same UID/GID for authentication and synchronization.
When reusing authorization, copy **both `passwd` and `iid` from the same configuration**.
A text file containing a raw OAuth token cannot replace the client's `passwd` file.

Separate mounts are also supported; create the host directories first:

```yaml
volumes:
  - ./config:/data/config
  - ./disk:/data/disk
```

## Common commands

```bash
docker compose exec yandex-disk yadisk status --last
docker compose exec yandex-disk yadisk sync
docker compose exec yandex-disk yadisk publish "/data/disk/Photos/vacation.zip"
docker compose exec yandex-disk yadisk unpublish "/data/disk/Photos/vacation.zip"
docker compose exec yandex-disk yadisk help
docker compose logs -f
docker compose down
```

Use container paths for file arguments. To update the image, run `docker compose pull` followed by
`docker compose up -d`; keep the storage directories to preserve authorization and files.

## Configuration

**Synchronization runs in foreground mode and ignores `config.cfg`.** Set options through environment variables
or the startup command. Other client commands use `config.cfg` when present.

| Variable | Default | Meaning |
| --- | --- | --- |
| `EXCLUDE` | empty | Comma-separated directories; applies only to `yadisk start` |
| `PROXY` | `auto` when empty | `auto`, `no`, or `protocol,host,port[,login,password]`; applies to all commands |
| `CONFIG_DIR` | `/data/config` | Configuration directory inside the container |
| `DATA_DIR` | `/data/disk` | Synchronization directory inside the container |

For example, add these settings to the Compose service:

```yaml
environment:
  EXCLUDE: tmp,cache
  PROXY: https,proxy.example.com,3128
command: ["yadisk", "start", "--read-only"]
```

The client flag `--read-only` downloads files without changing cloud files.
**EXCLUDE does not guarantee that local files stay off the cloud:** client 0.1.6.1081 uploaded a new local directory
listed in EXCLUDE. For a separate `yadisk sync`, pass `--exclude-dirs=tmp,cache` explicitly.

For custom storage paths, use absolute container paths and mount writable storage there. With a custom `CONFIG_DIR`,
also mount the same configuration storage at `/data/config` so the client can read its `iid`. Empty path variables
use the defaults. Run client commands through `yadisk` to use the selected paths.
See the [official command reference](https://yandex.ru/support/yandex-360/customers/disk/desktop/linux/ru/cli-commands.html).

## Read-only container filesystem

Keep storage writable and add the following to the Compose service:

```yaml
read_only: true
tmpfs:
  - /tmp
  - /run
security_opt:
  - no-new-privileges:true
```

This protects the container filesystem; the client can still modify synchronized files and cloud data.
Use the client flag `--read-only` above to restrict cloud changes.

## Migration from 2.x

1. Remove `PUID` and `PGID`; nonempty values now cause an error.
2. Set Compose `user: "UID:GID"` or Docker `--user UID:GID` to the storage owner's IDs.
3. Ensure that user can access the configuration and disk directories; ownership is no longer changed at startup.
4. Preserve existing configuration, including matching `passwd` and `iid`. If needed, authenticate explicitly with
   `yadisk token` or `yadisk setup`; startup no longer waits for authorization.

[Releases](https://github.com/albaranovsky/yandex-disk-docker/releases) ·
[Image attestations](https://github.com/albaranovsky/yandex-disk-docker/attestations) ·
[Report an issue](https://github.com/albaranovsky/yandex-disk-docker/issues) · [MIT license](LICENSE)
