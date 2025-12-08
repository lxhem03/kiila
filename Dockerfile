FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

RUN apt-get update && apt-get install -y \
    python3 python3-pip git wget pv jq mediainfo \
    libgl1 libglib2.0-0 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

RUN wget -O ffmpeg.tar.xz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz && \
    tar -xJf ffmpeg.tar.xz && \
    mv ffmpeg-*-amd64-static/ffmpeg ffmpeg-*-amd64-static/ffprobe /usr/local/bin/ && \
    rm -rf ffmpeg*

COPY . .
RUN pip3 install --no-cache-dir -r requirements.txt

RUN mkdir -p /ramdisk

CMD ["bash", "run.sh"]
