FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY falae ./falae
RUN pip install --no-cache-dir .

# Settings come from .env at runtime (compose.yaml, or `docker run --env-file .env`); nothing is
# baked in, and .env itself is docker-ignored so secrets never land in an image layer.
# On Cloud Run, pass them with --set-env-vars / --set-secrets. Cloud Run also sets PORT.
CMD exec uvicorn falae.api:app --host 0.0.0.0 --port ${PORT:-8013}
