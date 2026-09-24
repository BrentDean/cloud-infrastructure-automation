-- Apply AFTER 0001_incidents.sql and before either application runtime.
-- Minimal sanitized Cowrie failed-login intake; never store raw log JSON.
BEGIN;

CREATE TABLE IF NOT EXISTS public.security_events (
    id UUID PRIMARY KEY,
    incident_id UUID NOT NULL REFERENCES public.incidents (id) ON DELETE RESTRICT,
    source VARCHAR(20) NOT NULL CHECK (source = 'cowrie'),
    source_event_id VARCHAR(128) NOT NULL CHECK (length(btrim(source_event_id)) > 0),
    event_type VARCHAR(40) NOT NULL CHECK (event_type = 'cowrie.login.failed'),
    source_ip INET NOT NULL,
    username VARCHAR(128) NOT NULL CHECK (length(btrim(username)) > 0),
    observed_at TIMESTAMPTZ NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_event_id)
);

ALTER TABLE public.security_events OWNER TO labuser;

CREATE INDEX IF NOT EXISTS security_events_incident_recent_idx
    ON public.security_events (incident_id, observed_at DESC, id DESC);

COMMIT;
