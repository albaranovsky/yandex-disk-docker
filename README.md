# yandex-disk-docker

[![CI & Build](https://github.com/albaranovsky/yandex-disk-docker/actions/workflows/ci.yml/badge.svg)](https://github.com/albaranovsky/yandex-disk-docker/actions/workflows/ci.yml)
[![Docker Hub](https://img.shields.io/badge/Docker_Hub-image-blue?logo=docker)](https://hub.docker.com/r/yadisk/yandex-disk)
[![GHCR](https://img.shields.io/badge/GHCR-image-blue?logo=github)](https://github.com/albaranovsky/yandex-disk-docker/pkgs/container/yandex-disk-docker)
[![Attestation](https://img.shields.io/badge/Attestation-Verified-success?logo=github)](https://github.com/albaranovsky/yandex-disk-docker/attestations)
[![Yandex.Disk](https://img.shields.io/badge/yandex--disk-0.1.6.1081-blue?logo=yandex)](https://repo.yandex.ru/yandex-disk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Docker image for the official **Yandex.Disk CLI v0.1.6.1081**, with persistent storage, a non-root user,
`tini` for signal handling, and a small `yadisk` command wrapper.

## Runtime model

- Runs as **UID/GID 1000:1000** by default. Override with Compose `user:` or Docker `--user`.
- Stores configuration and OAuth token in `/data/config`, synchronized files in `/data/disk`.
- Never changes host file ownership or container user accounts at startup.
- Authentication is explicit. Starting without a nonempty token exits with an error.
- Runs synchronization in the foreground with `--no-daemon`; healthcheck uses `yadisk status`.
- Supports read-only rootfs with writable storage and temporary directories.
- Downloads the upstream package from a version-specific URL and verifies SHA256; published images include SBOM and
  provenance attestations.

The image contains the amd64 client. Use `platform: linux/amd64` in Compose or `--platform linux/amd64` with Docker
on another architecture (requires emulation).

This README describes the source tree. Registry images are published from release tags; commits on `main` do not
update the images. Build locally when trying changes that have not yet been released.

## Quick start with Compose

### 1. Prepare storage and select the user

Run as the host account that should own the synchronized files:

```bash
mkdir -p data/config data/disk
chmod 700 data/config
id -u
id -g
```

The included Compose file defaults to UID/GID 1000:1000. If your IDs differ, edit the service's `user:` line
in `docker-compose.yml` using the numeric values above, for example:

```yaml
user: "1001:1002"
```

Existing files must be readable and writable by the selected user. Prepare permissions on the host; the container will
not repair them. The configuration directory contains your OAuth token, so keep access restricted to its owner.

### 2. Build and authenticate

The repository Compose file builds the local image:

```bash
make build
make setup
```

The setup wizard asks you to authorize in a browser. Use `/data/disk` as the synchronization directory, or accept
`/home/yadisk/Yandex.Disk`, which links to it. Decline system autostart: Docker manages the process.
Configuration and token are saved in `data/config`.

Alternatively, obtain just the token without the setup wizard:

```bash
make token
```

The wrapper explicitly stores it in `/data/config/passwd`; no configuration file is required for foreground startup.
When moving existing authorization, preserve both `passwd` and `iid` from the same configuration directory.

### 3. Start synchronization

```bash
make up
make status
make logs
```

`make logs` follows the output until you press Ctrl+C; this does not stop the service.

Authenticate before starting the service. With `restart: unless-stopped`, missing credentials will cause restart attempts
until you configure the token or stop the service.

To use a published image, replace both `build: .` and `image: yandex-disk:latest` in the Compose file with
`image: yadisk/yandex-disk:latest` or `image: ghcr.io/albaranovsky/yandex-disk-docker:latest`. Then run `make pull`.

## Using Docker directly

Prepare `data/config` and `data/disk` as described above, then run:

```bash
docker run -it --rm --platform linux/amd64 \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/data":/data \
  yadisk/yandex-disk:latest yadisk token

docker run -d --platform linux/amd64 \
  --name yandex-disk --restart unless-stopped --stop-timeout 30 \
  --user "$(id -u):$(id -g)" \
  -v "$(pwd)/data":/data \
  yadisk/yandex-disk:latest
```

The same user must own the storage during authentication and synchronization. Two separate mounts are also supported:

```yaml
volumes:
  - ./config:/data/config
  - ./disk:/data/disk
```

Create both host directories with suitable permissions first.

## Commands

The `yadisk` wrapper supplies storage paths and preserves additional arguments:

```bash
docker exec yandex-disk yadisk status --last
docker exec yandex-disk yadisk sync
docker exec yandex-disk yadisk publish "/data/disk/Photos/vacation.zip"
docker exec yandex-disk yadisk unpublish "/data/disk/Photos/vacation.zip"
docker exec yandex-disk yadisk help
```

`docker exec` uses the configured container user. There is no automatic privilege drop if you explicitly select root.
Use paths inside the container for file arguments and Make's `FILE`; the wrapper does not translate host paths or change
the working directory to `/data/disk`.

Make's `FILE` is a literal path; pass it as one quoted shell argument, for example
`make publish 'FILE=/data/disk/Photos/a"b.zip'`. Dollar signs and other special characters are preserved after the calling
shell has processed your command. `ARGS` is a shell argument list for `make status`, intended for flags you supply yourself,
such as `ARGS="--last"`.

`yadisk token /path/to/file` accepts a custom token output path. Default startup still checks and uses
`$CONFIG_DIR/passwd` (`/data/config/passwd` by default), so use `yadisk token` without a file argument for this service.

| Make target | Action |
| --- | --- |
| `make build` / `make pull` | Build locally / pull the configured registry image |
| `make setup` / `make token` | Explicit authentication wizard / token only |
| `make up` / `make down` / `make restart` | Manage the service |
| `make status ARGS="--last"` / `make sync` | Inspect or trigger synchronization |
| `make publish FILE="/data/disk/path"` / `make unpublish FILE="/data/disk/path"` | Manage public links |
| `make logs` / `make shell` | Follow logs / open a shell |
| `make test-unit` | Run script tests without Docker (Python 3.8+) |
| `make test-integration` | Run container checks (requires a built image) |
| `make test` / `make lint` | Run both test suites / container-based linters |

## Synchronization options

**Foreground mode (`--no-daemon`) ignores `config.cfg`.** Set daemon options through environment variables or CLI flags;
the wrapper supplies `DATA_DIR` and `$CONFIG_DIR/passwd` explicitly.

| Variable | Default | Meaning |
| --- | --- | --- |
| `CONFIG_DIR` | `/data/config` | Container path for configuration and token; used by entrypoint and wrapper |
| `DATA_DIR` | `/data/disk` | Container path for synchronized files; used by entrypoint and wrapper |
| `EXCLUDE` | empty | Passed only by `yadisk start`: comma-separated directories, e.g. `tmp,cache` |
| `PROXY` | empty | Passed to all client commands: `auto`, `no`, or `protocol,host,port[,login,password]` |

Empty or unset `CONFIG_DIR` and `DATA_DIR` use their defaults. Use absolute paths inside the container and mount storage
there with permissions for the selected user. Entrypoint creates these directories; `yadisk setup` explicitly supplies
the configuration, token, and disk paths even on first use. The image's home-directory symlinks still point to the default
`/data/config` and `/data/disk`; use `yadisk` commands when overriding storage paths.

Empty `EXCLUDE` and `PROXY` add no CLI option. The client's default proxy mode is `auto`.

For example, in Compose:

```yaml
environment:
  EXCLUDE: tmp,cache
  PROXY: https,proxy.example.com,3128
command: ["yadisk", "start", "--read-only"]
```

The client flag `--read-only` downloads from the cloud without changing server files. It is separate from Docker's
read-only root filesystem. Other commands use `config.cfg` when it exists; additional arguments are passed to the client.
For a standalone `yadisk sync` with exclusions, pass `--exclude-dirs=tmp,cache` explicitly or configure `config.cfg`;
the `EXCLUDE` environment variable is not applied to that command.
See the [official command reference](https://yandex.ru/support/yandex-360/customers/disk/desktop/linux/ru/cli-commands.html).

## Read-only rootfs

The same user model works with a read-only root filesystem. Keep storage writable and add this to the Compose service:

```yaml
read_only: true
tmpfs:
  - /tmp
  - /run
security_opt:
  - no-new-privileges:true
```

This affects the container filesystem; it does not make synchronized host files read-only.

## Migration from 2.x

This is a breaking change to container startup:

1. Remove `PUID` and `PGID` from the container environment. Nonempty legacy variables now produce a migration error.
2. Set Compose `user: "UID:GID"` or Docker `--user UID:GID` to the existing storage owner's IDs.
3. Ensure `config` and `disk` exist and the selected user can access them. Ownership is no longer changed automatically.
4. Authenticate with `make setup` or `make token` if needed. Neither TTY detection nor waiting for authentication remains.

Existing authorization can be reused by preserving `data/config`, including its matching `passwd` and `iid` files.
Do not delete your configuration or synchronized files.
Start still uses foreground mode, so pass exclusions and proxy settings through the environment or CLI.

## Testing

```bash
make test-unit
make test-integration IMAGE=yandex-disk:latest
```

Script tests run the original shell scripts with temporary storage selected through `CONFIG_DIR` and `DATA_DIR`,
and one fake client to check argument handling, exit codes, authentication errors,
permissions, and preservation of existing files. The write-permission test is skipped when run as root.
Container checks verify users, mounts, read-only rootfs, and signal forwarding through `tini`. Foreground argument and
signal checks substitute a client; the official client is invoked for an unauthenticated status check.
The default test suite and CI run without an account.

For an opt-in local test of real synchronization, prepare a directory containing the original `passwd` and `iid`
from the same client configuration for a dedicated test account:

```bash
YADISK_AUTH_DIR=/absolute/path/to/config make test-live IMAGE=yandex-disk:latest
```

Use the file generated by `yadisk token` or `setup`; a text file containing a raw OAuth token is not interchangeable
with the client's encrypted authorization file. The test requires both nonempty files: transferring `passwd` alone
failed with client 0.1.6.1081,
while preserving the matching `iid` allowed synchronization. Neither source file is modified.

To save the path, add it to `.env` at the repository root (ignored by Git):

```dotenv
YADISK_AUTH_DIR=/absolute/path/to/config
```

Then run `make test-live IMAGE=yandex-disk:latest`. Precedence is `--auth-dir`, environment variable, then `.env`.
The test reads only `YADISK_AUTH_DIR` from `.env`; use a plain path or wrap it in matching single/double quotes.
Relative paths from `.env` are resolved from the repository root; `~` is supported. Shell expressions and variable
interpolation are not evaluated. Store the path in `.env`, not the authorization file's contents.

This test writes to the cloud account. Use a dedicated account: both clients may download its other contents.
It copies only `passwd` and `iid` into two temporary Docker volumes and starts clients as `1000:1000` and
`23456:23456` (verified absent from the image's user/group databases). It checks file contents in both directions,
graceful shutdown, and synchronization after recreating a container with its original volume. No REST API token is needed.
Only a uniquely named `yadisk-live-...` cloud folder is created and deleted. On success, deletion is confirmed through
the other client; on failure or interruption, the folder may remain and its name is reported for manual cleanup.
Test containers and volumes are removed on exit. The source authorization file is not modified or printed.
Root is used only to prepare new volumes; both synchronization clients run unprivileged.
This test is excluded from `make test` and CI; interactive token acquisition and `setup` still need a manual check.
Each wait and Docker operation has a timeout; to override the default 300 seconds, run
`python3 tests/live_sync.py --image yandex-disk:latest --auth-dir /path/to/config --timeout 600`.
The test waits for both clients to receive the account quota and enter `idle`, `busy`, or `index` before creating files.
A successful `yadisk status` exit code alone does not establish readiness: the client can report `no internet access`
with exit code 0. Initial indexing need not finish; success requires the test files to reach the other client intact.
While waiting, the test prints each client's core state every 15 seconds and again on timeout.

Upstream updater tests run against temporary repository files and synthetic Debian package records without network
access. They cover package selection, metadata validation, unchanged releases, unexpected hash changes, and literal
version replacement.

## CI and releases

CI runs Actionlint, Hadolint, ShellCheck, script tests, image build, container checks, and a Trivy scan with SARIF upload.
CI and local checks both use `make lint`, which runs the three linters from Docker images. Hadolint fails on warnings
and errors. Actionlint uses the author's Docker image.
The checker scans all workflow files, validates expressions and job dependencies, and checks embedded shell commands.
The build job has repository read access and `security-events: write` for SARIF reporting. Registry publication,
release creation, and attestation permissions belong to a separate `publish` job, which runs only for release tags
after the build job succeeds. It builds the release image, reruns container checks, and scans it with Trivy before
registry login and publication. The release scan is printed in the job log; SARIF upload remains in the build job.
Both scans are report-only. The existing build check name is retained for repository rules.
Release tags matching `v*` trigger image publication to GHCR and, in the original repository, Docker Hub, followed by
provenance attestation and an automatically generated GitHub Release. In the original repository, the Docker Hub
description is updated from the same release tag after a successful image push. Pushes to `main` do not update it.

The upstream workflow checks Yandex's package index every Monday at 08:00 UTC and opens an update PR when the version
changes. It requires one `yandex-disk` amd64 record with a valid version and SHA256. A changed hash without a version
change stops the workflow for manual review; it does not replace the expected hash automatically. Invalid tracked
metadata also fails the check instead of being treated as a first update. ETag is not used.

Upstream PR creation uses the repository secret `AUTO_PR_TOKEN` when configured, otherwise the default `GITHUB_TOKEN`.
With the default token, approve pending PR workflows using **Approve workflows to run** in the PR. For unattended CI
triggering, set `AUTO_PR_TOKEN` to a personal access token authorized for this repository; a fine-grained token needs
**Contents: read and write** and **Pull requests: read and write**. Repository and organization policies still apply.
A GitHub App is another option, but its installation token must be generated for each run and passed to the PR action;
storing an expiring installation token as a permanent secret is insufficient. Before merging an upstream PR, verify that
**CI & Build** succeeded for its latest commit. See [GitHub's workflow triggering rules](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow).

Dependabot checks Docker and GitHub Actions dependencies weekly.

Both Docker base images are pinned by tag and multi-platform manifest digest. The existing Docker Dependabot group
proposes updates to these references, including new digests for an unchanged tag. Review the PR, require successful CI,
inspect the Trivy report, and merge before publishing the next stable release. Dependency-only fixes normally use a
patch release; merging the PR alone does not update published images or `latest`.

For urgent OS fixes, check for a newer base digest and update it through a PR without waiting for the weekly check.
On release tags, CI rebuilds the runtime stage without its cache to refresh packages installed by `apt`, even when the
base digest is unchanged. This refresh happens in the publish job, which builds the image with release labels and
tests and scans it on the same runner. The final push reuses that local builder cache and adds SBOM/provenance.
The shared GitHub Actions cache speeds up builds; no image fingerprints or cache scopes are passed between jobs.
Normal branch and PR builds retain caching. To verify the release build locally, use
`docker build --no-cache-filter runtime --platform linux/amd64 -t yandex-disk:os-update .`.
Pinned base images do not freeze Debian's package repositories: clean builds can still resolve different `apt` package
versions. Byte-for-byte reproducibility is not guaranteed.

## Supply chain verification

```bash
docker scout attestation list yadisk/yandex-disk:latest
docker buildx imagetools inspect yadisk/yandex-disk:latest
gh attestation verify oci://ghcr.io/albaranovsky/yandex-disk-docker:latest --owner albaranovsky
```
