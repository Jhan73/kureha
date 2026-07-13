# Production image: ECS Fargate, same container serves the API and the
# LangGraph agent runtime (design.md §1, §20).
FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install dependencies first (layer cache), without the project itself, no
# dev-only tooling (import-linter/pytest/watchfiles never ship to prod).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Now copy the app and install it.
COPY . .
RUN uv sync --frozen --no-dev

FROM python:3.13-slim

RUN groupadd --system app && useradd --system --gid app app

WORKDIR /app

COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
