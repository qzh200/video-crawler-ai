# syntax=docker/dockerfile:1.7
ARG PYTHON_IMAGE=python:3.12.13-slim-bookworm
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=10

WORKDIR /app

# Codex must verify Crawl4AI/Chromium system dependencies against the selected
# Crawl4AI release and pin the base images before production release.
COPY pyproject.toml README.md /app/
COPY src /app/src
COPY alembic.ini /app/alembic.ini
COPY migrations /app/migrations

RUN --mount=type=cache,target=/root/.cache/pip python -m pip install .

# Crawl4AI uses Playwright. Installing through Playwright keeps the Chromium
# revision aligned with the pinned Python dependency and installs its Linux
# shared-library/font dependencies in the same image used by Worker/login.
RUN python -m playwright install --with-deps chromium

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "video_crawler.main:app", "--host", "0.0.0.0", "--port", "8000"]
