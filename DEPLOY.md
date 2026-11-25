# Deploying Viber

Viber is two containers (the API with the dashboard, and Postgres with pgvector). Everything it knows lives in
one Docker volume, `viber_pgdata`.

## 1. Prerequisites

Docker (Desktop on Windows) and git. `gh` (GitHub CLI, signed in) if you want to scan repos from GitHub.

## 2. Start it

```powershell
git clone https://github.com/zeemoussa-dev/Viber.git
cd Viber
copy .env.example .env      # then edit .env: set POSTGRES_PASSWORD and VIBER_TOKEN
docker compose up -d --build
```

Set `POSTGRES_PASSWORD` **before the first start**: Postgres reads it only when it creates the volume. Generate a
token with `[guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")`. By default the ports listen on
this machine only (`VIBER_BIND=127.0.0.1`); set `VIBER_BIND=0.0.0.0` to reach it from other machines, and only
with a token set.

The first build takes a few minutes (Python packages, then the dashboard's npm build). Check it:

```powershell
docker compose ps                                  # both "healthy"
curl http://localhost:8088/health                  # {"status":"ok",...}
```

Open **http://localhost:8088/dashboard/** (enter the token once if you set one). Database migrations run
automatically at start, and a newer database than the code is refused rather than rewritten.

## 3. Create a project and load your repos

On the dashboard's Projects page, create a project (for example `sbos`), or:

```powershell
curl -X POST http://localhost:8088/v1/projects -H "Authorization: Bearer <token>" -H "Content-Type: application/json" `
  -d '{\"key\":\"sbos\",\"name\":\"Second Brain OS\"}'
```

Read components, versions and links from GitHub (read-only, uses your `gh` sign-in; no token reaches a container):

```powershell
$env:VIBER_TOKEN = "<token>"
$repos = (gh repo list <owner> --limit 200 --json name | ConvertFrom-Json) | ForEach-Object { $_.name }
.\tools\scan-github.ps1 -Project sbos -Owner <owner> -Repos $repos -MaxTags 2
```

## 4. Wire Claude sessions to it

Per repository, on each machine, run the installer. It writes that repo's `.claude/settings.local.json` (which
Claude Code keeps out of git) with the Viber env and hooks for this machine's paths, merges with what is there,
keeps a `.bak` of the original, and is safe to run again:

```powershell
.\hooks\install.ps1 -Repo E:\MyWorx\sbos-v3\sb-core -Project sbos
```

The token is read from the `VIBER_TOKEN` environment variable (set it once for your user:
`[Environment]::SetEnvironmentVariable("VIBER_TOKEN","<token>","User")`, then restart Claude Code); pass `-Token` only to
override it. Or skip all of this by pasting `project-scaffold` into Claude Code in the repo, which does these steps, writes
the repo's `CLAUDE.md` and slash commands, and imports its old tracking files.

Then add the MCP server so Claude can call `viber_recall`, `viber_quick`, `viber_bug`, `viber_remember`,
`viber_decide`, `viber_handoff`, `viber_sessions` and `viber_context`. Put this in the repo's `.mcp.json` (Claude asks you to
approve it the first time), adding the header if you set a token:

```json
{ "mcpServers": { "viber": { "type": "http", "url": "http://localhost:8088/mcp",
                             "headers": { "Authorization": "Bearer <token>" } } } }
```

Start a new Claude Code session in that repo. It registers as S1, S2, ... on the dashboard's Sessions page and
receives its context pack. Set `VIBER_DEBUG=1` to see why a hook failed; hooks otherwise never block a session.
Forks: set `VIBER_PARENT_SESSION` to the parent's session id to record the lineage.

## 5. Day-to-day

| Task | Command |
|---|---|
| Update to the latest | `git pull; docker compose up -d --build` |
| Logs | `docker compose logs -f api` |
| Stop / start | `docker compose stop` / `docker compose start` |
| Run the tests | `docker compose --profile tests run --rm --build tests` |

## 6. Backup and restore

```powershell
# Backup (a plain SQL file; keep it somewhere that is not this machine's only disk)
docker compose exec -T db pg_dump -U viber viber > viber-backup.sql

# Restore into an empty database (a fresh volume)
docker compose exec -T db psql -U viber -d viber < viber-backup.sql
```

`docker compose down -v` deletes the volume and everything in it. Plain `docker compose down` keeps it.

## 7. Changing the database password later

Postgres ignores `POSTGRES_PASSWORD` once the volume exists. To change it: update `.env`, then
`docker compose exec db psql -U viber -c "ALTER USER viber PASSWORD '<new>'"` and `docker compose up -d`.

## Not built yet

Importing second_brain's changelog, bugs and ADR files (a migration prompt for its session comes next), claims and
file locks between concurrent sessions, and mobile layout for the dashboard.
