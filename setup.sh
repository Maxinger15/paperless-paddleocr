#!/bin/bash
# Bootstrap paperless-paddleocr inside a paperless-ngx Docker container.
#
# Mount this script (plus the matching paperless-paddleocr wheel/sdist)
# under /custom-cont-init.d/ - the paperless-ngx base image runs every
# executable in that directory before starting paperless itself.
#
# OCR recognition is delegated to a separate PP-OCRv6 PaddleX HTTP service;
# see examples/docker-compose.yml for a matching runtime config. This script
# installs no native libraries, Paddle runtime, or model weights of its own.
#
# A pre-built artifact is REQUIRED next to this script - paperless-paddleocr
# is not published to PyPI. The script supports both shapes:
#   * paperless_paddleocr-*.tar.gz (sdist)
#   * paperless_paddleocr-*.whl    (wheel - any version, first match wins)
#
# Obtain one with either of:
#   pip wheel --no-deps "git+https://github.com/flobernd/paperless-paddleocr.git@v0.1.0"
#   # or build docker/builder.Dockerfile and copy its /dist output
#
# The install is idempotent: repeated container restarts skip work that
# is already done.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARBALLS=()
# First matching artifact wins. shopt avoids a literal glob string
# in the unmatched case.
shopt -s nullglob
TARBALLS=("${SCRIPT_DIR}"/paperless_paddleocr-*.tar.gz)
WHEELS=("${SCRIPT_DIR}"/paperless_paddleocr-*.whl)
shopt -u nullglob

# ---------------------------------------------------------------------------
# Python package
# ---------------------------------------------------------------------------
PACKAGE_NAME="paperless-paddleocr"

is_installed() {
    pip show "${PACKAGE_NAME}" >/dev/null 2>&1
}

if is_installed; then
    echo "${PACKAGE_NAME} already installed - skipping pip install"
else
    if [ ${#TARBALLS[@]} -gt 0 ]; then
        echo "=== Installing ${PACKAGE_NAME} from ${TARBALLS[0]} ==="
        pip install --no-cache-dir "${TARBALLS[0]}"
    elif [ ${#WHEELS[@]} -gt 0 ]; then
        echo "=== Installing ${PACKAGE_NAME} from ${WHEELS[0]} ==="
        pip install --no-cache-dir "${WHEELS[0]}"
    else
        echo "ERROR: no paperless-paddleocr artifact found next to setup.sh." >&2
        echo "       Expected one of:" >&2
        echo "         ${SCRIPT_DIR}/paperless_paddleocr-*.tar.gz" >&2
        echo "         ${SCRIPT_DIR}/paperless_paddleocr-*.whl" >&2
        echo "       See docker/builder.Dockerfile for how to build one." >&2
        exit 1
    fi
fi

echo "=== paperless-paddleocr bootstrap complete ==="
