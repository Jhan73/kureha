-- Creates the restricted runtime role RLS policies actually run against.
--
-- Blocker fixed here (flagged during PR 2's review, tasks.md task 2.9):
-- `app_user` (POSTGRES_USER in docker-compose.yml) is the Postgres bootstrap
-- role -- confirmed superuser + BYPASSRLS. Postgres superusers unconditionally
-- bypass RLS regardless of `ENABLE`/`FORCE ROW LEVEL SECURITY` on a table, so
-- every RLS-isolation test run against `app_user` would trivially pass
-- whether or not the policies are actually correct (false-green on the single
-- most safety-critical layer in the system). Migrations still run as
-- `app_user` (schema ownership, matching the rest of Phase 2), but the
-- application/tests connect as `app_runtime` for anything RLS is meant to
-- enforce.
--
-- Role creation (CREATE ROLE) needs superuser/CREATEROLE, the same
-- constraint that already applies to `CREATE EXTENSION` in
-- 01_extensions.sql -- so, same convention, it runs once here as part of
-- Postgres container initialization, not inside an Alembic migration. On
-- RDS this becomes part of the master-user bootstrap step alongside the
-- extensions (tasks.md task 16.1 already flags that bootstrap step; the role
-- creation belongs next to it -- deferred to Phase 16, not done here).
--
-- Table-level GRANTs for `app_runtime` (SELECT/INSERT/UPDATE/DELETE, plus the
-- audit_logs REVOKE) are NOT here: no tables exist yet at container-init
-- time. Those live in migration 2.9 (backend/migrations/versions/*_rls_*),
-- the same split already used for `app_user`'s audit_logs REVOKE/GRANT
-- (migration 776b456050fe): role bootstrap is infra, object privileges are a
-- migration concern.
--
-- CAVEAT (same as 01_extensions.sql): docker-entrypoint-initdb.d scripts only
-- run once, the first time the container initializes an EMPTY data
-- directory. An existing local `postgres_data` volume created before this
-- file was added will NOT pick it up automatically -- run
-- `docker compose down -v` (drops the volume) or apply this script manually
-- via `psql` against the running container.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_runtime') THEN
    CREATE ROLE app_runtime WITH
      LOGIN
      PASSWORD 'dev_only_password'
      NOSUPERUSER
      NOCREATEDB
      NOCREATEROLE
      NOREPLICATION
      NOBYPASSRLS;
  END IF;
END $$;

GRANT CONNECT ON DATABASE kureha_dev TO app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;
