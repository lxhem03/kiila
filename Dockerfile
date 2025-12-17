FROM python:3.10-slim-buster

RUN sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list && \
    sed -i '/security.debian.org/d' /etc/apt/sources.list

RUN apt-get update && apt-get install -y \
    git wget curl pv jq python3-dev fontconfig mediainfo gcc \
    libsm6 libxext6 libfontconfig1 libxrender1 libgl1-mesa-glx \
    ca-certificates xz-utils tar procps \
    && rm -rf /var/lib/apt/lists/*

RUN wget -O ffmpeg.tar.xz https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz && \
    tar -xJf ffmpeg.tar.xz && \
    mv ffmpeg-master-latest-linux64-gpl/bin/ffmpeg /usr/local/bin/ffmpeg && \
    mv ffmpeg-master-latest-linux64-gpl/bin/ffprobe /usr/local/bin/ffprobe && \
    chmod +x /usr/local/bin/ffmpeg /usr/local/bin/ffprobe && \
    rm -rf ffmpeg.tar.xz ffmpeg-master-latest-linux64-gpl

WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

COPY . .

RUN pip3 install --no-cache-dir -r requirements.txt

RUN mkdir -p /ramdisk

RUN ffmpeg -version && ffprobe -version

CMD ["bash", "run.sh"]
