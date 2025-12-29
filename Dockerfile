# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system deps if needed (e.g., for pymongo DNS).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-dev.txt* ./
RUN python -m pip install --upgrade pip \
 && python -m pip install -r requirements.txt \
 && if [ -f requirements-dev.txt ]; then python -m pip install -r requirements-dev.txt; fi

COPY . /app

CMD ["python", "-m", "offside_bot"]
