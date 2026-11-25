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
- Not built yet: links/versions/contracts/releases, scanner, streams/claims/locks, MCP server, hooks,
  dashboard, pgvector recall.
