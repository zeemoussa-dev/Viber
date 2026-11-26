-- A fact can be true only for a while ("run unattended tonight"). When expires_at passes, the fact is ended
-- (valid_to = expires_at), so every reader of live facts drops it without knowing about expiry. Nothing is deleted.
-- set_by_operator is true only when a person with the review or admin role set it: a session cannot claim it.
ALTER TABLE fact ADD COLUMN expires_at timestamptz;
ALTER TABLE fact ADD COLUMN set_by_operator boolean NOT NULL DEFAULT false;
CREATE INDEX fact_expiring ON fact (expires_at) WHERE expires_at IS NOT NULL AND valid_to IS NULL;
