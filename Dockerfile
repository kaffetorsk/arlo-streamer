FROM jrottenberg/ffmpeg:4.3-ubuntu

# Install python 3.11
RUN apt-get update
ARG DEBIAN_FRONTEND=noninteractive
ARG TZ=Etc/UTC
RUN apt-get -y install software-properties-common git
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update
RUN apt-get -y install python3.11-full
RUN python3.11 -m ensurepip

# Unbuffered logging
ENV PYTHONUNBUFFERED=TRUE

COPY idle.mp4 requirements.txt ./

RUN pip3.11 install -U --upgrade-strategy eager -r requirements.txt

COPY *.py ./

ENTRYPOINT ["python3.11", "main.py"]
