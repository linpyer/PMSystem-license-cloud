FROM python:3.12.10-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml constraints.txt README.md ./
COPY app ./app
RUN python -m pip wheel --constraint constraints.txt --wheel-dir /wheels .

FROM python:3.12.10-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN groupadd --system --gid 10001 license \
    && useradd --system --uid 10001 --gid license --home-dir /nonexistent --shell /usr/sbin/nologin license \
    && python -m venv /opt/venv

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels ddrec-license-server \
    && rm -rf /wheels \
    && find /opt/venv/lib/python3.12/site-packages -type d -name tests -prune -exec rm -rf '{}' + \
    && find /opt/venv/lib/python3.12/site-packages -type d -name __pycache__ -prune -exec rm -rf '{}' +

WORKDIR /srv/license-server
COPY --chown=license:license alembic.ini ./
COPY --chown=license:license alembic ./alembic

USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health/live', timeout=3).read()"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "127.0.0.1"]
