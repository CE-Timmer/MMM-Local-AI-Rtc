ARG BUILD_FROM
FROM $BUILD_FROM

RUN apk add --no-cache \
    ffmpeg \
    portaudio \
    portaudio-dev \
    libstdc++ \
    libgcc \
    bash

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY run.sh /run.sh
COPY app /app

RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
