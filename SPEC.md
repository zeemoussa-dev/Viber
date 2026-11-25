# Viber — Spec (DRAFT v0.1)

Status: draft for review. Nothing is built. Date: 2026-11-25.

## 1. What Viber is

Viber is a **development methodology plus the service that runs it**: one stop shop for
managing large-scale vibe-coding projects with Claude. It holds, in one Postgres database:

- the **map**: projects, components, versions, and the links between them
- the **work**: tickets, bugs, stories, decisions, changes, releases
- the **memory**: sessions, episodes, facts, rules, a knowledge graph — shared by every
  Claude session working on a project

Everything the old scaffold kept in hand-written markdown (`BACKLOG.md`, `BUGS.md`,
`CHANGELOG.md`, `MEMORY.md`, `REVIEW-QUEUE.md`, `ESCALATIONS.md`, stories, tasks, sprints,
ADRs) becomes rows in tables. Markdown files in repos become **generated views**, never the
source of truth and never the coordination channel.

Viber is a standalone tool. It is not a Second Brain OS plugin. Later it may be wrapped by
or replace Dev Center; the design keeps that possible (same memory contract shape as
`sb-memory`), but nothing depends on it.

### Problems it must solve (from the user)

1. File-system-as-bus between agents breaks down → **a service owns state; agents call it**.
2. Memory management is hard → **one shared, scoped, queryable memory per project**.
3. Concurrent sessions don't work → **lanes, leases and file locks, enforced by the service**.
4. Small ad-hoc work breaks the pipeline → **work weight is a choice per item; quick lane
   costs almost nothing; untracked work can be reconciled afterwards**.
5. ~40 repos with changelogs/bugs/links written by hand → **generated from records;
   links and versions are first-class and checked**.

### Principles

- **The service is the only writer of state.** Agents and humans use API/MCP/CLI.
- **Capture is automatic.** Hooks record sessions and episodes; nobody writes a changelog.
- **Weight is opt-in.** The default is the lightest lane that is safe.
- **Append-only history, mutable current state.** Episodes/audit never change; items have
  status; facts are ended or superseded, never deleted.
- **Links are data, verified against reality.** Declared links are compared with what the
  repos' manifests actually say; drift is reported.
- **Humans decide the few things that matter** (rules, ADRs, releases, flagged items);
  agents propose.

## 2. Domain model

```
Workspace
 └─ Project            (a product: "Second Brain OS", "Jarvis", "Padelers")
     ├─ Component      (a repo/package/service/plugin/contract: "sb-memory")
     │   └─ Version    (a release or a ref: 1.3.0, tag, commit, branch head)
     ├─ Link           (typed edge between components, optionally version-constrained)
     ├─ Contract       (a named interface a component provides/consumes: "memory 1.3.0")
     ├─ Release        (a set of component versions that ship together)
     ├─ Item           (ticket: task / bug / story / idea / chore)  ── lane: quick|standard|full
     ├─ Decision       (ADR)
     └─ Memory         (sessions, episodes, facts, rules, graph)
```

### 2.1 Project

A product or area of work. Has a key (`sbos`), a name, phases/roadmap (optional), and
settings (default lane, review rules). Components belong to exactly one *home* project but
may be **linked from** other projects (e.g. a plugin repo used by two products).

### 2.2 Component

The unit you build, version and link. One component ≈ one repo (or one deployable
package inside a monorepo — a repo may hold several).

| Field | Notes |
|---|---|
| `key` | stable slug, e.g. `sb-memory` |
| `kind` | `service`, `library`, `plugin`, `contract`, `app`, `infra`, `tool`, `docs`, `model` |
| `repo` | `owner/name`, default branch, path inside repo (for monorepos) |
| `language`/`stack` | informational |
| `owner project` | home project |
| `lifecycle` | `idea`, `active`, `stable`, `deprecated`, `archived` |
| `provides` | contracts it implements (with version) |
| `consumes` | contracts / components it needs (with constraint) |
| `manifest sources` | where Viber reads truth: `pyproject.toml`, `package.json`, plugin manifest, `openapi.yaml`, etc. |

### 2.3 Version

A concrete, addressable state of a component.

- `semver`, `git_ref` (tag), `commit_sha`, `released_at`, `status`
  (`dev`, `candidate`, `released`, `yanked`), `notes` (generated from episodes/changes).
- Each version records **what it declares**: provided contracts, consumed contracts and
  dependency constraints, read from its manifest at that commit.
- A component always has a moving `head` version (the branch tip) plus released versions.

### 2.4 Link (the anti-mess part)

A typed, directed edge, optionally with a version constraint and a verification state.

| Link type | Meaning | Example |
|---|---|---|
| `depends_on` | build/runtime dependency | `sb-memory → sb-contracts >=1.3` |
| `implements` | component provides a contract | `sb-memory implements memory@1.3.0` |
| `consumes` | uses another's contract or API | `sb-web consumes memory@^1.2` |
| `extends` | plugin/extension of a host | `sb-plugins-dev-center extends sb-plugin-runtime` |
| `deploys_with` | shipped/deployed together | `sb-web deploys_with sb-core` |
| `tests_against` | integration/conformance relation | |
| `replaces` | succession | v2 `second_brain` → v3 cells |

Each link carries:

- `declared_by`: `manual` | `manifest` (auto-discovered) | `inferred`
- `constraint`: semver range (nullable)
- `state`: `verified` (matches manifests), `drifted` (manifest says otherwise),
  `unverified` (manual only), `broken` (constraint not satisfiable by any released version)
- `evidence`: file path + commit where discovered

### 2.5 Contract

A named interface with versions (e.g. `memory`, `identity`, `models`). Components `provide`
or `consume` `contract@version`. This mirrors the v3 "cell contract" idea but is generic:
HTTP APIs, Python protocols, event schemas, file formats. Compatibility rule per contract:
semver (breaking = major) unless the contract says otherwise.

### 2.6 Release

A named, ordered bundle of component versions that is known to work together
(`2026.11-r2`: `sb-core 3.4.0`, `sb-memory 1.3.0`, ...). Viber computes whether a proposed
bundle is **consistent** (every `depends_on`/`consumes` constraint satisfied) and what is
missing. Releases give "what shipped when" and the changelog across 40 repos.

### 2.7 Item (work)

One table for all work. `kind`: `task | bug | story | idea | chore | spike`.

Common fields: `key` (`SBOS-412`, sequential per project, atomic), `title`, `body`,
`status`, `lane`, `priority/severity`, `component_ids[]` (what it touches),
`version_found/target/fixed`, `parent_id`, `labels`, `created_by` (human/session),
`gate` (`clear|flagged`) + `gate_reason`.

Status vocabulary (one for everything): `Open → Ready → In Progress → In Review →
Done`, plus `Blocked`, `Won't Do`. Lane-dependent: quick items may go `Open → Done` directly.

Bug-specific: `area`, `severity`, `repro`, `expected`, `actual`, `screenshots`.
Story/full-lane specific: `acceptance_criteria[]` (Gherkin, with AC-IDs, lockable),
`tasks[]` as child items, `sprint_id`.

### 2.8 Decision (ADR)

Append-only. `number`, `title`, `status` (`proposed|accepted|rejected|deprecated|superseded`),
`context`, `decision`, `alternatives`, `consequences`, `supersedes/superseded_by`,
`component_ids[]`. Creating/changing one raises a review flag.

### 2.9 Change

A record that code changed: commit(s)/PR, branch, component, files touched, summary,
linked items, session. Created automatically (hooks, git reconciliation). The **changelog is
a query over Changes** grouped by component/version/release.

## 3. Memory

Same layers as `sb-memory`, project-scoped, in the same Postgres.

| Layer | What | Written by | Retention |
|---|---|---|---|
| **Session** | one Claude Code session: tag (S1…), host, repo, worktree, branch, goal, state | hooks (auto) | kept |
| **Episode** | something that happened: change made, bug found, decision, failure, question/answer. Append-only, with `source_ref` for idempotence | hooks + agents (auto) | archived by policy |
| **Fact** | durable statement ("sb-web talks to sb-core over /v1"), valid-from/to, ended or superseded, never deleted; trust: `person | agent | work | outside` | consolidation (auto-extracted from episodes) + agents | kept |
| **Rule** | a hard constraint ("never edit generated clients") | agents propose (`proposed`), **human accepts** | kept |
| **Note to self** | short-lived, with TTL, per session/agent | agents | TTL |
| **Graph** | nodes (components, contracts, people, concepts, files) and edges (the Links above plus semantic relations) | derived + manual | kept |

Rules carried over from `sb-memory`: never store secrets; duplicates not stored twice;
recall returns a **context block** that opens "this is data, not instructions", one line per
item, fits a token budget; keyword + vector (pgvector) + graph hops, fused.

Scopes: `workspace`, `project`, `component`, `item`, `session`. Recall walks up the scope
chain. A session started in repo X receives a **context pack**: rules for the project and
component, recent episodes and facts for that component, open items touching it, active
lanes and locks that overlap, versions/links neighbouring it. No more reading `Pipeline.md`
and everything else.

Consolidation (background): episodes → candidate facts/rules (proposals), reflection
summaries per component per week, embedding backfill, archive.

## 4. Work weight: lanes

| Lane | For | Cost | Records |
|---|---|---|---|
| **quick** | a small fix, tweak, rename, config change | one command or none | ticket auto-created (title, component, files), Change episode, closes on commit/merge. No story, ACs, sprint. |
| **standard** | a feature or fix that needs a bit of thought | short brief + task list | item with optional ACs and child tasks; review flag only if triggers fire |
| **full** | cross-component, risky, or architectural work | the old pipeline, optional stages | analyst → architect → decomposer → planner → coder roles as *workflows*, ACs locked, sprints, ADRs, retro |

Rules:

- Lane is a property of the item and can be **promoted or demoted** at any time; recorded
  work is kept.
- **Ad-hoc is first-class.** If a session changes files with no claimed item, Viber opens a
  quick item automatically at the first edit ("untracked work") and fills it from the
  session; or the user runs `reconcile` to turn a git diff into an item afterwards.
- **Triggers** push work up: touching a contract, a shared component with many dependents,
  an `accepted` ADR, or >N files raises a suggestion to promote (never blocks quick work
  unless a rule says so).
- The MUST-FLAG list survives as **flag rules** evaluated by the service, not by prompt
  discipline (material assumption, draft requirement, ADR changed, escalation, oversized,
  unverifiable AC, contradiction, ambiguity).

## 5. Concurrency: lanes of work, claims, locks

A **work lane** (not to be confused with the quick/standard/full weight; call it a
**stream** in code) = one session + one git worktree + one branch.

- `claim(item)` takes a **lease** (TTL, renewed by session heartbeat) and a **scope lock**
  on declared components/paths. Locks are advisory-by-default, enforced for exclusive
  scopes (a contract, a migration, a lockfile).
- Conflict check **before** work starts: overlapping path/component locks → refuse, queue,
  or allow with a warning (configurable per project).
- Heartbeats and hooks keep leases alive; a dead session's lease expires and its work is
  surfaced ("orphaned stream").
- Each stream works in its own worktree/branch; a **merge queue** orders merges and
  re-checks conflicts and link constraints at merge time.
- IDs are allocated by the database (sequences) — no collisions between sessions.
- Everything is transactional: status transitions are validated in code
  (`Open→Ready→…`), not by agents editing frontmatter.

## 6. Keeping links and versions honest

This is the "avoid the mess" part.

1. **Discovery.** A scanner reads each component's manifests at head and at tags:
   `pyproject.toml`/`requirements*.txt`, `package.json`, plugin manifests (`sbos.components`
   entry points, `Manifest`), `openapi.yaml`, `Dockerfile`/compose references, workflow
   files. It proposes Links and Versions (`declared_by=manifest`).
2. **Drift detection.** Compare declared links to manifest reality. Report: link in Viber
   not in manifests, dependency in manifest not tracked, constraint unsatisfiable, a
   consumed contract version that no component provides.
3. **Impact analysis.** `impact(component@version)` → everything that depends on it, the
   constraints involved, what breaks if you bump major, which releases include it.
4. **Release checks.** `check_release(bundle)` → consistent or list of violations.
   `suggest_bump(component)` from the Changes since last version and contract diffs.
5. **Change gating.** A Change that touches a contract file or a provided API marks the
   contract as `changed`, opens a flagged item, and lists dependents to re-test.
6. **Graph view.** Components/contracts/links rendered later by the dashboard; the API
   returns the graph in a standard node/edge form.

Viber never edits a repo's manifests itself in v1; it **reports** and opens items. Optional
later: propose PRs that bump constraints.

## 7. Generated views (no more hand-written files)

Rendered on demand (API/CLI), optionally committed into repos by a `sync-views` step:

- `CHANGELOG.md` per component and per release (from Changes/episodes)
- `BUGS.md` / `BACKLOG.md` mirrors (from Items)
- `STATUS.md` per project: streams, locks, flagged queue, open items
- ADR index, component/links table, release notes
- `CLAUDE.md` memory section: the accepted rules for the project (rendered, so the repo
  carries them even offline)

Markdown in repos is read-only output. The one exception is **prose that belongs to the
repo** (README, wiki articles) — Viber links to it, does not own it.

## 8. Interfaces

One core service, three front doors:

```
Claude sessions ──MCP──┐
CLI / hooks ───────────├──► Viber API (FastAPI, container) ──► Postgres + pgvector (container)
Dashboard (later) ─────┘            │ worker (consolidation, scanner, embeddings, lease reaper)
```

### REST (OpenAPI is the contract)

Resource groups: `/projects`, `/components`, `/versions`, `/links`, `/contracts`,
`/releases`, `/items`, `/decisions`, `/changes`, `/streams`, `/claims`, `/review-queue`,
`/memory/{facts,episodes,rules,notes,graph,recall}`, `/sessions`, `/scan`, `/views`,
`/impact`, `/health`. Cursor pagination, ETags, idempotency keys on writes, an `Idempotency-Key`
or `source_ref` for hook-originated writes.

### MCP tools (thin wrapper over the same operations)

| Tool | Purpose |
|---|---|
| `viber_context(repo/component, task?)` | the context pack at session start |
| `viber_quick(title, component?, files?)` | start/log quick work |
| `viber_claim(item, paths?)` / `viber_release_claim` / `viber_heartbeat` | leases and locks |
| `viber_item_create/update/transition` | items and statuses |
| `viber_bug(...)` | log a bug (replaces `/bug`) |
| `viber_remember(fact\|rule\|note)` / `viber_recall(query)` | memory |
| `viber_decide(adr)` | propose/record an ADR |
| `viber_links(component)` / `viber_impact(component, version?)` | graph questions |
| `viber_flag(item, reason)` / `viber_review_queue()` | human attention |
| `viber_reconcile()` | turn untracked git changes into an item |
| `viber_release_check(bundle)` | consistency check |

Slash commands in Claude Code become thin prompts that call these tools
(`/quick`, `/bug`, `/spec`, `/flow`, `/triage`, `/context`).

### Hooks (Claude Code)

`SessionStart` (register, fetch context pack), `PostToolUse` on edits (record touched
files, open quick item if untracked, heartbeat), `Stop`/`SessionEnd` (episode summary),
`UserPromptSubmit` (optional: inject new flagged answers). Hooks post to the API;
**no files are used as a channel.** If the API is down, hooks queue locally and replay
(idempotent via `source_ref`).

## 9. Data model sketch (Postgres)

Single database, schema `viber`. Tenant/workspace id on every row; row-level security
enabled so a project namespace cannot leak (future multi-user, as in `sb-memory`).

```
workspace(id, name)
project(id, workspace_id, key, name, settings jsonb)
component(id, project_id, key, kind, repo, path, default_branch, lifecycle, meta jsonb)
version(id, component_id, semver, git_ref, commit_sha, status, released_at, declares jsonb)
contract(id, project_id, key, kind, compat_rule)
contract_version(id, contract_id, semver, spec_ref)
component_provides(version_id, contract_version_id)
link(id, from_component_id, to_component_id|to_contract_id, type, constraint,
     declared_by, state, evidence jsonb, created_at)
release(id, project_id, name, status, released_at)
release_member(release_id, version_id)
item(id, project_id, key, kind, lane, status, gate, gate_reason, title, body, severity,
     parent_id, found_in_version, target_version, fixed_in_version, data jsonb, ...)
item_component(item_id, component_id)
acceptance_criterion(id, item_id, ac_key, gherkin, locked)
decision(id, project_id, number, status, ...)  -- append-only
change(id, component_id, commit_sha, branch, pr, summary, files text[], session_id, item_id)
stream(id, session_id, worktree, branch, component_id, state, last_heartbeat)
claim(id, item_id, stream_id, lease_expires_at, scope jsonb)   -- exclusion via constraint
review_item(id, item_id, reason, status, resolved_by, ...)
session(id, tag, host, repo, branch, goal, state, started_at, last_seen)
episode(id, scope, kind, source, source_ref UNIQUE-with-source, content, session_id, ...)
fact(id, scope, subject, text, trust, valid_from, valid_to, superseded_by, embedding vector)
rule(id, scope, text, status, proposed_by, accepted_by)
note(id, scope, text, expires_at)
node(id, kind, ref, name) / edge(id, from, relation, to, valid_from, valid_to)
audit(id, actor, action, entity, entity_id, at)  -- append-only by trigger
```

Sequences per project for item keys (`SBOS-n`), per project for ADR numbers.
Exclusion constraints (`btree_gist`) for overlapping active claims on exclusive scopes.
Status transitions validated by functions/triggers plus application code.

## 10. Tech stack and repo layout (proposed)

- **Python 3.12 + FastAPI + SQLAlchemy/psycopg3**, Alembic migrations, pytest.
- **Postgres 17 + pgvector** (container; arm64 image verified on this machine).
- **Worker** process (same image): consolidation, embeddings, scanner, lease reaper.
- **MCP server** (Python SDK) in the same codebase, calling the core in-process or the API.
- **CLI** (`viber`) for hooks and scripting, talks to the API.
- Embeddings: pluggable (local model container or API); keyword+graph recall works without.
- All development and tests in Docker (`docker compose`), as in your other repos; nothing
  needs installing on Windows.

```
viber/
  docker-compose.yml
  src/viber/{api,core,db,memory,links,scanner,workflows,mcp,cli,views}/
  migrations/
  tests/
  docs/            (this spec becomes ADRs)
  hooks/           (Claude Code hook scripts + install)
  workflows/       (agent prompts for full lane: analyst, architect, ...)
```

## 11. Build order

1. **Skeleton**: compose (api + worker + postgres), migrations, health, auth stub, test
   harness in Docker.
2. **Map**: projects, components, versions, links, contracts + CRUD API; import the
   ~40 `sb-*` repos from GitHub (`gh`) as the first real dataset.
3. **Scanner**: manifests → links/versions, drift report, `impact`, `check_release`.
4. **Items + lanes**: items, statuses, quick lane, bug capture, generated changelog/bugs.
5. **Memory**: sessions, episodes, facts, rules, notes, recall (keyword + graph), context
   pack; then pgvector recall and consolidation.
6. **Concurrency**: streams, claims, leases, locks, orphan reaping, merge-queue checks.
7. **Hooks + MCP + slash commands**: automatic capture, `viber_context`, `/quick`, `/bug`.
8. **Full-lane workflows**: ports of analyst/architect/decomposer/planner/coder as
   workflows over the API; flag rules; review queue.
9. **Dashboard** on the REST API (streams, graph, review queue, release board).
10. **Migration tooling**: import existing `BACKLOG/BUGS/Stories/ADR` markdown from
    second_brain-style repos into tables.

Each step ships usable: after step 3 you already get the link/version map; after step 4
the daily quick/bug flow; after step 7 sessions share memory.

## 12. Open questions

1. **Component granularity**: one component per repo always, or allow several per
   monorepo (the plan assumes yes)?
2. **Versioning source of truth**: are versions tagged in git today, or only in manifests?
   (affects the scanner's first pass)
3. **Contracts**: should every `sb-contracts` contract be imported as a Viber contract
   with compat rules, or start with components/links only?
4. **Hosting of views**: commit generated markdown into repos automatically, or serve only
   from Viber (no repo writes)?
5. **Auth**: single-user for now (token), or multi-user from day one?
6. **Embeddings**: which model, local or API? (can start keyword + graph only)
7. **Where do streams run**: this PC only, or also other machines (needs the API reachable)?
8. **Lane triggers**: which paths/components should force promotion out of quick?
9. **Name collisions**: "lane" means weight (quick/standard/full) in user language and the
   work context (session+worktree) in code — keep weight as *lane* and call the other a
   *stream*?
