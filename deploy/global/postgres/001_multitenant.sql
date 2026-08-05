BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS zeaz;

CREATE OR REPLACE FUNCTION zeaz.current_organization_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.organization_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION zeaz.current_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
AS $$
  SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
$$;

CREATE TABLE IF NOT EXISTS zeaz.users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  username text NOT NULL UNIQUE,
  email text UNIQUE,
  password_hash text NOT NULL,
  display_name text NOT NULL DEFAULT '',
  locale text NOT NULL DEFAULT 'en',
  timezone text NOT NULL DEFAULT 'UTC',
  mfa_enabled boolean NOT NULL DEFAULT false,
  disabled_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zeaz.organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug text NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
  default_locale text NOT NULL DEFAULT 'en',
  default_timezone text NOT NULL DEFAULT 'UTC',
  max_agents integer NOT NULL DEFAULT 5 CHECK (max_agents >= 0),
  max_concurrent_jobs integer NOT NULL DEFAULT 4 CHECK (max_concurrent_jobs >= 1),
  artifact_quota_bytes bigint NOT NULL DEFAULT 10737418240 CHECK (artifact_quota_bytes >= 0),
  created_by uuid NOT NULL REFERENCES zeaz.users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zeaz.memberships (
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES zeaz.users(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('owner', 'admin', 'operator', 'developer', 'viewer', 'auditor')),
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('invited', 'active', 'suspended')),
  invited_by uuid REFERENCES zeaz.users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS zeaz.projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  slug text NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}$'),
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  repository_provider text,
  repository_external_id text,
  repository_url text,
  default_branch text NOT NULL DEFAULT 'main',
  allowed_providers jsonb NOT NULL DEFAULT '[]'::jsonb,
  policy jsonb NOT NULL DEFAULT '{}'::jsonb,
  retention_days integer NOT NULL DEFAULT 30 CHECK (retention_days >= 1),
  created_by uuid NOT NULL REFERENCES zeaz.users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, slug)
);

CREATE TABLE IF NOT EXISTS zeaz.agents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  name text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
  public_key text NOT NULL,
  credential_version integer NOT NULL DEFAULT 1,
  protocol_version text NOT NULL,
  status text NOT NULL DEFAULT 'offline' CHECK (status IN ('pending', 'online', 'offline', 'disabled', 'revoked')),
  capabilities jsonb NOT NULL DEFAULT '{}'::jsonb,
  capacity integer NOT NULL DEFAULT 1 CHECK (capacity >= 1),
  last_seen_at timestamptz,
  disabled_at timestamptz,
  created_by uuid NOT NULL REFERENCES zeaz.users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS zeaz.project_agents (
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES zeaz.projects(id) ON DELETE CASCADE,
  agent_id uuid NOT NULL REFERENCES zeaz.agents(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project_id, agent_id)
);

CREATE TABLE IF NOT EXISTS zeaz.agent_enrollment_tokens (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  token_hash bytea NOT NULL UNIQUE,
  requested_name text NOT NULL,
  expires_at timestamptz NOT NULL,
  consumed_at timestamptz,
  created_by uuid NOT NULL REFERENCES zeaz.users(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (expires_at > created_at)
);

CREATE TABLE IF NOT EXISTS zeaz.jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES zeaz.projects(id) ON DELETE CASCADE,
  agent_id uuid REFERENCES zeaz.agents(id) ON DELETE SET NULL,
  requested_by uuid NOT NULL REFERENCES zeaz.users(id),
  provider_id text NOT NULL,
  status text NOT NULL DEFAULT 'queued' CHECK (
    status IN ('queued', 'leased', 'running', 'succeeded', 'failed', 'stopping', 'stopped', 'timed_out', 'orphaned', 'dead_letter')
  ),
  priority smallint NOT NULL DEFAULT 100,
  payload jsonb NOT NULL,
  policy_snapshot jsonb NOT NULL DEFAULT '{}'::jsonb,
  idempotency_key text NOT NULL,
  attempt integer NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  max_attempts integer NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),
  available_at timestamptz NOT NULL DEFAULT now(),
  lease_owner uuid REFERENCES zeaz.agents(id) ON DELETE SET NULL,
  lease_expires_at timestamptz,
  started_at timestamptz,
  finished_at timestamptz,
  error_code text,
  error_message text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS zeaz.job_events (
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES zeaz.jobs(id) ON DELETE CASCADE,
  sequence bigint NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, sequence)
);

CREATE TABLE IF NOT EXISTS zeaz.artifacts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES zeaz.projects(id) ON DELETE CASCADE,
  job_id uuid NOT NULL REFERENCES zeaz.jobs(id) ON DELETE CASCADE,
  kind text NOT NULL,
  storage_key text NOT NULL,
  content_type text NOT NULL DEFAULT 'application/octet-stream',
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  sha256 text NOT NULL CHECK (sha256 ~ '^[a-f0-9]{64}$'),
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, storage_key)
);

CREATE TABLE IF NOT EXISTS zeaz.api_keys (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  key_prefix text NOT NULL,
  secret_hash bytea NOT NULL UNIQUE,
  scopes text[] NOT NULL DEFAULT ARRAY[]::text[],
  project_ids uuid[] NOT NULL DEFAULT ARRAY[]::uuid[],
  expires_at timestamptz,
  last_used_at timestamptz,
  revoked_at timestamptz,
  created_by uuid NOT NULL REFERENCES zeaz.users(id),
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zeaz.audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  actor_user_id uuid REFERENCES zeaz.users(id),
  actor_agent_id uuid REFERENCES zeaz.agents(id),
  request_id text NOT NULL,
  action text NOT NULL,
  resource_type text NOT NULL,
  resource_id text,
  outcome text NOT NULL CHECK (outcome IN ('success', 'denied', 'failure')),
  source_ip inet,
  user_agent text,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  previous_hash text,
  event_hash text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS zeaz.outbox_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES zeaz.organizations(id) ON DELETE CASCADE,
  aggregate_type text NOT NULL,
  aggregate_id uuid NOT NULL,
  event_type text NOT NULL,
  payload jsonb NOT NULL,
  available_at timestamptz NOT NULL DEFAULT now(),
  attempts integer NOT NULL DEFAULT 0,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS memberships_user_idx ON zeaz.memberships (user_id, status);
CREATE INDEX IF NOT EXISTS projects_org_idx ON zeaz.projects (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS agents_org_status_idx ON zeaz.agents (organization_id, status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS jobs_dispatch_idx ON zeaz.jobs (status, available_at, priority, created_at)
  WHERE status IN ('queued', 'leased');
CREATE INDEX IF NOT EXISTS jobs_org_created_idx ON zeaz.jobs (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS job_events_org_job_idx ON zeaz.job_events (organization_id, job_id, sequence);
CREATE INDEX IF NOT EXISTS artifacts_org_job_idx ON zeaz.artifacts (organization_id, job_id);
CREATE INDEX IF NOT EXISTS audit_org_created_idx ON zeaz.audit_events (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS outbox_pending_idx ON zeaz.outbox_events (available_at, created_at)
  WHERE published_at IS NULL;

ALTER TABLE zeaz.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE zeaz.users FORCE ROW LEVEL SECURITY;
CREATE POLICY users_self_policy ON zeaz.users
  USING (id = zeaz.current_user_id())
  WITH CHECK (id = zeaz.current_user_id());

ALTER TABLE zeaz.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE zeaz.organizations FORCE ROW LEVEL SECURITY;
CREATE POLICY organizations_tenant_policy ON zeaz.organizations
  USING (id = zeaz.current_organization_id())
  WITH CHECK (id = zeaz.current_organization_id());

DO $$
DECLARE
  table_name text;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'memberships',
    'projects',
    'agents',
    'project_agents',
    'agent_enrollment_tokens',
    'jobs',
    'job_events',
    'artifacts',
    'api_keys',
    'audit_events',
    'outbox_events'
  ]
  LOOP
    EXECUTE format('ALTER TABLE zeaz.%I ENABLE ROW LEVEL SECURITY', table_name);
    EXECUTE format('ALTER TABLE zeaz.%I FORCE ROW LEVEL SECURITY', table_name);
    EXECUTE format(
      'CREATE POLICY %I ON zeaz.%I USING (organization_id = zeaz.current_organization_id()) WITH CHECK (organization_id = zeaz.current_organization_id())',
      table_name || '_tenant_policy',
      table_name
    );
  END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION zeaz.claim_next_job(p_agent_id uuid, p_lease_seconds integer DEFAULT 60)
RETURNS SETOF zeaz.jobs
LANGUAGE plpgsql
SECURITY INVOKER
AS $$
BEGIN
  RETURN QUERY
  WITH candidate AS (
    SELECT j.id
    FROM zeaz.jobs j
    JOIN zeaz.project_agents pa
      ON pa.organization_id = j.organization_id
     AND pa.project_id = j.project_id
     AND pa.agent_id = p_agent_id
    WHERE j.organization_id = zeaz.current_organization_id()
      AND j.status = 'queued'
      AND j.available_at <= now()
      AND (j.agent_id IS NULL OR j.agent_id = p_agent_id)
    ORDER BY j.priority ASC, j.created_at ASC
    FOR UPDATE OF j SKIP LOCKED
    LIMIT 1
  )
  UPDATE zeaz.jobs j
     SET status = 'leased',
         agent_id = p_agent_id,
         lease_owner = p_agent_id,
         lease_expires_at = now() + make_interval(secs => p_lease_seconds),
         attempt = attempt + 1,
         updated_at = now()
    FROM candidate
   WHERE j.id = candidate.id
  RETURNING j.*;
END
$$;

COMMIT;
