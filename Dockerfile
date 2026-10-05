# check=skip=SecretsUsedInArgOrEnv
# Orderdesk demo image: the React console built with Node, served by the FastAPI app.
# Holds the generated world (catalogue, customers, history) and the fitted confidence model.
# It never holds data/eval (messages or ground truth): the product doesn't need them.

ARG NODE_IMAGE=node:22-bookworm-slim
ARG PYTHON_IMAGE=python:3.11-slim-bookworm

FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
# An optional build secret "ca" adds a corporate/proxy CA for the build only; it never lands in a layer.
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/ca; fi; npm ci --no-audit --no-fund
COPY web/ ./
# The demo login buttons fill this in; it's the public demo password, not a secret.
ARG VITE_DEMO_PASSWORD=orderdesk-demo
ENV VITE_DEMO_PASSWORD=${VITE_DEMO_PASSWORD}
RUN npm run build

FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY api/pyproject.toml api/
COPY api/src api/src
RUN --mount=type=secret,id=ca,required=false \
    if [ -f /run/secrets/ca ]; then export PIP_CERT=/run/secrets/ca; fi; pip install ./api
COPY api/alembic.ini api/alembic.ini
COPY api/alembic api/alembic
COPY data/world data/world
COPY data/model data/model
COPY --from=web /web/dist web/dist
COPY scripts/start.sh scripts/start.sh
RUN useradd --create-home --uid 10001 app && mkdir -p runs && chown app runs
USER app
ENV ORDERDESK_ROOT=/app ORDERDESK_DATA=/app/data ORDERDESK_STATIC=/app/web/dist PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"
CMD ["sh", "scripts/start.sh"]
