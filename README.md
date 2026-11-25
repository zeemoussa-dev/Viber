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

## Dashboard (v0.5)

Served by the API container at **http://localhost:8088/dashboard/** (the root redirects there). A React 19 +
Vite + TypeScript single-page app in `dashboard/`, built in a Docker stage and copied into the API image, so
there is still one container to deploy. Screens: Overview (stat tiles, active sessions, latest handoffs, recent
changes), Sessions (history, forks, files, handoffs), Review queue (accept or dismiss proposed rules and
decisions, flagged items), Work (bugs and tasks with filters and detail), Map (components, links, problems),
Memory (recall search, rules, facts), Projects.

- The look is second_brain's: its CSS (`dashboard/src/styles`), fonts and self-contained components
  (`dashboard/src/ui`) are vendored, see `dashboard/NOTICE.md`. Viber has its own shell and pages on top.
- If `VIBER_TOKEN` is set the dashboard asks for it once and keeps it in the browser.
- `index.html` is served `no-cache` and hashed assets `immutable`, so a redeploy shows up on the next load.
- Develop it with hot reload: `cd dashboard; npm install; npm run dev` (proxies `/v1` to the API on :8088).
- Dashboard read models: `GET .../overview`, `.../review`, `.../sessions/history`, `.../sessions/{tag}/detail`,
  `.../components/summary`, `.../memory/facts`, `.../changes`; review actions: `POST .../decisions/{key}/accept|reject`,
  `.../memory/rules/{id}/accept|retire`.

## Sessions (v0.4): what makes Claude sessions faster

The loop: a hook registers each session and injects a small **context pack**; Claude uses `viber_*` tools
during the work; edit hooks warn when two active sessions touch the same file; `viber_handoff` carries what a
session learned to the next one or a fork. Nothing is a file bus: everything goes through the API.

- **Context pack** (`POST .../sessions/start`): accepted rules, handoffs from earlier or sibling sessions
  (scoped to the component), other active sessions and the files they are editing, open bugs, recent
  decisions and changes. Capped by `budget_tokens` (default 1500); the size is logged per session, see
  `GET .../stats/sessions` (packs, average/max tokens, forks, overlap warnings, handoffs).
- **Rows, not files (v0.6):** Viber's own data is never a file, so there is nothing to lock: sessions write rows and
  Postgres settles concurrent writes. Nothing long is stored. A fact is at most 500 characters, a rule 400, an
  episode 1000, a spec row 400, a decision statement 500; longer text is refused or split into rows
  (`src/viber/atoms.py`, `POST .../memory/split`). (File claims were built and removed: they only help when
  the shared thing is a file.)
  - **Decisions:** a header plus `decision_point` rows. MCP `viber_next_adr` reserves the next number
    (`ADR-v3.018`, using the project's own prefix, so two sessions never share one), `viber_get_adr` reads one by
    key or by number (`17`), and `viber_decide` fills a reserved number. REST: `GET .../adr/next`, `GET .../adr/{key|number}`.
  - **Specs:** one requirement, constraint, interface or acceptance criterion per row (`REQ-001`, `CON-001`, ...)
    with a status Draft, Agreed, Built, Verified or Dropped. MCP `viber_spec_add`, `viber_spec_get`,
    `viber_spec_status`; REST `.../specs`, `.../specs/split`.
  - **Memory:** facts, rules, episodes and a graph as in Second Brain: entities with aliases, dated relations
    (`sb-fleet` / `depends on` / `sb-contracts`; ended, never deleted) and facts linked to entities. MCP
    `viber_remember` (with `about`), `viber_link`, `viber_graph`; REST `.../graph/*`. `viber_recall` searches facts,
    accepted rules, decision statements, specs, items and episodes.
- **Meaning search (v0.7), built into Viber:** Viber ships its own embedding service (an `embeddings` container running
  Ollama with `bge-m3`; the first start pulls the model, about 1.2 GB, into the `viber_embed_models` volume) and keeps
  vectors in Postgres with pgvector. Nothing depends on any other product. `VIBER_EMBED_PROVIDER` is `ollama`
  (default), `openai` (any OpenAI-compatible endpoint, with `VIBER_EMBED_URL`, `VIBER_EMBED_MODEL`, `VIBER_EMBED_KEY`)
  or `none` (keyword recall only, and `/v1/memory-health` says so). Recall fuses keyword and meaning results by rank
  (reciprocal rank fusion) and falls back to keywords if the service is down. A write never waits for an embedding:
  a background sync (every 20 s, or `POST /v1/embeddings/sync`) fills in what is missing or changed. Every vector
  records its model and a query only uses the configured model's. Text that looks like a secret is never sent to the
  model; it stays keyword-searchable. `GET /v1/memory-health` shows provider, model, vectors, pending and the last
  error. **Recall checks** (`POST .../recall/checks`, `GET .../recall/checks/run`) are questions with the answer they
  must return; run them after any change so ranking cannot quietly get worse.
- **Forks:** a fork starts with the parent's whole conversation but not what siblings learned afterwards.
  Handoffs close that gap. Set `VIBER_PARENT_SESSION` (the parent's session id) to record lineage.
- **MCP** (`POST /mcp`, JSON-RPC over HTTP): `viber_recall`, `viber_context`, `viber_quick`, `viber_bug`,
  `viber_remember` (fact, or a rule a human must accept), `viber_decide` (ADR as Proposed), `viber_handoff`,
  `viber_sessions`. Connect with:

  ```powershell
  claude mcp add --transport http viber http://localhost:8088/mcp
  ```

- **Hooks** (`hooks/viber-hook.ps1`, never blocks a session; exits 0 silently if Viber is down). Needs
  `VIBER_PROJECT` (and `VIBER_URL`, `VIBER_TOKEN` if set). Add to `~/.claude/settings.json` (or a project's
  `.claude/settings.json`):

  ```json
  { "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "powershell -NoProfile -ExecutionPolicy Bypass -File D:/MyWorx/Projects/Viber/hooks/viber-hook.ps1 -Event SessionStart" }] }],
    "PostToolUse":  [{ "matcher": "Edit|Write|MultiEdit", "hooks": [{ "type": "command", "command": "powershell -NoProfile -ExecutionPolicy Bypass -File D:/MyWorx/Projects/Viber/hooks/viber-hook.ps1 -Event PostToolUse" }] }],
    "Stop":         [{ "hooks": [{ "type": "command", "command": "powershell -NoProfile -ExecutionPolicy Bypass -File D:/MyWorx/Projects/Viber/hooks/viber-hook.ps1 -Event Stop" }] }],
    "SessionEnd":   [{ "hooks": [{ "type": "command", "command": "powershell -NoProfile -ExecutionPolicy Bypass -File D:/MyWorx/Projects/Viber/hooks/viber-hook.ps1 -Event SessionEnd" }] }]
  } }
  ```

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
