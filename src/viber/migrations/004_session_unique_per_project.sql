-- A Claude session id identifies a session within one project; the lookup in start_session is per project,
-- so the constraint must be too (a global one turned the same id in a second project into a 500).
ALTER TABLE session DROP CONSTRAINT session_external_id_key;
ALTER TABLE session ADD CONSTRAINT session_project_external_id_key UNIQUE (project_id, external_id);
