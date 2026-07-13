-- Enables extensions required by later Alembic migrations
-- (backend/migrations, design.md §4.1) before the app connects.
--
-- CREATE EXTENSION requires superuser privileges the migration-time app_user
-- role may not have (e.g. on RDS), so it runs once here as part of Postgres
-- container initialization instead of inside a migration.
--
-- btree_gist backs the EXCLUDE USING gist constraints used for anti
-- double-booking (appointments) and anti-overlap (shifts).
CREATE EXTENSION IF NOT EXISTS btree_gist;
