FROM debian:bullseye-slim
LABEL authors="albaranovsky"

ARG CONFIG_DIR=/config
ARG DATA_DIR=/disk
ARG YADISK_DEB=yandex-disk_latest_amd64.deb
ARG YADISK_CONFIG_DIR=/root/.config/yandex-disk

ENV DEBIAN_FRONTEND="noninteractive" \
    DATA_DIR=${DATA_DIR} \
    EXCLUDE=""

ADD http://repo.yandex.ru/yandex-disk/$YADISK_DEB /root

RUN mkdir $DATA_DIR \
    && mkdir -p $YADISK_CONFIG_DIR \
    && ln -s $YADISK_CONFIG_DIR $CONFIG_DIR \
    && cd /root \
    && dpkg -i $YADISK_DEB \
    && rm $YADISK_DEB

ENTRYPOINT exec yandex-disk --no-daemon --dir=$DATA_DIR --exclude-dirs=$EXCLUDE
