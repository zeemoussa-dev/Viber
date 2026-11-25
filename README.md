# Viber

Development methodology service: projects, components, versions, links, work (items, decisions, changes)
and shared project memory (facts, rules, episodes), in one Postgres. See `SPEC.md` for the design.

## Run

```powershell
docker compose up -d --build        # db on :5433, api on http://localhost:8088 (docs at /docs)
docker compose --profile tests run --rm --build tests   # test suite against a throwaway database
```

Set `VIBER_TOKEN` (compose `api` service) to require `Authorization: Bearer <token>`; empty means open (dev only).
Send `X-Viber-Actor: <name>` on writes so the audit log names who did it.

## What exists (v0.1)

- Schema: project, component, item (bugs/tasks/...), decision (ADRs, string keys kept as written), change
  (changelog), session, episode, fact, rule, note, audit (append-only), import_run.
- API under `/v1/projects/{key}/...`: components, items, decisions, changes, memory (facts, rules + accept,
  episodes), `recall`, bulk `import/{items|decisions|changes|episodes|facts|rules}` (idempotent by
  `source` + `source_ref` or by key; `?dry_run=true` writes nothing), generated views (`changelog`, `bugs`).
- Not built yet: streams/claims/locks, MCP server, hooks, dashboard, pgvector recall.

## Links and versions (v0.2)

- One SemVer per component. A **head** row is the latest scan of the default branch (overwritten by the next
  scan); a **release** row comes from a tag scan and is immutable. Train tags like `v3.0.2` are release names,
  not component versions.
- `POST .../components/{key}/scan` takes manifest text (`pyproject.toml`, `package.json`), registers the
  package name as an alias, and re-derives all manifest links in the project. Dependencies that are not
  components stay in `version.declares` and never become links. A link that disappears from the manifest is
  marked `drifted`; a manual link a manifest later confirms becomes `verified`.
- `GET .../links`, `GET .../links/check` (drifted, unsatisfied constraints, unprovided contracts),
  `GET .../components/{key}/impact?version=X` (transitive dependents, and which would break at X).
- Contracts (`/contracts`, versions, `provides`) and manual `consumes` links to contracts.
- Releases are bundles of tagged versions. `POST .../releases/check` validates a bundle against each member's
  own manifest as of its tag; `POST .../releases` stores a draft; `.../publish` refuses an inconsistent one.
- Constraint solving is deterministic (PEP 440 and npm ranges); no model ever decides a version or a link.

### Manifests and component boundaries (v0.3)

- Read: `pyproject.toml`, `package.json`, `plugin.json`, `Chart.yaml`, and a root `VERSION` file.
- `plugin.json` gives the plugin id (alias), its version, `requires` (plugin-to-plugin links) and
  `framework_api`, which becomes a `consumes` link to the `plugin-api` contract with `>=<framework_api>`.
  (Assumption: `framework_api` is a minimum. Confirm per plugin if that is wrong.)
- `POST .../discover {repo, paths}` decides component boundaries: one component per repo when it has a
  root `pyproject.toml`/`package.json`/`plugin.json`/`Chart.yaml`; a repo with no such root manifest (a
  root `VERSION` file alone, or nothing) is split by directory (`repo.leaf`); test, vendor, template, doc and
  build directories are ignored and reported.
- A consumed contract is created on first use. Someone must say which component version **provides** it
  (`POST .../components/{key}/versions/{semver}/provides`); until then its links report `no_provider`.

### Scanning GitHub

Runs on your machine with `gh`; no token goes into a container. It asks Viber to discover components, then
scans each at the default branch and at up to `-MaxTags` tags:

```powershell
.\tools\scan-github.ps1 -Project sbos -Owner zeemoussa-dev -Repos sb-core,sb-platform -MaxTags 3
```
