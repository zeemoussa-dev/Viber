CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE project (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key         text NOT NULL UNIQUE,
    name        text NOT NULL,
    settings    jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Atomic per-project counters: item keys, bug numbers.
CREATE TABLE counter (
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        text NOT NULL,
    value       bigint NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, name)
);

CREATE TABLE component (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    key         text NOT NULL,
    kind        text NOT NULL DEFAULT 'service',
    repo        text,
    path        text,
    lifecycle   text NOT NULL DEFAULT 'active',
    meta        jsonb NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, key)
);

-- One table for all work: task, bug, story, idea, chore, spike.
-- status is free text in v0 so legacy vocabularies import unchanged; transitions are validated later.
CREATE TABLE item (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    key         text NOT NULL,
    kind        text NOT NULL,
    lane        text NOT NULL DEFAULT 'quick',
    status      text NOT NULL DEFAULT 'Open',
    severity    text,
    area        text,
    title       text NOT NULL,
    body        text NOT NULL DEFAULT '',
    gate        text NOT NULL DEFAULT 'clear',
    gate_reason text,
    found_on    date,
    data        jsonb NOT NULL DEFAULT '{}',
    source      text,
    source_ref  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    tsv         tsvector GENERATED ALWAYS AS
                (to_tsvector('english'::regconfig, coalesce(title,'') || ' ' || coalesce(body,''))) STORED,
    UNIQUE (project_id, key),
    UNIQUE (project_id, source, source_ref)
);
CREATE INDEX item_tsv ON item USING gin (tsv);
CREATE INDEX item_status ON item (project_id, kind, status);

CREATE TABLE item_component (
    item_id      uuid NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    component_id uuid NOT NULL REFERENCES component(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, component_id)
);

-- Keys are strings as written in the source (ADR-141, ADR-v2.060, ADR-v3.004).
CREATE TABLE decision (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    key           text NOT NULL,
    title         text NOT NULL,
    status        text NOT NULL DEFAULT 'Accepted',
    decided_on    date,
    context       text NOT NULL DEFAULT '',
    decision      text NOT NULL DEFAULT '',
    alternatives  text NOT NULL DEFAULT '',
    consequences  text NOT NULL DEFAULT '',
    supersedes    text,
    superseded_by text,
    data          jsonb NOT NULL DEFAULT '{}',
    source        text,
    source_ref    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    tsv           tsvector GENERATED ALWAYS AS
                  (to_tsvector('english'::regconfig,
                     coalesce(title,'') || ' ' || coalesce(context,'') || ' ' || coalesce(decision,''))) STORED,
    UNIQUE (project_id, key),
    UNIQUE (project_id, source, source_ref)
);
CREATE INDEX decision_tsv ON decision USING gin (tsv);

-- The changelog is a query over this table.
CREATE TABLE change (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    component_id uuid REFERENCES component(id) ON DELETE SET NULL,
    occurred_on  date NOT NULL,
    kind         text NOT NULL DEFAULT 'change',
    summary      text NOT NULL,
    body         text NOT NULL DEFAULT '',
    version      text,
    commit_sha   text,
    source       text,
    source_ref   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, source, source_ref)
);
CREATE INDEX change_when ON change (project_id, occurred_on DESC);

CREATE TABLE session (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    tag        text,
    host       text,
    repo       text,
    branch     text,
    goal       text,
    state      text NOT NULL DEFAULT 'working',
    started_at timestamptz NOT NULL DEFAULT now(),
    last_seen  timestamptz NOT NULL DEFAULT now()
);

-- Memory layers. scope: 'project' or 'component:<key>' or 'item:<key>'.
CREATE TABLE episode (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    scope       text NOT NULL DEFAULT 'project',
    kind        text NOT NULL DEFAULT 'note',
    content     text NOT NULL,
    session_id  uuid REFERENCES session(id) ON DELETE SET NULL,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    source      text,
    source_ref  text,
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(content,''))) STORED,
    UNIQUE (project_id, source, source_ref)
);
CREATE INDEX episode_tsv ON episode USING gin (tsv);

CREATE TABLE fact (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    scope         text NOT NULL DEFAULT 'project',
    subject       text,
    text          text NOT NULL,
    trust         text NOT NULL DEFAULT 'agent',
    valid_from    timestamptz NOT NULL DEFAULT now(),
    valid_to      timestamptz,
    superseded_by uuid REFERENCES fact(id),
    source        text,
    source_ref    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    tsv           tsvector GENERATED ALWAYS AS
                  (to_tsvector('english'::regconfig, coalesce(subject,'') || ' ' || coalesce(text,''))) STORED,
    UNIQUE (project_id, source, source_ref)
);
CREATE INDEX fact_tsv ON fact USING gin (tsv);

CREATE TABLE rule (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    scope       text NOT NULL DEFAULT 'project',
    category    text NOT NULL DEFAULT 'constraint',
    text        text NOT NULL,
    status      text NOT NULL DEFAULT 'proposed',
    proposed_by text,
    accepted_by text,
    source      text,
    source_ref  text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(text,''))) STORED,
    UNIQUE (project_id, source, source_ref)
);
CREATE INDEX rule_tsv ON rule USING gin (tsv);

CREATE TABLE note (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    scope      text NOT NULL DEFAULT 'project',
    text       text NOT NULL,
    expires_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE audit (
    id         bigserial PRIMARY KEY,
    at         timestamptz NOT NULL DEFAULT now(),
    actor      text NOT NULL,
    action     text NOT NULL,
    entity     text NOT NULL,
    entity_id  text,
    project_id uuid,
    detail     jsonb NOT NULL DEFAULT '{}'
);

-- Append-only by trigger (no UPDATE, no DELETE).
CREATE FUNCTION audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit is append-only'; END $$;
CREATE TRIGGER audit_no_change BEFORE UPDATE OR DELETE ON audit
    FOR EACH ROW EXECUTE FUNCTION audit_append_only();

CREATE TABLE import_run (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    source     text NOT NULL,
    kind       text NOT NULL,
    created    int NOT NULL,
    skipped    int NOT NULL,
    dry_run    boolean NOT NULL,
    at         timestamptz NOT NULL DEFAULT now()
);
