# A single image for api, migrate and the 5 workers: only the command changes.

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0
WORKDIR /app
# Dependencies first: this layer stays cached as long as uv.lock does not change.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --create-home --uid 10001 vigia
WORKDIR /app
COPY --from=build --chown=vigia:vigia /app/.venv /app/.venv
COPY --chown=vigia:vigia alembic.ini ./
COPY --chown=vigia:vigia migrations ./migrations
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
USER vigia
EXPOSE 8000
CMD ["uvicorn", "--factory", "vigia.api.main:create_app", "--host", "0.0.0.0", "--port", "8000"]
