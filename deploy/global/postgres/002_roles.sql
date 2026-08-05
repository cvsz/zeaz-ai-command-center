BEGIN;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zeaz_application') THEN
    CREATE ROLE zeaz_application NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zeaz_scheduler') THEN
    CREATE ROLE zeaz_scheduler NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'zeaz_backup') THEN
    CREATE ROLE zeaz_backup NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
  END IF;
END
$$;

REVOKE ALL ON SCHEMA zeaz FROM PUBLIC;
GRANT USAGE ON SCHEMA zeaz TO zeaz_application, zeaz_scheduler, zeaz_backup;

GRANT SELECT, INSERT, UPDATE, DELETE
  ON ALL TABLES IN SCHEMA zeaz
  TO zeaz_application;

GRANT SELECT, INSERT, UPDATE
  ON zeaz.jobs, zeaz.job_events, zeaz.outbox_events, zeaz.agents, zeaz.audit_events
  TO zeaz_scheduler;

GRANT SELECT
  ON ALL TABLES IN SCHEMA zeaz
  TO zeaz_backup;

GRANT USAGE, SELECT
  ON ALL SEQUENCES IN SCHEMA zeaz
  TO zeaz_application, zeaz_scheduler;

GRANT EXECUTE
  ON FUNCTION zeaz.current_organization_id()
  TO zeaz_application, zeaz_scheduler, zeaz_backup;

GRANT EXECUTE
  ON FUNCTION zeaz.current_user_id()
  TO zeaz_application, zeaz_scheduler, zeaz_backup;

GRANT EXECUTE
  ON FUNCTION zeaz.claim_next_job(uuid, integer)
  TO zeaz_scheduler;

ALTER DEFAULT PRIVILEGES IN SCHEMA zeaz
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO zeaz_application;
ALTER DEFAULT PRIVILEGES IN SCHEMA zeaz
  GRANT SELECT ON TABLES TO zeaz_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA zeaz
  GRANT USAGE, SELECT ON SEQUENCES TO zeaz_application, zeaz_scheduler;

COMMIT;
