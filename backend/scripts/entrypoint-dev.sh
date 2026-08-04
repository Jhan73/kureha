#!/bin/sh
# Dev-only entrypoint (Dockerfile.dev): applies pending Alembic migrations
# before the app starts, so a fresh `postgres_data` volume never boots into
# the RBAC-seed-on-lifespan crash (relation "action_permissions" does not
# exist) that a manual `alembic upgrade head` step is easy to forget.
set -e

uv run alembic upgrade head

exec "$@"
