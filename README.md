# Viber

Development methodology service: projects, components, versions, links, work (items, decisions, changes)
and shared project memory (facts, rules, episodes), in one Postgres. See `SPEC.md` for the design.

## Run

```powershell
docker compose up -d --build        # db on :5433, api on http://localhost:8088 (docs at /docs)
docker compose --profile tests run --rm --build tests   # test suite against a throwaway database
```

Configuration comes from a `.env` next to `docker-compose.yml` (see `.env.example`); every default works for local
development with no `.env`. Set `VIBER_TOKEN` to require `Authorization: Bearer <token>`; empty means open (dev
only). Send `X-Viber-Actor: <name>` on writes so the audit log names who did it. For a real deployment, backups
and wiring Claude sessions to it, see `DEPLOY.md`.

## What exists

Built in layers; each section below says which version added it: the core records (this section), links and
versions (v0.2, v0.3), sessions (v0.4) and the dashboard (v0.5).

- Schema: project, component, item (bugs/tasks/...), decision (ADRs, string keys kept as written), change
  (changelog), session, episode, fact, rule, note, audit (append-only), import_run.
- API under `/v1/projects/{key}/...`: components, items, decisions, changes, memory (facts, rules + accept,
  episodes), `recall`, bulk `import/{items|decisions|changes|episodes|facts|rules}` (idempotent by
  `source` + `source_ref` or by key; `?dry_run=true` writes nothing), generated views (`changelog`, `bugs`).
- Recall is keyword search only.
- Not built yet: claims and file locks between concurrent sessions (overlap is only warned about), pgvector
  recall, a background worker for consolidation, and importing second_brain's markdown (changelog, bugs, ADRs).

## Connecting a repository: `project-scaffold`

`project-scaffold` is a prompt you paste into Claude Code in any repo. It checks Viber, registers the project and
component, wires the hooks (`hooks/install.ps1`), writes `.mcp.json`, a short `CLAUDE.md` and seven slash commands
(`/quick`, `/bug`, `/recall`, `/remember`, `/decide`, `/handoff`, `/status`), and can import a repo's old
`BUGS.md`, `CHANGELOG.md`, `MEMORY.md`, ADR and learnings files through the import API. It replaces the original
markdown pipeline scaffold, kept at `docs/legacy/project-scaffold-v1.md`. Stories, tasks and sprints are not
replaced yet (the full lane in `SPEC.md` is unbuilt).

`PROMPTS.md` is the set of ready-to-paste session prompts built on it: mirror import for `second_brain`,
`sb-orchestration` and other repos, switch-over for standalone repos, re-sync, an independent audit, and fork
kickoff and closeout prompts for day-to-day work.

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
- **Graph hops in recall:** when a question names a known entity (or an alias), recall also returns the facts linked to
  it and its live relations, fused with keyword and meaning results (`via` says which found each row).
- **Consolidation and reflection (v0.8):** `POST .../memory/consolidate` reads the episodes since the last run and asks
  a chat model to propose facts and rules (facts carry trust `agent` and source `consolidation`; every rule waits for a
  human). `POST .../memory/reflect?component=` writes a short current summary of one component, replacing the last.
  Needs `VIBER_LLM_PROVIDER` (`ollama` or `openai`), `VIBER_LLM_MODEL`, `VIBER_LLM_URL`, `VIBER_LLM_KEY`; without them it
  answers 409 and says so. Always available without a model: `GET .../memory/duplicates` (near-identical facts, by
  vector) and `POST .../memory/supersede` (end the older fact, keeping it in the history).
- **Generated views:** `GET .../views/{status|adr|rules|specs|plans|backlog|changelog|bugs}` render markdown from the
  tables on demand. They are read-only output and never a source of truth.
- **Roles (v0.8):** `read` < `write` < `review` < `admin`. The master `VIBER_TOKEN` is admin. Make named tokens on the
  dashboard's System page or `POST /v1/tokens {name, role}` (shown once, only a hash is kept, revocable). A named token is
  its own actor in the audit log. Give sessions a Write token: it records work and proposes, but cannot accept rules or
  decisions, retire things, or make projects and tokens. MCP tools are classed the same way.
- **Memory is per project (v0.9):** every query is filtered by project, links cannot cross projects, and numbering restarts in
  each. A token can be limited to some projects (System page, or `project_keys` on `POST /v1/tokens`): it is refused (403)
  for any other project and sees only its own in `GET /v1/projects`. The hook no longer assumes a project: it asks
  `GET /v1/resolve?repo=owner/name&cwd=...`, which answers by a component's `repo`, then by a project's
  `settings.workspaces` (folder prefixes); a session in a place no project owns gets nothing and writes nothing. Set
  `VIBER_PROJECT` only on a single-project machine.
- **Prompt vault:** `GET .../prompts` lists a project's prompts, `GET .../prompts/{key}?component=` returns one as plain text
  with `{project}` and `{component}` filled in, `PUT .../prompts/{key}` saves one (one statement per line),
  `POST .../prompts/seed` adds the default set (start, resume, component, bug, decide, plan, consolidate, finish). The MCP
  tool `viber_prompt` reads them; the dashboard's Prompts page copies one to paste as a session's first message.
- **Backups (v1.0):** a `pg_dump` of Viber's own database (without the rebuildable vectors) every `VIBER_BACKUP_EVERY_HOURS`
  (default 24; a machine that was off catches up at once), into `./backups` on the host, so it outlives the Docker volumes.
  A backup is trusted only after a restore check: it is restored into a scratch database and each table's row count must fall
  between the live counts just before and just after the dump; its checksum is rechecked on every later check, so a damaged
  or missing file is caught. Retention keeps the newest of each of the last 7 days, 5 weeks and 6 months, and never the
  last good one. The dashboard's System page shows the status and does Back up now, Check again and Download (admin only);
  `GET /v1/backups` has the same, and the MCP tool `viber_backup_status` lets any session see whether memory is backed up.
  To restore: `.\tools\restore-backup.ps1 -File backups\<file>.dump` restores into a separate database (safe); add
  `-Database viber -Yes` to replace the live one. The dump holds every project's data and the token hashes: keep copies of
  the `backups` folder somewhere safe, and treat them as secret.
- **For now (timed facts):** something true only for a while ("run unattended tonight", "don't touch billing until Friday")
  is not a rule. `viber_remember` with `lasts` (`90m`, `12h`, `2d`, `1w`) or `until` (ISO time with offset) stores a
  temporary fact, 5 minutes to 90 days. Every new session's context pack lists them first, under **For now**, where the
  token budget cannot cut them; recall marks them `[temporary, until ...]`. When the time passes the fact is ended and
  every search stops returning it; it stays in the history. Because such a fact often grants permission to act, only the
  review and admin roles (the dashboard's For now card) record one as **set by the operator**; one recorded by a session
  says so, and a session cannot change or end the operator's. `viber_for_now` lists them, `viber_end_for_now` ends one.
- **Forks:** a fork starts with the parent's whole conversation but not what siblings learned afterwards.
  Handoffs close that gap. Set `VIBER_PARENT_SESSION` (the parent's session id) to record lineage.
- **MCP** (`POST /mcp`, JSON-RPC over HTTP): `viber_recall`, `viber_context`, `viber_quick`, `viber_bug`,
  `viber_remember` (fact, or a rule a human must accept), `viber_decide` (ADR as Proposed), `viber_handoff`,
  `viber_sessions`. Connect with:

  ```powershell
  claude mcp add --transport http viber http://localhost:8088/mcp
  ```

- **Hooks** (`hooks/viber-hook.ps1`, never blocks a session; exits 0 silently if Viber is down). It reads
  `VIBER_PROJECT` (required), `VIBER_URL` and `VIBER_TOKEN`. Install them per repository and machine with the
  installer, which writes that repo's `.claude/settings.local.json` using this machine's paths, merges with what
  is there, keeps a `.bak`, and is safe to re-run:

  ```powershell
  .\hooks\install.ps1 -Repo C:\path\to\repo -Project <project-key> [-ViberUrl http://localhost:8088] [-Token <token>]
  ```

  Set `VIBER_DEBUG=1` to see why a hook failed. Full setup steps are in `DEPLOY.md`.

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
