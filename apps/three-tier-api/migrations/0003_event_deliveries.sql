-- Apply after 0002_security_events.sql for the local event-worker milestone.
-- event_id uniqueness makes consumer-side reprocessing idempotent.
BEGIN;

CREATE TABLE IF NOT EXISTS public.event_deliveries (
    id BIGSERIAL PRIMARY KEY,
    subject VARCHAR(128) NOT NULL CHECK (length(btrim(subject)) > 0),
    event_id UUID NOT NULL UNIQUE,
    payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.event_deliveries OWNER TO labuser;

CREATE INDEX IF NOT EXISTS event_deliveries_recent_idx
    ON public.event_deliveries (received_at DESC, id DESC);

COMMIT;
