FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV CC=gcc
ENV CXX=g++

WORKDIR /

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    build-essential \
    gcc \
    g++ \
    openjdk-11-jdk \
    zlib1g-dev \
    libffi-dev \
    libssl-dev \
    python3 \
    python3-dev \
    python3-venv \
    python3-distutils \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements.txt

RUN python3 -m pip install --upgrade pip setuptools wheel && \
    python3 -m pip install -r requirements.txt && \
    python3 -m pip install --upgrade git+https://github.com/terrierteam/pyterrier_t5.git

COPY . .

CMD ["python3", "app.py"]