-- Apply explicitly before deploying either application runtime; never in Pod startup.
-- The existing disposable lab's labuser role owns all incident data.
BEGIN;

CREATE TABLE IF NOT EXISTS public.incidents (
    id UUID PRIMARY KEY,
    title VARCHAR(120) NOT NULL CHECK (length(btrim(title)) > 0),
    description VARCHAR(2000) NOT NULL CHECK (length(btrim(description)) > 0),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status VARCHAR(20) NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'investigating', 'resolved')),
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    notes VARCHAR(4000),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.incidents OWNER TO labuser;

CREATE INDEX IF NOT EXISTS incidents_recent_idx
    ON public.incidents (created_at DESC, id DESC);

COMMIT;
