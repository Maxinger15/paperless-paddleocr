# paperless-ngx + the locally built plugin, for the e2e compose stacks.
# Build context is the repo root.
ARG PAPERLESS_IMAGE=ghcr.io/paperless-ngx/paperless-ngx:3.0.3

FROM python:3.12-slim AS plugin
WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY paperless_paddleocr ./paperless_paddleocr
RUN pip install --no-cache-dir build \
 && python -m build --wheel --outdir /dist

FROM ${PAPERLESS_IMAGE}
COPY --from=plugin /dist/*.whl /tmp/plugin/
RUN pip install --no-cache-dir /tmp/plugin/*.whl \
 && rm -rf /tmp/plugin
