<!-- markdownlint-disable-file MD033 MD041 -->
<div align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <img src="assets/logo-light.svg" alt="paperless-paddleocr" width="360">
  </picture>
</div>

`paperless-paddleocr` is a [PP-OCRv6](https://www.paddleocr.ai/) provider for
[paperless-ngx](https://github.com/paperless-ngx/paperless-ngx). It is a parser plugin: Paperless
still owns ingestion, OCRmyPDF processing, rotation, deskew, hOCR, and PDF/A creation. A separate
CPU-only PaddleX service recognises one rasterised page at a time over HTTP.

This project began as a fork of [flobernd/paperless-chandra](https://github.com/flobernd/paperless-chandra).
Its source code remains MIT licensed; see [License](#license-and-attribution).

## Architecture

```text
Paperless consumer -> parser -> OCRmyPDF -> PP-OCRv6 HTTP /ocr -> hOCR -> PDF/A -> Paperless API
```

The plugin posts a lossless Base64 PNG for each page to PaddleX Basic Serving with `fileType: 1`,
`visualize: false`, and all three document-orientation/unwarping/text-line-orientation flags false.
Paperless/OCRmyPDF already handles rotation and deskew. The service YAML also defaults
`Serving.visualize: false` and `Serving.extra.max_num_input_imgs: null`; client correctness does
not depend on those defaults because it explicitly sets `visualize: false` and sends individual pages.

## Requirements

- paperless-ngx 3.0 or later; `3.0.2` is the CI-smoked compatibility baseline.
- A PP-OCRv6 PaddleX Basic Serving `/ocr` endpoint. The supplied service uses CPU only and pins
  `python:3.10.20-slim-bookworm`, `paddlepaddle==3.2.1`, `paddlex[ocr-core]==3.7.2`, and
  `paddleocr==3.7.0`.
- For a custom Paperless image, Docker and Docker Compose. The Paperless image contains the plugin
  and lightweight HTTP/image/OCRmyPDF dependencies only; it does not contain Paddle, model files,
  or an accelerator runtime.

CPU OCR is intentionally simple to deploy but can be slow, especially for large, high-DPI, or
multi-page documents. Start with one Paperless task worker, measure on the target host, and scale
only after observing memory and latency.

## Quick start with Compose

Create `examples/.env`:

```dotenv
PAPERLESS_DB_USER=paperless
PAPERLESS_DB_PASSWORD=change-this-to-a-long-secret
```

Then pull and start the complete stack:

```bash
cd examples
docker compose pull
docker compose up -d
```

[`examples/docker-compose.yml`](examples/docker-compose.yml) creates distinct Paperless,
`paddleocr-server`, PostgreSQL, and Redis services. `paddlex_models` persists downloaded PP-OCRv6
files between restarts. The sidecar's healthcheck proves only that TCP port 8080 is listening;
model download/loading can continue after it turns healthy, so the first request can take longer.

### Published images and tags

The example pulls multi-platform Linux images for `amd64` and `arm64` by default:

- `ghcr.io/maxinger15/paperless-paddleocr:latest` — paperless-ngx with this plugin installed.
  It intentionally contains no Paddle, PaddleX, model files, or accelerator runtime.
- `ghcr.io/maxinger15/paperless-paddleocr-server:latest` — the separate CPU-only PP-OCRv6
  PaddleX service.

`latest` is rebuilt from the default branch, and the Paperless image is also rebuilt daily at
05:37 UTC against `ghcr.io/paperless-ngx/paperless-ngx:latest`. Scheduled Paperless builds also
receive a `daily-YYYY-MM-DD` tag. Default-branch and manual builds receive a `sha-*` tag; version
tags do not publish images automatically. The server is published for default-branch pushes and
manual runs from the default branch, but is not rebuilt by the daily schedule. Both images publish
one manifest for `linux/amd64` and `linux/arm64`, so Compose selects the native image for the host.

The daily channel deliberately follows the mutable official Paperless `latest` image. For a
controlled deployment, select a reviewed `daily-YYYY-MM-DD` tag or pin the resulting GHCR digest
instead of following `latest`.

GitHub Container Registry may create a package as private on its first publish. In GitHub, open
the repository's **Packages** section, select each package, then use **Package settings** to change
its visibility to **Public** before expecting unauthenticated pulls to work.

### Local source builds

To build from this checkout instead of pulling the published images:

```bash
docker build -f examples/Dockerfile \
  --build-arg PAPERLESS_TAG=3.0.2 \
  -t paperless-paddleocr:local .
docker build -f docker/paddleocr.Dockerfile -t paperless-paddleocr-server:local .
cd examples
PAPERLESS_IMAGE=paperless-paddleocr:local \
PADDLEOCR_SERVER_IMAGE=paperless-paddleocr-server:local \
docker compose up -d
```

The Dockerfile defaults to `PAPERLESS_TAG=latest`, matching daily publication. Set a specific
`--build-arg PAPERLESS_TAG=…` when scripting a reproducible deployment.

## Installation alternatives

For a prebuilt plugin artifact, build it with Docker:

```bash
docker build -f docker/builder.Dockerfile -t paperless-paddleocr-builder .
docker create --name paperless-paddleocr-extract paperless-paddleocr-builder
docker cp paperless-paddleocr-extract:/dist/. ./dist
docker rm paperless-paddleocr-extract
```

Place `setup.sh` and either `paperless_paddleocr-*.whl` or
`paperless_paddleocr-*.tar.gz` in Paperless's `/custom-cont-init.d/`. The bootstrap script is
idempotent and installs no Paddle runtime or models. On a non-container host, install the wheel in
the same Python environment as Paperless and restart it.

## Configuration

All standard `PAPERLESS_OCR_*` variables retain their Paperless meaning, including mode, output
type, pages, clean, deskew, rotation, DPI, and user arguments. Plugin variables are:

| Variable | Default | Description |
| --- | --- | --- |
| `PAPERLESS_PADDLEOCR_SERVER_URL` | *(required)* | Absolute `http://` or `https://` service base URL, for example `http://paddleocr-server:8080`. |
| `PAPERLESS_PADDLEOCR_ENDPOINT` | `/ocr` | Relative PaddleX endpoint path. |
| `PAPERLESS_PADDLEOCR_API_KEY` | *(unset)* | Optional bearer token appended as `Authorization: Bearer …`. |
| `PAPERLESS_PADDLEOCR_CONNECT_TIMEOUT` | `10` | Positive HTTP connect timeout in seconds. |
| `PAPERLESS_PADDLEOCR_READ_TIMEOUT` | `300` | Positive per-page HTTP read timeout in seconds. |
| `PAPERLESS_PADDLEOCR_VERIFY_TLS` | `true` | Set to `false` only for an explicitly accepted local self-signed certificate risk. |
| `PAPERLESS_PADDLEOCR_CA_BUNDLE` | *(unset)* | Path to a PEM CA bundle for a private/reverse-proxy CA. Cannot be combined with disabled verification. |
| `PAPERLESS_PADDLEOCR_SCORE` | `15` | Paperless parser score; the built-in Tesseract parser scores `10`. |

### External, HTTPS, and authenticated services

An external plain HTTP service:

```dotenv
PAPERLESS_PADDLEOCR_SERVER_URL=http://ocr-host.internal:8080
```

For TLS and bearer authentication behind a reverse proxy:

```dotenv
PAPERLESS_PADDLEOCR_SERVER_URL=https://ocr.example.internal
PAPERLESS_PADDLEOCR_API_KEY=replace-with-a-secret-token
PAPERLESS_PADDLEOCR_CA_BUNDLE=/usr/src/paperless/certs/internal-ca.pem
```

Mount the CA file read-only into the Paperless container. For a temporary local self-signed setup
without a trusted CA, `PAPERLESS_PADDLEOCR_VERIFY_TLS=false` is available. **This disables server
identity verification and exposes OCR page images and bearer tokens to interception; do not use it
on an untrusted network.** Prefer a trusted or mounted private CA bundle.

## Updating

Rebuild the Paperless image after selecting a newer plugin release/source, then recreate the
container. The PaddleX service can be updated independently after reviewing PaddleX and PaddleOCR
release notes. Keep the model-cache volume when recreating it to avoid unnecessary model downloads.

## Verification and operations

The deterministic E2E checks Paperless ingestion, parser discovery, OCRmyPDF, HTTP request shape,
hOCR, PDF/A, API content, and a rotated page without downloading a model:

```bash
tests/e2e/run-stub.sh
```

The real PP-OCRv6 service smoke waits for model startup, sends a small German image to `/ocr`, and
requires `errorCode == 0`, exactly one result, and consistent `rec_texts`, `rec_scores`,
`rec_boxes`, and `rec_polys` arrays:

```bash
docker build -f docker/paddleocr.Dockerfile -t paperless-paddleocr-server:local .
docker run --rm -d --name paperless-paddleocr-server -p 8080:8080 paperless-paddleocr-server:local
python tests/smoke_paddlex_service.py --url http://localhost:8080 --timeout 900
docker stop paperless-paddleocr-server
```

The real smoke is deliberately manual (`.github/workflows/paddleocr-smoke.yml`) rather than normal
CI because first-time CPU model download and inference are too expensive for every change.

## Troubleshooting and limitations

- `PaddleOCR requires … absolute HTTP(S) URL`: set `PAPERLESS_PADDLEOCR_SERVER_URL`, including its
  scheme and host.
- HTTP 401/403: configure the reverse proxy and `PAPERLESS_PADDLEOCR_API_KEY` with matching bearer
  credentials.
- TLS/CA failure: mount the correct PEM bundle and set `PAPERLESS_PADDLEOCR_CA_BUNDLE`; do not make
  disabled verification a permanent fix.
- First request times out: inspect `paddleocr-server` logs for model download/loading, retain the
  cache volume, then adjust the read timeout only after measuring the host.
- The service interface is PaddleX Basic Serving `/ocr`, not the standalone PaddleOCR Python API.
  A proxy must preserve the JSON body and response arrays.
- Recognition quality, language coverage, and throughput depend on the PP-OCRv6 model and the
  document. This plugin preserves the Paperless PDF/A workflow; it does not add layout reconstruction
  or a separate document-understanding model.

## License and attribution

Released under the [MIT License](LICENSE). This repository was originally based on
[flobernd/paperless-chandra](https://github.com/flobernd/paperless-chandra); the project has been
reworked to use the separate PP-OCRv6 PaddleX service described above. PaddlePaddle, PaddleX, and
PaddleOCR are their respective upstream projects and have their own licenses.
