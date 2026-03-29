FROM python:3.9-slim-buster

ENV PIP_NO_CACHE_DIR=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* \
    :

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip3 install t-tech-investments --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple
RUN pip3 install -r requirements.txt

COPY . .
ENTRYPOINT ["python3", "./tinkoff-stream-grid-bot.py"]
