#!/usr/bin/env bash
# End-to-end pipeline test against the deterministic PaddleX server.
# Usage: tests/e2e/run-stub.sh   (from anywhere; needs docker + repo venv)
set -euo pipefail
cd "$(dirname "$0")"
REPO_ROOT=$(cd ../.. && pwd)
PY="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
E2E_IMAGE="${PAPERLESS_E2E_IMAGE:-paperless-paddleocr-e2e:local}"
PAPERLESS_BASE_IMAGE="${PAPERLESS_BASE_IMAGE:-ghcr.io/paperless-ngx/paperless-ngx:3.0.3}"
SKIP_BUILD="${PAPERLESS_E2E_SKIP_BUILD:-false}"

cleanup() { docker compose -f docker-compose.stub.yml down -v; }
trap cleanup EXIT

rm -rf consume && mkdir -p consume
"$PY" make_test_page.py consume/e2e-test.png
"$PY" make_test_page.py consume/e2e-rotated.png 180

if [ "$SKIP_BUILD" != "true" ]; then
  docker build \
    --file "$REPO_ROOT/docker/e2e.Dockerfile" \
    --build-arg "PAPERLESS_IMAGE=$PAPERLESS_BASE_IMAGE" \
    --tag "$E2E_IMAGE" \
    "$REPO_ROOT"
fi
PAPERLESS_E2E_IMAGE="$E2E_IMAGE" \
  PAPERLESS_BASE_IMAGE="$PAPERLESS_BASE_IMAGE" \
  docker compose -f docker-compose.stub.yml up -d --no-build

"$PY" assert_e2e.py \
  --expect "PAPERLESS PADDLEOCR STUB OK" --expect "Stub Rechnung 2026-0042" \
  --expect-docs 2 --assert-upright e2e-rotated --timeout 600
echo "== stub e2e passed =="
