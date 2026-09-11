# syntax=docker/dockerfile:1
# --- Stage 1: Download package ---
FROM curlimages/curl:8.22.0 AS downloader
ARG YADISK_DEB_URL=https://repo.yandex.ru/yandex-disk/yandex-disk_latest_amd64.deb
RUN curl -fsSL "${YADISK_DEB_URL}" -o /tmp/yandex-disk.deb

# --- Stage 2: Runtime image ---
FROM debian:bookworm-slim
LABEL org.opencontainers.image.title="yandex-disk-docker" \
      org.opencontainers.image.description="Lightweight and secure Yandex.Disk CLI client in Docker" \
      org.opencontainers.image.authors="Aleksey Baranovsky" \
      org.opencontainers.image.source="https://github.com/albaranovsky/yandex-disk-docker" \
      org.opencontainers.image.licenses="MIT"

ARG DEBIAN_FRONTEND=noninteractive
ENV PUID="" \
    PGID="" \
    EXCLUDE="" \
    PROXY=""

# hadolint ignore=DL3008
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=bind,from=downloader,source=/tmp/yandex-disk.deb,target=/tmp/yandex-disk.deb \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        gosu \
        tini \
        /tmp/yandex-disk.deb && \
    groupadd -g 1000 yadisk && \
    useradd -u 1000 -g 1000 -d /home/yadisk -m -s /bin/bash yadisk && \
    mkdir -p /root/.config /home/yadisk/.config /data/config /data/disk && \
    ln -s /data/config /root/.config/yandex-disk && \
    ln -s /data/config /home/yadisk/.config/yandex-disk && \
    ln -s /data/disk /root/Yandex.Disk && \
    ln -s /data/disk /home/yadisk/Yandex.Disk && \
    chown -R yadisk:yadisk /data /home/yadisk

COPY --chmod=755 entrypoint.sh yadisk /usr/local/bin/

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["yadisk", "status"]

ENTRYPOINT ["tini", "-g", "--", "entrypoint.sh"]
CMD ["start"]
