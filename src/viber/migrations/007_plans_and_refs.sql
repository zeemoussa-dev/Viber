-- A plan is a row, not a file: its content is the specs, bugs, tasks and decisions linked to it.
CREATE TABLE plan (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    key        text NOT NULL,
    title      text NOT NULL CHECK (char_length(title) <= 200),
    goal       text NOT NULL DEFAULT '' CHECK (char_length(goal) <= 300),
    status     text NOT NULL DEFAULT 'Draft',
    source     text,
    source_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, key),
    UNIQUE (project_id, source, source_ref)
);

-- One table for every relation between two things: "this, relation, that, from when, until when".
-- An obsolete relation is ended (valid_to), never deleted. Keys: version = component@semver, fact = its id.
CREATE TABLE ref (
    id         bigserial PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    from_type  text NOT NULL CHECK (from_type IN ('plan','spec','item','decision','component','version','fact','release','entity')),
    from_key   text NOT NULL,
    relation   text NOT NULL CHECK (char_length(relation) <= 40),
    to_type    text NOT NULL CHECK (to_type   IN ('plan','spec','item','decision','component','version','fact','release','entity')),
    to_key     text NOT NULL,
    version_range text CHECK (char_length(version_range) <= 60),
    seq        int,
    note       text CHECK (char_length(note) <= 200),
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to   timestamptz,
    source     text,
    source_ref text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX ref_live ON ref (project_id, from_type, from_key, lower(relation), to_type, to_key) WHERE valid_to IS NULL;
CREATE INDEX ref_to ON ref (project_id, to_type, to_key) WHERE valid_to IS NULL;
CREATE INDEX ref_from ON ref (project_id, from_type, from_key) WHERE valid_to IS NULL;
