FROM jrottenberg/ffmpeg:4.3-ubuntu

RUN apt-get update
ARG DEBIAN_FRONTEND=noninteractive
ARG TZ=Etc/UTC
RUN apt-get -y install software-properties-common git
RUN add-apt-repository ppa:deadsnakes/ppa
RUN apt-get update
RUN apt-get -y install python3.11-full
RUN python3.11 -m ensurepip

ENV PYTHONUNBUFFERED=TRUE

COPY eye.png requirements.txt ./

# ENTRYPOINT ["bash"]

RUN pip3.11 install -r requirements.txt

COPY *.py ./

ENTRYPOINT ["python3.11", "main.py"]
