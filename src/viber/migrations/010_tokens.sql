-- Access tokens with a role. The master VIBER_TOKEN stays the admin; these are for people and sessions that should do less.
-- Only a hash is stored: the token itself is shown once, when it is made.
CREATE TABLE api_token (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name         text NOT NULL CHECK (char_length(name) BETWEEN 1 AND 60),
    role         text NOT NULL CHECK (role IN ('read', 'write', 'review', 'admin')),
    token_hash   text NOT NULL UNIQUE,
    created_by   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    revoked_at   timestamptz
);
CREATE UNIQUE INDEX api_token_name_live ON api_token (lower(name)) WHERE revoked_at IS NULL;
