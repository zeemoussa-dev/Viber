-- A token can be limited to some projects. NULL means every project (the master token always is).
ALTER TABLE api_token ADD COLUMN project_keys text[];

-- Prompts a person gives to a session so it starts knowing what to do. A prompt is a few short lines per project, never a
-- document; {project} and {component} are filled in when it is read.
CREATE TABLE prompt (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    key        text NOT NULL CHECK (char_length(key) <= 40),
    title      text NOT NULL CHECK (char_length(title) <= 120),
    purpose    text NOT NULL DEFAULT '' CHECK (char_length(purpose) <= 200),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, key)
);
CREATE TABLE prompt_line (
    id        bigserial PRIMARY KEY,
    prompt_id uuid NOT NULL REFERENCES prompt(id) ON DELETE CASCADE,
    seq       int  NOT NULL,
    text      text NOT NULL CHECK (char_length(text) <= 500),
    UNIQUE (prompt_id, seq)
);
