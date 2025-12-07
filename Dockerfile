FROM python:3.10-slim-buster

WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

RUN sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list && \
    sed -i '/security.debian.org/d' /etc/apt/sources.list && \
    echo "Acquire::Check-Valid-Until \"false\";\nAcquire::Check-Date \"false\";" | cat > /etc/apt/apt.conf.d/10no--check-valid-until

RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
        git wget pv jq python3-dev mediainfo gcc \
        libsm6 libxext6 libfontconfig1 libxrender1 \
        libgl1-mesa-glx ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY --from=mwader/static-ffmpeg:6.1 /ffmpeg /usr/local/bin/ffmpeg
COPY --from=mwader/static-ffmpeg:6.1 /ffprobe /usr/local/bin/ffprobe
RUN chmod 755 /usr/local/bin/ffmpeg /usr/local/bin/ffprobe

COPY . .

RUN pip3 install --no-cache-dir -r requirements.txt

RUN mkdir -p /ramdisk

CMD ["bash", "run.sh"]
