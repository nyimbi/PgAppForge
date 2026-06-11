# ── Build stage ───────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps for psycopg2-binary, weasyprint, reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev libffi-dev libxml2-dev libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/ requirements/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements/base.txt \
                               -r requirements/postgres.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

LABEL maintainer="PgAppForge Contributors"
LABEL description="PgAppForge ERP + Fintech Platform"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_APP=app:create_app \
    FLASK_ENV=production \
    PGAPPFORGE_ENV=production

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libxml2 libxslt1.1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1001 pgappforge \
    && useradd --uid 1001 --gid pgappforge --no-create-home pgappforge

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application
COPY --chown=pgappforge:pgappforge . .

# Optional: install optional fintech deps (PyJWT for Keycloak/Clerk, reportlab for PDFs)
RUN pip install --no-cache-dir \
    PyJWT==2.8.0 \
    reportlab==4.2.5 \
    cryptography>=42.0 \
    || true   # non-fatal — app degrades gracefully without these

USER pgappforge

EXPOSE 8080

# Gunicorn with 4 workers; override CMD in docker-compose for dev
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "4", \
     "--worker-class", "sync", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:create_app()"]
