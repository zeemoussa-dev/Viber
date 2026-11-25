-- Where consolidation got to, per project, so each run reads only the episodes since the last one.
CREATE TABLE consolidation_state (
    project_id      uuid PRIMARY KEY REFERENCES project(id) ON DELETE CASCADE,
    last_episode_at timestamptz,
    last_run_at     timestamptz,
    last_error      text CHECK (char_length(last_error) <= 300)
);
