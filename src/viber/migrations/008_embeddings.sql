-- Everything searchable by meaning, in one view: what is live, accepted and not obsolete. Vectors are derived data:
-- they can always be rebuilt from these rows.
CREATE VIEW memory_embeddable AS
SELECT project_id, 'fact'::text AS kind, id::text AS ref, id::text AS rid, text AS content FROM fact WHERE valid_to IS NULL
UNION ALL SELECT project_id, 'rule', id::text, id::text, text FROM rule WHERE status = 'accepted'
UNION ALL SELECT project_id, 'episode', id::text, id::text, content FROM episode
UNION ALL SELECT d.project_id, 'decision', p.id::text, d.key, d.title || ': ' || p.text
  FROM decision_point p JOIN decision d ON d.id = p.decision_id
 WHERE d.status NOT IN ('Rejected', 'Superseded', 'Obsolete', 'Reserved')
UNION ALL SELECT project_id, 'spec', key, key, statement FROM spec WHERE status <> 'Dropped'
UNION ALL SELECT project_id, 'item', key, key, title FROM item WHERE status NOT IN ('Closed', 'Done', 'Fixed', 'Won''t Fix');

-- One vector per (thing, model). The model is recorded, so vectors of different models are never mixed in a query,
-- and a new model can be filled in beside the old one. A NULL embedding means withheld (it looked like a secret).
CREATE TABLE memory_vector (
    id           bigserial PRIMARY KEY,
    project_id   uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    kind         text NOT NULL,
    ref          text NOT NULL,
    model        text NOT NULL,
    dims         int,
    content_hash text NOT NULL,
    embedding    vector,
    withheld     boolean NOT NULL DEFAULT false,
    created_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, kind, ref, model)
);
CREATE INDEX memory_vector_model ON memory_vector (project_id, model);

-- How the embedding service is doing, per model, for the health view.
CREATE TABLE embedding_state (
    model         text PRIMARY KEY,
    provider      text NOT NULL,
    last_ok_at    timestamptz,
    last_error    text,
    last_error_at timestamptz,
    failures      int NOT NULL DEFAULT 0
);

-- Recall checks: a question and the answer it must return. Run after any change so ranking cannot quietly get worse.
CREATE TABLE recall_check (
    id          bigserial PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    query       text NOT NULL CHECK (char_length(query) <= 300),
    expect_kind text NOT NULL,
    expect_id   text NOT NULL,
    note        text CHECK (char_length(note) <= 200),
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, query, expect_kind, expect_id)
);
