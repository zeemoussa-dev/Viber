-- Every backup attempt, and what was found when it was restored into a scratch database and counted.
CREATE TABLE backup_run (
    id              bigserial PRIMARY KEY,
    trigger         text NOT NULL DEFAULT 'manual',        -- scheduled | manual | test
    status          text NOT NULL DEFAULT 'running',       -- running | unverified | ok | failed | pruned
    file            text,
    bytes           bigint,
    sha256          text,
    counts_before   jsonb,
    counts_after    jsonb,
    counts_restored jsonb,
    verified_at     timestamptz,
    verify_note     text CHECK (char_length(verify_note) <= 400),
    error           text CHECK (char_length(error) <= 400),
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz
);
CREATE INDEX backup_run_started ON backup_run (started_at DESC);
