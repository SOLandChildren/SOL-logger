FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install Python 3.10 and required tools
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 \
        python3-distutils \
        python3-venv \
        python3-pip \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Diagnostic check (safe to keep or remove) ----
RUN python3 --version && \
    python3 -m pip --version && \
    which python3

COPY requirements.txt requirements.txt
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7001

ENTRYPOINT ["python3", "search_app.py"]