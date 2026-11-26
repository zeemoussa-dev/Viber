-- Dropped (cancelled) work is finished work: it must not be searched or counted as open.
CREATE OR REPLACE VIEW memory_embeddable AS
SELECT project_id, 'fact'::text AS kind, id::text AS ref, id::text AS rid, text AS content FROM fact WHERE valid_to IS NULL
UNION ALL SELECT project_id, 'rule', id::text, id::text, text FROM rule WHERE status = 'accepted'
UNION ALL SELECT project_id, 'episode', id::text, id::text, content FROM episode
UNION ALL SELECT d.project_id, 'decision', p.id::text, d.key, d.title || ': ' || p.text
  FROM decision_point p JOIN decision d ON d.id = p.decision_id
 WHERE d.status NOT IN ('Rejected', 'Superseded', 'Obsolete', 'Reserved')
UNION ALL SELECT project_id, 'spec', key, key, statement FROM spec WHERE status <> 'Dropped'
UNION ALL SELECT project_id, 'item', key, key, title FROM item WHERE status NOT IN ('Closed', 'Done', 'Fixed', 'Won''t Fix', 'Dropped')
UNION ALL SELECT i.project_id, 'item', 'p' || p.id::text, i.key, i.title || ': ' || p.text
  FROM item_point p JOIN item i ON i.id = p.item_id WHERE i.status NOT IN ('Closed', 'Done', 'Fixed', 'Won''t Fix', 'Dropped')
UNION ALL SELECT c.project_id, 'change', 'p' || p.id::text, c.id::text, c.summary || ': ' || p.text
  FROM change_point p JOIN change c ON c.id = p.change_id;
