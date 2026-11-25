-- A claim says "this session is working on this file, wait or ask". One live claim per file.
-- Claims expire (a crashed session never holds a file for long) and end with their session.
CREATE TABLE file_claim (
    id          bigserial PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    session_id  uuid NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    path        text NOT NULL,
    reason      text,
    claimed_at  timestamptz NOT NULL DEFAULT now(),
    expires_at  timestamptz NOT NULL,
    released_at timestamptz
);
CREATE UNIQUE INDEX file_claim_live ON file_claim (project_id, path) WHERE released_at IS NULL;
CREATE INDEX file_claim_session ON file_claim (session_id) WHERE released_at IS NULL;
