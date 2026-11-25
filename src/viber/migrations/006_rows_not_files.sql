-- Viber holds rows, not files: no file claims, no long text.
DROP TABLE IF EXISTS file_claim;

-- A decision is a short header plus one row per statement (context, decision, alternative, consequence).
-- The old long columns stay empty for new decisions and are rebuilt from these rows when read.
CREATE TABLE decision_point (
    id          bigserial PRIMARY KEY,
    decision_id uuid NOT NULL REFERENCES decision(id) ON DELETE CASCADE,
    kind        text NOT NULL CHECK (kind IN ('context','decision','alternative','consequence')),
    seq         int  NOT NULL,
    text        text NOT NULL CHECK (char_length(text) <= 500),
    tsv         tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(text,''))) STORED,
    UNIQUE (decision_id, kind, seq)
);
CREATE INDEX decision_point_tsv ON decision_point USING gin (tsv);

-- Specifications: one requirement, constraint, interface or acceptance criterion per row.
CREATE TABLE spec (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    key           text NOT NULL,
    kind          text NOT NULL DEFAULT 'requirement',
    component_key text,
    parent_key    text,
    statement     text NOT NULL CHECK (char_length(statement) <= 400),
    status        text NOT NULL DEFAULT 'Draft',
    source        text,
    source_ref    text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    tsv           tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(statement,''))) STORED,
    UNIQUE (project_id, key),
    UNIQUE (project_id, source, source_ref)
);
CREATE INDEX spec_tsv ON spec USING gin (tsv);
CREATE INDEX spec_component ON spec (project_id, component_key);

-- Memory graph (as in Second Brain): entities, their aliases, dated relations between them, and facts about them.
CREATE TABLE entity (
    id          bigserial PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    kind        text NOT NULL DEFAULT 'thing',
    name        text NOT NULL CHECK (char_length(name) <= 200),
    merged_into bigint REFERENCES entity(id),
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX entity_name ON entity (project_id, lower(name)) WHERE merged_into IS NULL;

CREATE TABLE entity_alias (
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    entity_id  bigint NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    alias      text NOT NULL CHECK (char_length(alias) <= 200),
    PRIMARY KEY (project_id, entity_id, alias)
);
CREATE UNIQUE INDEX entity_alias_name ON entity_alias (project_id, lower(alias));

CREATE TABLE edge (
    id         bigserial PRIMARY KEY,
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    subject_id bigint NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    relation   text NOT NULL CHECK (char_length(relation) <= 60),
    object_id  bigint NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to   timestamptz,
    source     text,
    source_ref text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX edge_live ON edge (project_id, subject_id, lower(relation), object_id) WHERE valid_to IS NULL;
CREATE INDEX edge_object ON edge (project_id, object_id) WHERE valid_to IS NULL;

CREATE TABLE fact_entity (
    fact_id   uuid   NOT NULL REFERENCES fact(id) ON DELETE CASCADE,
    entity_id bigint NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    PRIMARY KEY (fact_id, entity_id)
);
CREATE INDEX fact_entity_entity ON fact_entity (entity_id);
