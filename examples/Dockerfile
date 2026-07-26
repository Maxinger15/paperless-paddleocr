# syntax=docker/dockerfile:1.7
#
# paperless-ngx + paperless-paddleocr.
# OCR recognition is delegated to a separate PP-OCRv6 PaddleX CPU service;
# see docker-compose.yml for the matching runtime config.
#
# Build:
#   docker build \
#     -f examples/Dockerfile \
#     -t paperless-paddleocr:0.1.0 .

# Published images pass a version-and-digest pinned Paperless reference.
# Override this locally to select another official Paperless image.
ARG PAPERLESS_IMAGE=ghcr.io/paperless-ngx/paperless-ngx:3.0.3

# --- Stage 1: build the plugin wheel from source --------------------------
FROM python:3.12-slim AS plugin
WORKDIR /build
COPY pyproject.toml README.md LICENSE ./
COPY paperless_paddleocr ./paperless_paddleocr
RUN pip install --no-cache-dir build \
 && python -m build --wheel --outdir /dist

# --- Stage 2: layer the plugin onto paperless-ngx -------------------------
FROM ${PAPERLESS_IMAGE}

COPY --from=plugin /dist/*.whl /tmp/plugin/
RUN pip install --no-cache-dir /tmp/plugin/*.whl \
 && rm -rf /tmp/plugin
