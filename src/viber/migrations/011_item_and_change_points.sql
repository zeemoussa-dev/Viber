-- Work records and changes keep a short body; everything longer lives here, one statement per row (like decision_point).
CREATE TABLE item_point (
    id      bigserial PRIMARY KEY,
    item_id uuid NOT NULL REFERENCES item(id) ON DELETE CASCADE,
    kind    text NOT NULL DEFAULT 'detail',
    seq     int  NOT NULL,
    text    text NOT NULL CHECK (char_length(text) <= 500),
    tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(text,''))) STORED,
    UNIQUE (item_id, kind, seq)
);
CREATE INDEX item_point_tsv ON item_point USING gin (tsv);

CREATE TABLE change_point (
    id        bigserial PRIMARY KEY,
    change_id uuid NOT NULL REFERENCES change(id) ON DELETE CASCADE,
    seq       int  NOT NULL,
    text      text NOT NULL CHECK (char_length(text) <= 500),
    tsv       tsvector GENERATED ALWAYS AS (to_tsvector('english'::regconfig, coalesce(text,''))) STORED,
    UNIQUE (change_id, seq)
);
CREATE INDEX change_point_tsv ON change_point USING gin (tsv);

-- The statements are searchable by meaning too.
CREATE OR REPLACE VIEW memory_embeddable AS
SELECT project_id, 'fact'::text AS kind, id::text AS ref, id::text AS rid, text AS content FROM fact WHERE valid_to IS NULL
UNION ALL SELECT project_id, 'rule', id::text, id::text, text FROM rule WHERE status = 'accepted'
UNION ALL SELECT project_id, 'episode', id::text, id::text, content FROM episode
UNION ALL SELECT d.project_id, 'decision', p.id::text, d.key, d.title || ': ' || p.text
  FROM decision_point p JOIN decision d ON d.id = p.decision_id
 WHERE d.status NOT IN ('Rejected', 'Superseded', 'Obsolete', 'Reserved')
UNION ALL SELECT project_id, 'spec', key, key, statement FROM spec WHERE status <> 'Dropped'
UNION ALL SELECT project_id, 'item', key, key, title FROM item WHERE status NOT IN ('Closed', 'Done', 'Fixed', 'Won''t Fix')
UNION ALL SELECT i.project_id, 'item', 'p' || p.id::text, i.key, i.title || ': ' || p.text
  FROM item_point p JOIN item i ON i.id = p.item_id WHERE i.status NOT IN ('Closed', 'Done', 'Fixed', 'Won''t Fix')
UNION ALL SELECT c.project_id, 'change', 'p' || p.id::text, c.id::text, c.summary || ': ' || p.text
  FROM change_point p JOIN change c ON c.id = p.change_id;
