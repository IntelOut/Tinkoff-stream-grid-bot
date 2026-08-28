FROM python:3.12-slim

ENV PIP_NO_CACHE_DIR=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get -y upgrade && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements.txt
# Приватный пакет ставим отдельным шагом с эксклюзивным индексом,
# чтобы избежать подмены версии с публичного PyPI (dependency confusion)
RUN pip3 install --index-url https://opensource.tbank.ru/api/v4/projects/238/packages/pypi/simple "t-tech-investments>=0.3.5"
RUN pip3 install -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser && chown -R appuser:appuser /app
USER appuser

ENTRYPOINT ["python3", "./tinkoff-stream-grid-bot.py"]
