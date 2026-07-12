# ragbooster served as an HTTP API — build once, run anywhere Docker runs.
# Build:  docker build -t ragbooster .
# Run:    docker run -p 8000:8000 -v ragbooster-data:/data ragbooster
# Then:   curl http://localhost:8000/health

FROM python:3.12-slim

# Keep Python from writing .pyc files / buffering stdout — standard for containers.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RAGBOOSTER_STATE_DIR=/data

WORKDIR /app

# Install deps first so this layer is cached across code-only changes.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[server]"

# Non-root user: don't run the service as root inside the container.
RUN useradd --create-home --uid 1000 ragbooster \
    && mkdir -p /data \
    && chown -R ragbooster:ragbooster /app /data
USER ragbooster

VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "ragbooster.server:app", "--host", "0.0.0.0", "--port", "8000"]
