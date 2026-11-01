-- Hermes persistence schema. Safe to apply more than once.
--
-- Times named t* are the gateway's monotonic clock, in seconds. They order
-- events inside one run and are not comparable across runs; wall-clock time
-- lives on experiment_runs only.

CREATE TABLE IF NOT EXISTS experiment_runs (
    id          bigserial PRIMARY KEY,
    name        text NOT NULL,
    condition   text NOT NULL,          -- fifo, priority or exchange (the gateway name in the event log)
    seed        integer,
    params      jsonb NOT NULL DEFAULT '{}',
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

-- One row per request, updated as its events arrive.
CREATE TABLE IF NOT EXISTS requests (
    run_id      bigint NOT NULL REFERENCES experiment_runs (id) ON DELETE CASCADE,
    request_id  text NOT NULL,
    gateway     text NOT NULL,
    tenant_id   text,                   -- who the request belongs to; null for runs recorded before tenants
    t_request   double precision NOT NULL,
    t_end       double precision,       -- result or cancel; null while in flight
    outcome     text CHECK (outcome IN ('result', 'cancelled')),
    status      integer,                -- final HTTP status; null if cancelled or sending failed
    error       text,                   -- set if sending raised
    forwards    integer NOT NULL DEFAULT 0,
    rejections  integer NOT NULL DEFAULT 0,  -- 429s: wasted retries
    PRIMARY KEY (run_id, request_id)
);

ALTER TABLE requests ADD COLUMN IF NOT EXISTS tenant_id text;  -- for a database created before tenants

-- One row per bid placed, or placed again at a higher price by aging.
CREATE TABLE IF NOT EXISTS orders (
    id          bigserial PRIMARY KEY,
    run_id      bigint NOT NULL,
    request_id  text NOT NULL,
    attempt     integer NOT NULL,       -- calls sent before this bid; rises after a 429
    kind        text NOT NULL CHECK (kind IN ('bid', 'reprice')),
    offered     integer NOT NULL,       -- price on the book, in ticks
    asked       integer,                -- price before the credit cap (bid only)
    previous    integer,                -- price it replaced (reprice only)
    t           double precision NOT NULL,
    FOREIGN KEY (run_id, request_id) REFERENCES requests (run_id, request_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS orders_request ON orders (run_id, request_id);

-- One row per slice won.
CREATE TABLE IF NOT EXISTS fills (
    id          bigserial PRIMARY KEY,
    run_id      bigint NOT NULL,
    request_id  text NOT NULL,
    attempt     integer NOT NULL,
    paid        integer NOT NULL,       -- trade price
    offered     integer NOT NULL,       -- what the winning bid offered
    t           double precision NOT NULL,
    FOREIGN KEY (run_id, request_id) REFERENCES requests (run_id, request_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS fills_request ON fills (run_id, request_id);
