# Yandex.Disk CLI in Docker

Official **Yandex.Disk CLI v0.1.6.1081** with persistent storage and a non-root user.
Default UID/GID: **1000:1000**. Platform: **linux/amd64**; other architectures require emulation.

## Quick start

Create storage as the host user who should own synchronized files, then authenticate:

```bash
mkdir -p data/config data/disk
chmod 700 data/config

docker run -it --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/data":/data \
  yadisk/yandex-disk:latest yadisk token
```

Open the link shown in the terminal and follow the instructions. Start synchronization:

```bash
docker run -d --platform linux/amd64 \
  --name yandex-disk --restart unless-stopped --stop-timeout 30 \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/data":/data \
  yadisk/yandex-disk:latest
```

Use the same UID/GID for authentication and synchronization. The selected user must have read/write access to storage;
the container does not repair ownership or permissions. Missing credentials cause startup to fail and restart attempts.
For Compose, see the [quick start](https://github.com/albaranovsky/yandex-disk-docker#quick-start-with-compose).

## Storage

| Container path | Contents |
| --- | --- |
| `/data/config` | Authorization and settings; keep private |
| `/data/disk` | Synchronized files |

You can mount these directories separately. When reusing authorization, preserve **both `passwd` and `iid`
from the same configuration**. A raw OAuth token cannot replace the client's `passwd` file.

## macOS

With Docker Desktop and a bind mount (a host folder such as `./data:/data`), folders created on the Mac
after the client starts may upload their initial files but fail to synchronize later edits. This was
observed with the current client version.

Create folders before starting synchronization, or run `docker restart yandex-disk` after creating them
(`docker compose restart yandex-disk` for Compose). Existing pending edits were uploaded after restarting
in our checks. A Docker-managed volume avoids the host file-sharing layer if direct access to files
from the Mac is unnecessary.

## Commands

```bash
docker exec yandex-disk yadisk status --last
docker exec yandex-disk yadisk sync
docker exec yandex-disk yadisk publish "/data/disk/Photos/vacation.zip"
docker exec yandex-disk yadisk unpublish "/data/disk/Photos/vacation.zip"
docker exec yandex-disk yadisk help
```

File arguments use container paths. For the interactive authentication wizard, run `yadisk setup` instead of `yadisk token`;
choose `/data/disk` and decline system autostart.

The container healthcheck uses `yadisk status` to check the Yandex.Disk daemon.
An `unhealthy` status means the daemon is not running or its status could not be retrieved.
A `healthy` status does not guarantee cloud connectivity or completed synchronization.

## Options

**Foreground synchronization ignores `config.cfg`.** Set environment variables with `docker run -e`:

| Variable | Default | Meaning |
| --- | --- | --- |
| `EXCLUDE` | empty | Comma-separated directories, e.g. `tmp,cache`; only for `yadisk start` |
| `PROXY` | `auto` when empty | `auto`, `no`, or `protocol,host,port[,login,password]`; all commands |
| `CONFIG_DIR` | `/data/config` | Configuration directory inside the container |
| `DATA_DIR` | `/data/disk` | Synchronization directory inside the container |

Other commands use `config.cfg` when present. For a separate `yadisk sync`, pass `--exclude-dirs=tmp,cache` explicitly.
For custom paths, mount writable storage at the selected locations. A custom `CONFIG_DIR` also requires the same
configuration storage mounted at `/data/config` for `iid`. Empty path variables use the defaults; use `yadisk` commands.

Add `yadisk start --read-only` after the image name to download without changing cloud files.
For a read-only container filesystem, use Docker `--read-only --tmpfs /tmp --tmpfs /run` and keep storage writable;
this still permits changes to synchronized files and cloud data.

## Migration from 2.x

Remove `PUID`/`PGID` and set `--user UID:GID` or Compose `user: "UID:GID"`. Prepare storage permissions on the host.
Keep existing data and configuration, including matching `passwd` and `iid`; authenticate explicitly if needed.
Startup no longer changes ownership, launches an interactive setup, or waits for a token.

[Full documentation](https://github.com/albaranovsky/yandex-disk-docker) ·
[Releases](https://github.com/albaranovsky/yandex-disk-docker/releases) ·
[Image attestations](https://github.com/albaranovsky/yandex-disk-docker/attestations) ·
[Report an issue](https://github.com/albaranovsky/yandex-disk-docker/issues) ·
[MIT license](https://github.com/albaranovsky/yandex-disk-docker/blob/main/LICENSE)
