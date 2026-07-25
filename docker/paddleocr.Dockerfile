# Dedicated PP-OCRv6 CPU service. It is deliberately separate from the
# paperless image: the parser talks to this container only over HTTP.
FROM python:3.10.20-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir \
        paddlepaddle==3.2.1 \
        "paddlex[ocr-core]==3.7.2" \
        paddleocr==3.7.0 \
    && paddlex --install serving

COPY docker/OCR.yaml /app/OCR.yaml
COPY docker/paddleocr_healthcheck.py /usr/local/bin/paddleocr-healthcheck

EXPOSE 8080

# This only confirms that a TCP listener exists. Use the contract smoke test
# to verify that model loading and inference are ready.
HEALTHCHECK --interval=15s --timeout=3s --start-period=30s --retries=20 \
    CMD ["python", "/usr/local/bin/paddleocr-healthcheck"]

CMD ["paddlex", "--serve", "--pipeline", "/app/OCR.yaml", "--host", "0.0.0.0", "--port", "8080", "--device", "cpu"]
