# The worker: Python with LibreOffice, which turns Word documents into PDFs (Decision.md D-34).
#   docker compose up -d --build worker
FROM python:3.12-slim-trixie

# LibreOffice Writer without a desktop, and fonts that match the common Word fonts' widths
# (Liberation for Arial, Times New Roman and Courier New), so converted pages keep their layout.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui fonts-liberation fonts-dejavu-core libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"
WORKDIR /app

# Dependencies first, so a code change does not reinstall them. The dev-only workspace packages
# (shipgen, evals) are needed only for their names in the lock file.
COPY pyproject.toml uv.lock ./
COPY shipgen/pyproject.toml shipgen/pyproject.toml
COPY evals/pyproject.toml evals/pyproject.toml
RUN uv sync --frozen --no-dev --no-install-project --no-install-workspace
COPY src src
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 shipready
USER shipready
CMD ["celery", "-A", "shipready.worker", "worker", "--loglevel", "info", "--concurrency", "2"]
