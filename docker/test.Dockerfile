# Test image: current Home Assistant (2026.10.x needs Python 3.14).
# Build:  docker build -f docker/test.Dockerfile -t cololight-test .
# Run:    docker run --rm -v "$PWD":/work -w /work cololight-test pytest
FROM python:3.14-slim
RUN apt-get update && apt-get install -y --no-install-recommends gcc libc6-dev && rm -rf /var/lib/apt/lists/*
COPY requirements_test.txt /tmp/requirements_test.txt
RUN pip install --no-cache-dir -r /tmp/requirements_test.txt
