# syntax=docker/dockerfile:1.7
# Three-stage build (chapter 29.6): a Node stage runs the Vite build of the
# front-end, a Python builder resolves dependencies from uv.lock, and a slim
# runtime copies web/dist and the virtual environment and runs as a non-root
# user. Model weights are not baked in; HF_HOME points at the mounted cache
# volume so the first start downloads them once (or `keel index` does).

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG NODE_IMAGE=node:22-alpine

FROM ghcr.io/astral-sh/uv:0.5 AS uv

FROM ${NODE_IMAGE} AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

FROM ${PYTHON_IMAGE} AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --extra export
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra export

FROM ${PYTHON_IMAGE} AS runtime
LABEL org.opencontainers.image.title="keel" \
      org.opencontainers.image.description="Grounded answers to business questions about SEC filings from one LLM call" \
      org.opencontainers.image.licenses="MIT"
RUN groupadd --system keel \
    && useradd --system --gid keel --home-dir /app --shell /usr/sbin/nologin keel \
    && mkdir -p /app/index /app/cache /app/logs /app/demo/answer_cache \
    && chown -R keel:keel /app
WORKDIR /app
COPY --from=builder --chown=keel:keel /app /app
COPY --from=web --chown=keel:keel /web/dist /app/web/dist
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/app/cache/hf \
    KEEL_SERVER__HOST=0.0.0.0 \
    KEEL_SERVER__PORT=8000
USER keel
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
ENTRYPOINT ["keel"]
CMD ["serve"]
