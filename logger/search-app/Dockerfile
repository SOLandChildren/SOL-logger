FROM python:3.14.4-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install required system tools. Python is provided by the base image.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ---- Diagnostic check (safe to keep or remove) ----
RUN python --version && \
    python -m pip --version && \
    which python

COPY requirements.txt requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7001

ENTRYPOINT ["python", "search_app.py"]
