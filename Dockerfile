FROM python:3.10-slim-buster
    
WORKDIR /usr/src/app
RUN chmod 777 /usr/src/app

RUN sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list && \
    sed -i '/security.debian.org/d' /etc/apt/sources.list
    
RUN apt-get update && apt-get upgrade -y
RUN apt-get install git wget pv jq python3-dev mediainfo gcc libsm6 libxext6 libfontconfig1 libxrender1 libgl1-mesa-glx -y

COPY --from=mwader/static-ffmpeg:6.1 /ffmpeg /bin/ffmpeg
COPY --from=mwader/static-ffmpeg:6.1 /ffprobe /bin/ffprobe

COPY . .
RUN pip3 install --no-cache-dir -r requirements.txt

CMD ["bash","run.sh"]
