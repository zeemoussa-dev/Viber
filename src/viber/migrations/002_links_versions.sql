-- Package/npm names a component is known by, so manifest dependencies resolve to components.
CREATE TABLE component_alias (
    project_id   uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    component_id uuid NOT NULL REFERENCES component(id) ON DELETE CASCADE,
    ecosystem    text NOT NULL,
    alias        text NOT NULL,
    PRIMARY KEY (project_id, ecosystem, alias)
);

-- One SemVer per component. A head row (is_head) is the latest scan of the branch tip and is
-- overwritten by the next head scan; a release row is a tagged version and is immutable.
CREATE TABLE version (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    component_id uuid NOT NULL REFERENCES component(id) ON DELETE CASCADE,
    semver       text NOT NULL,
    is_head      boolean NOT NULL DEFAULT false,
    git_ref      text,
    commit_sha   text,
    status       text NOT NULL DEFAULT 'dev',
    released_at  timestamptz,
    declares     jsonb NOT NULL DEFAULT '{}',
    scanned_at   timestamptz NOT NULL DEFAULT now(),
    UNIQUE (component_id, semver, is_head)
);

ALTER TABLE component ADD COLUMN current_version_id uuid REFERENCES version(id) ON DELETE SET NULL;

CREATE TABLE contract (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    key        text NOT NULL,
    kind       text NOT NULL DEFAULT 'api',
    notes      text NOT NULL DEFAULT '',
    UNIQUE (project_id, key)
);

CREATE TABLE contract_version (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    contract_id uuid NOT NULL REFERENCES contract(id) ON DELETE CASCADE,
    semver      text NOT NULL,
    spec_ref    text,
    UNIQUE (contract_id, semver)
);

CREATE TABLE provides (
    version_id          uuid NOT NULL REFERENCES version(id) ON DELETE CASCADE,
    contract_version_id uuid NOT NULL REFERENCES contract_version(id) ON DELETE CASCADE,
    PRIMARY KEY (version_id, contract_version_id)
);

-- Typed edge. Target is a component or a contract (exactly one).
-- declared_by: manual | manifest.  state: verified | unverified | drifted.
CREATE TABLE link (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    from_component_id uuid NOT NULL REFERENCES component(id) ON DELETE CASCADE,
    to_component_id   uuid REFERENCES component(id) ON DELETE CASCADE,
    to_contract_id    uuid REFERENCES contract(id) ON DELETE CASCADE,
    type              text NOT NULL DEFAULT 'depends_on',
    scope             text NOT NULL DEFAULT 'runtime',
    constraint_text   text NOT NULL DEFAULT '',
    syntax            text NOT NULL DEFAULT 'semver',
    declared_by       text NOT NULL DEFAULT 'manual',
    state             text NOT NULL DEFAULT 'unverified',
    evidence          jsonb NOT NULL DEFAULT '{}',
    note              text NOT NULL DEFAULT '',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CHECK ((to_component_id IS NOT NULL) <> (to_contract_id IS NOT NULL))
);
CREATE UNIQUE INDEX link_component_target
    ON link (from_component_id, type, scope, to_component_id) WHERE to_component_id IS NOT NULL;
CREATE UNIQUE INDEX link_contract_target
    ON link (from_component_id, type, scope, to_contract_id) WHERE to_contract_id IS NOT NULL;
CREATE INDEX link_reverse ON link (to_component_id);

CREATE TABLE release (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid NOT NULL REFERENCES project(id) ON DELETE CASCADE,
    name        text NOT NULL,
    status      text NOT NULL DEFAULT 'draft',
    notes       text NOT NULL DEFAULT '',
    released_at timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, name)
);

CREATE TABLE release_member (
    release_id uuid NOT NULL REFERENCES release(id) ON DELETE CASCADE,
    version_id uuid NOT NULL REFERENCES version(id) ON DELETE CASCADE,
    PRIMARY KEY (release_id, version_id)
);
