-- A session is one Claude Code session (a fork is a new session whose parent is the session it forked from).
ALTER TABLE session
    ADD COLUMN external_id  text UNIQUE,
    ADD COLUMN parent_id    uuid REFERENCES session(id) ON DELETE SET NULL,
    ADD COLUMN cwd          text,
    ADD COLUMN component_id uuid REFERENCES component(id) ON DELETE SET NULL,
    ADD COLUMN source       text,
    ADD COLUMN ended_at     timestamptz,
    ADD COLUMN summary      text;

CREATE INDEX session_active ON session (project_id, last_seen DESC) WHERE ended_at IS NULL;

-- Which files a session edited, for collision warnings between concurrent sessions.
CREATE TABLE file_touch (
    id         bigserial PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    session_id uuid NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    path       text NOT NULL,
    tool       text,
    at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX file_touch_path ON file_touch (project_id, path, at DESC);
CREATE INDEX file_touch_session ON file_touch (session_id, at DESC);

-- Size of each context pack handed to a session: the measurable cost of starting one.
CREATE TABLE context_pack_log (
    id         bigserial PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    session_id uuid REFERENCES session(id) ON DELETE SET NULL,
    tokens     int NOT NULL,
    sections   jsonb NOT NULL DEFAULT '{}',
    truncated  boolean NOT NULL DEFAULT false,
    at         timestamptz NOT NULL DEFAULT now()
);
