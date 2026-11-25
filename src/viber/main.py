from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

import os
from pathlib import Path

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, dashboard_api, links, map_api, mcp_api, service, session_api
from .security import actor_name, require_token
from .db import DryRunRollback, close_pool, insert_idempotent, record_audit, run_migrations, transaction
from .models import (ComponentIn, ChangeIn, DecisionIn, EpisodeIn, FactIn, ImportBatch, ItemIn,
                     ItemUpdate, ProjectIn, RuleIn)


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    yield
    close_pool()


app = FastAPI(title="Viber", version=__version__, lifespan=lifespan)


app.include_router(map_api.router)
app.include_router(session_api.router)
app.include_router(mcp_api.router)
app.include_router(dashboard_api.router)

class DashboardFiles(StaticFiles):
    """Hashed assets never change, so they cache forever; everything else (index.html) revalidates, so a
    redeploy shows up on the next load instead of serving a page that points at assets that no longer exist."""

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        immutable = path.startswith("assets/")
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if immutable else "no-cache"
        return response


DASHBOARD_DIRECTORY = Path(os.environ.get("VIBER_DASHBOARD_DIR", "/app/dashboard_dist"))
if DASHBOARD_DIRECTORY.is_dir():
    # The dashboard is a static single-page app that talks to this same API; it carries no secrets.
    app.mount("/dashboard", DashboardFiles(directory=DASHBOARD_DIRECTORY, html=True), name="dashboard")

    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse("/dashboard/")
protected = [Depends(require_token)]


@app.get("/health")
def health():
    with transaction() as connection:
        connection.execute("SELECT 1")
    return {"status": "ok", "version": __version__}


@app.post("/v1/projects", status_code=201, dependencies=protected)
def create_project(payload: ProjectIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project_id, created = insert_idempotent(
            connection, "project", {"key": payload.key, "name": payload.name, "settings": payload.settings}
        )
        if not created:
            raise HTTPException(409, f"project '{payload.key}' already exists")
        record_audit(connection, actor, "create", "project", project_id, project_id)
    return {"id": project_id, "key": payload.key}


@app.get("/v1/projects", dependencies=protected)
def list_projects():
    with transaction() as connection:
        return connection.execute("SELECT id, key, name, created_at FROM project ORDER BY key").fetchall()


@app.post("/v1/projects/{project_key}/components", status_code=201, dependencies=protected)
def create_component(project_key: str, payload: ComponentIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        component_id, created = insert_idempotent(
            connection, "component", {"project_id": project["id"], **payload.model_dump(exclude={"aliases"})}
        )
        if not created:
            raise HTTPException(409, f"component '{payload.key}' already exists")
        conflicts = links.register_aliases(
            connection, project["id"], component_id,
            [links.parse_alias_text(text) for text in payload.aliases])
        if conflicts:
            raise HTTPException(409, {"error": "alias already owned by another component", "conflicts": conflicts})
        record_audit(connection, actor, "create", "component", component_id, project["id"])
    return {"id": component_id, "key": payload.key}


@app.get("/v1/projects/{project_key}/components", dependencies=protected)
def list_components(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT id, key, kind, repo, path, lifecycle FROM component WHERE project_id = %s ORDER BY key",
            (project["id"],),
        ).fetchall()


def respond_created(result_and_flag):
    result, created = result_and_flag
    return {**result, "created": created}


@app.post("/v1/projects/{project_key}/items", status_code=201, dependencies=protected)
def create_item(project_key: str, payload: ItemIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return respond_created(service.create_item(connection, project, payload, actor))


@app.get("/v1/projects/{project_key}/items", dependencies=protected)
def list_items(project_key: str, kind: str | None = None, status: str | None = None,
               limit: int = Query(100, le=1000), offset: int = 0):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT key, kind, lane, status, severity, area, title, found_on, gate, source FROM item "
            "WHERE project_id = %s AND (%s::text IS NULL OR kind = %s) AND (%s::text IS NULL OR status = %s) "
            "ORDER BY created_at, key LIMIT %s OFFSET %s",
            (project["id"], kind, kind, status, status, limit, offset),
        ).fetchall()


@app.get("/v1/projects/{project_key}/items/{item_key}", dependencies=protected)
def get_item(project_key: str, item_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        row = connection.execute(
            "SELECT * FROM item WHERE project_id = %s AND key = %s", (project["id"], item_key)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"item '{item_key}' not found")
        return {k: v for k, v in row.items() if k != "tsv"}


@app.patch("/v1/projects/{project_key}/items/{item_key}", dependencies=protected)
def update_item(project_key: str, item_key: str, payload: ItemUpdate, actor: str = Depends(actor_name)):
    changes = payload.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "nothing to update")
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        assignments = ", ".join(f"{column} = %s" for column in changes)
        row = connection.execute(
            f"UPDATE item SET {assignments}, updated_at = now() WHERE project_id = %s AND key = %s RETURNING id",
            [*changes.values(), project["id"], item_key],
        ).fetchone()
        if not row:
            raise HTTPException(404, f"item '{item_key}' not found")
        record_audit(connection, actor, "update", "item", str(row["id"]), project["id"], changes)
    return {"key": item_key, **changes}


@app.post("/v1/projects/{project_key}/decisions", status_code=201, dependencies=protected)
def create_decision(project_key: str, payload: DecisionIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return respond_created(service.create_decision(connection, project, payload, actor))


@app.get("/v1/projects/{project_key}/decisions", dependencies=protected)
def list_decisions(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT key, title, status, decided_on, supersedes, superseded_by, source FROM decision "
            "WHERE project_id = %s ORDER BY key",
            (project["id"],),
        ).fetchall()


@app.get("/v1/projects/{project_key}/decisions/{decision_key}", dependencies=protected)
def get_decision(project_key: str, decision_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        row = connection.execute(
            "SELECT * FROM decision WHERE project_id = %s AND key = %s", (project["id"], decision_key)).fetchone()
        if not row:
            raise HTTPException(404, f"decision '{decision_key}' not found")
        return {k: v for k, v in row.items() if k not in ("tsv", "id", "project_id")}


@app.post("/v1/projects/{project_key}/changes", status_code=201, dependencies=protected)
def create_change(project_key: str, payload: ChangeIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return respond_created(service.create_change(connection, project, payload, actor))


@app.post("/v1/projects/{project_key}/memory/facts", status_code=201, dependencies=protected)
def remember_fact(project_key: str, payload: FactIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return respond_created(service.create_fact(connection, project, payload, actor))


@app.post("/v1/projects/{project_key}/memory/episodes", status_code=201, dependencies=protected)
def record_episode(project_key: str, payload: EpisodeIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return respond_created(service.create_episode(connection, project, payload, actor))


@app.post("/v1/projects/{project_key}/memory/rules", status_code=201, dependencies=protected)
def propose_rule(project_key: str, payload: RuleIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return respond_created(service.create_rule(connection, project, payload, actor))


@app.post("/v1/projects/{project_key}/memory/rules/{rule_id}/accept", dependencies=protected)
def accept_rule(project_key: str, rule_id: str, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        row = connection.execute(
            "UPDATE rule SET status = 'accepted', accepted_by = %s WHERE project_id = %s AND id = %s RETURNING id",
            (actor, project["id"], rule_id),
        ).fetchone()
        if not row:
            raise HTTPException(404, "rule not found")
        record_audit(connection, actor, "accept", "rule", rule_id, project["id"])
    return {"id": rule_id, "status": "accepted"}


@app.get("/v1/projects/{project_key}/memory/rules", dependencies=protected)
def list_rules(project_key: str, status: str | None = None):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT id, category, scope, text, status, source FROM rule "
            "WHERE project_id = %s AND (%s::text IS NULL OR status = %s) ORDER BY created_at",
            (project["id"], status, status),
        ).fetchall()


@app.get("/v1/projects/{project_key}/recall", dependencies=protected)
def recall(project_key: str, q: str, limit: int = Query(10, le=50)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return service.recall(connection, project, q, limit)


@app.post("/v1/projects/{project_key}/import/{kind}", dependencies=protected)
def bulk_import(project_key: str, kind: str, batch: ImportBatch, dry_run: bool = False,
                actor: str = Depends(actor_name)):
    if kind not in service.IMPORTERS:
        raise HTTPException(404, f"unknown import kind '{kind}'; use one of {sorted(service.IMPORTERS)}")
    model_class, creator = service.IMPORTERS[kind]
    created_count = skipped_count = 0
    problems: list[dict] = []
    try:
        with transaction() as connection:
            project = service.project_row(connection, project_key)
            for index, raw_record in enumerate(batch.records):
                try:
                    payload = model_class(**{"source": batch.source, **raw_record})
                except Exception as validation_error:
                    problems.append({"index": index, "error": str(validation_error)[:300]})
                    continue
                try:
                    with connection.transaction():
                        _, created = creator(connection, project, payload, actor)
                except HTTPException as rejected:
                    problems.append({"index": index, "error": str(rejected.detail)})
                    continue
                created_count += created
                skipped_count += not created
            connection.execute(
                "INSERT INTO import_run (project_id, source, kind, created, skipped, dry_run) VALUES (%s,%s,%s,%s,%s,%s)",
                (project["id"], batch.source, kind, created_count, skipped_count, dry_run),
            )
            if dry_run:
                raise DryRunRollback()
    except DryRunRollback:
        pass
    return {"kind": kind, "source": batch.source, "dry_run": dry_run, "created": created_count,
            "skipped": skipped_count, "invalid": problems}


@app.get("/v1/projects/{project_key}/views/changelog", response_class=PlainTextResponse, dependencies=protected)
def changelog_view(project_key: str, component: str | None = None):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return service.render_changelog(connection, project, component)


@app.get("/v1/projects/{project_key}/views/bugs", response_class=PlainTextResponse, dependencies=protected)
def bugs_view(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        rows = connection.execute(
            "SELECT key, title, area, severity, status FROM item WHERE project_id = %s AND kind = 'bug' ORDER BY key",
            (project["id"],),
        ).fetchall()
    lines = [f"# BUGS - {project['name']}", "", "_Generated by Viber. Do not edit by hand._", "",
             "| ID | Title | Area | Severity | Status |", "|---|---|---|---|---|"]
    lines += [f"| {r['key']} | {r['title']} | {r['area'] or ''} | {r['severity'] or ''} | {r['status']} |" for r in rows]
    return "\n".join(lines) + "\n"
