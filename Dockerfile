# OmniKB production image
#
# Two-stage build to keep the runtime layer small:
# - builder: installs Python deps + downloads patchright chromium
# - runtime: ffmpeg + slim libs + final venv copy
#
# Build:
#   docker build -t omnikb:latest .
# Run (dev, mounts ./data):
#   docker run --rm -p 6886:6886 --env-file .env -v $(pwd)/data:/app/data omnikb:latest
# Run (compose, recommended):
#   docker compose up

# ─── Stage 1 · build ─────────────────────────────────────────────
FROM python:3.13-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    VIRTUAL_ENV=/opt/venv

# Build deps: gcc/g++ for sentence-transformers wheels that need compilation,
# git for any VCS-pinned deps, plus libgomp1 needed by ctranslate2 at runtime
# (we keep it in builder so wheels can link).
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libgomp1 \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv "$VIRTUAL_ENV"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install Python deps first — leverages docker layer cache across code edits.
COPY backend/requirements.lock.txt /tmp/requirements.lock.txt
RUN pip install --upgrade pip wheel setuptools && \
    pip install -r /tmp/requirements.lock.txt

# Pre-install patchright browser. The default install location lives inside
# the user's home; we redirect it to /opt/playwright so the runtime stage
# can copy it in one shot.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
RUN python -m patchright install chromium --with-deps || \
    python -m playwright install chromium --with-deps || \
    (echo "ERROR: patchright/playwright browser install failed — JS rendering path is required for web agent functionality" && exit 1)


# ─── Stage 2 · runtime ──────────────────────────────────────────
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMNIKB_HOST=0.0.0.0 \
    OMNIKB_PORT=6886 \
    USE_TF=0 \
    USE_JAX=0 \
    VIRTUAL_ENV=/opt/venv \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright \
    FASTEMBED_CACHE_PATH=/app/.cache/fastembed \
    HF_HOME=/app/.cache/huggingface

# Runtime system deps:
# - ffmpeg          (faster-whisper video/audio decoding)
# - libgomp1        (ctranslate2 OpenMP)
# - chromium runtime libs (for patchright)
# - tini            (PID 1 reaper)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libgomp1 \
        libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
        libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
        libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
        libasound2 libatspi2.0-0 \
        tini \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Copy venv + browsers from builder.
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder /opt/playwright /opt/playwright
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Application source.
WORKDIR /app
COPY backend /app/backend
COPY frontend /app/frontend

# Non-root runtime user.
RUN useradd --create-home --shell /bin/bash --uid 1000 omnikb && \
    mkdir -p /app/data /app/.cache/fastembed /app/.cache/huggingface && \
    chown -R omnikb:omnikb /app /opt/playwright
USER omnikb

WORKDIR /app/backend

EXPOSE 6886

# Health probe — relies on /health which now reports config_issues too.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:6886/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "main.py"]
