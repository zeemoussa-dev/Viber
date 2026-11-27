-- A saved view is a way of looking at one list (grouping, filters, search) under a name, so it can be opened again
-- with one press. It holds no memory of its own: only the choices.
CREATE TABLE saved_view (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    list       text NOT NULL CHECK (char_length(list) BETWEEN 1 AND 40),
    name       text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
    choice     jsonb NOT NULL,
    created_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX saved_view_name ON saved_view (project_id, list, lower(name));
