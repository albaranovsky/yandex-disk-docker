# syntax=docker/dockerfile:1
ARG YADISK_VERSION=0.1.6.1081
ARG YADISK_SHA256=7970b3da0ad644f06f7b3ae4f0c69cc28d4730f95a0a02b7af2b58eb6000f9c5

# --- Stage 1: Download package ---
FROM curlimages/curl:8.22.0@sha256:58adaa4e8dca9c988bae2aba4ab3434a0bb2da16bbe3f92dec39ec7785166777 AS downloader
ARG YADISK_VERSION
ARG YADISK_SHA256
ARG YADISK_DEB_URL=https://repo.yandex.ru/yandex-disk/deb/pool/main/y/yandex-disk/yandex-disk_${YADISK_VERSION}_amd64.deb
RUN curl -fsSL "${YADISK_DEB_URL}" -o /tmp/yandex-disk.deb && \
    printf '%s  %s\n' "${YADISK_SHA256}" /tmp/yandex-disk.deb > /tmp/checksum.txt && \
    sha256sum -c /tmp/checksum.txt && \
    rm -f /tmp/checksum.txt

# --- Stage 2: Runtime image ---
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 AS runtime
ARG YADISK_VERSION
LABEL org.opencontainers.image.title="yandex-disk-docker" \
      org.opencontainers.image.description="Lightweight and secure Yandex.Disk CLI client in Docker" \
      ru.yandex.disk.version="${YADISK_VERSION}" \
      org.opencontainers.image.authors="Aleksey Baranovsky" \
      org.opencontainers.image.source="https://github.com/albaranovsky/yandex-disk-docker" \
      org.opencontainers.image.licenses="MIT"

ARG DEBIAN_FRONTEND=noninteractive
ENV HOME="/home/yadisk" \
    EXCLUDE="" \
    PROXY=""

# hadolint ignore=DL3008
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=bind,from=downloader,source=/tmp/yandex-disk.deb,target=/tmp/yandex-disk.deb \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        tini \
        /tmp/yandex-disk.deb && \
    groupadd -g 1000 yadisk && \
    useradd -u 1000 -g 1000 -d /home/yadisk -m -s /bin/bash yadisk && \
    mkdir -p /home/yadisk/.config /data/config /data/disk && \
    chmod 755 /home/yadisk /home/yadisk/.config && \
    ln -s /data/config /home/yadisk/.config/yandex-disk && \
    ln -s /data/disk /home/yadisk/Yandex.Disk && \
    chown -R yadisk:yadisk /data /home/yadisk

COPY --chmod=755 entrypoint.sh yadisk /usr/local/bin/

USER 1000:1000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD ["yadisk", "status"]

ENTRYPOINT ["tini", "-g", "--", "entrypoint.sh"]
CMD ["yadisk", "start"]
