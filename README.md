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
