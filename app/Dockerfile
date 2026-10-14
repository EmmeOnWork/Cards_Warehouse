# syntax=docker/dockerfile:1

# --- base: the pinned Python and uv shared by build and dev ---
FROM python:3.12-slim-trixie AS base
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# --- build: resolve dependencies from uv.lock into a virtual environment ---
FROM base AS build
ENV UV_COMPILE_BYTECODE=1
WORKDIR /app

# Dependencies first: this layer is reused until uv.lock changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

COPY pyproject.toml uv.lock ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

# --- dev: the toolbox for tests, used through app/compose.yaml (make test) ---
FROM base AS dev
# Docker CLI and buildx, to drive the PC's Docker through its mounted socket.
COPY --from=docker:29.5.2-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=docker:29.5.2-cli /usr/local/libexec/docker/cli-plugins/docker-buildx /usr/local/libexec/docker/cli-plugins/docker-buildx
# Outside the mounted sources, so the PC's files never hide it.
ENV UV_PROJECT_ENVIRONMENT=/venv
WORKDIR /work/app
CMD ["bash"]

# --- runtime: only the virtual environment, no uv, no sources ---
FROM python:3.12-slim-trixie
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"
# Numeric user, so Kubernetes can verify runAsNonRoot.
USER 10001
EXPOSE 8000

# Last, so a new version only rebuilds this layer.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

CMD ["uvicorn", "cards_warehouse.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
