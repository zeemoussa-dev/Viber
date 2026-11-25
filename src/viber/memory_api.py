"""Memory health, the embedding sync, and recall checks (a question and the answer it must return)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import consolidation, embeddings, service
from .db import transaction
from .security import actor_name, require_token

router = APIRouter(dependencies=[Depends(require_token)])


class CheckIn(BaseModel):
    query: str = Field(max_length=300)
    expect_kind: str
    expect_id: str
    note: str | None = Field(None, max_length=200)


@router.get("/v1/memory-health")
def memory_health():
    """Which provider and model, how many vectors, what is pending, the last error. Says plainly when recall is keyword only."""
    return embeddings.health()


@router.post("/v1/embeddings/sync")
def run_sync(limit: int = 64):
    """Embed what is missing or changed now (the background sync does this every 20 seconds)."""
    return embeddings.sync(min(max(limit, 1), 500))


class SupersedeIn(BaseModel):
    old: str
    new: str


@router.post("/v1/projects/{project_key}/memory/consolidate")
def consolidate(project_key: str, actor: str = Depends(actor_name)):
    """Read the episodes since the last run and have the chat model propose facts and rules (rules wait for a human)."""
    with transaction() as connection:
        return consolidation.propose(connection, service.project_row(connection, project_key), actor)


@router.post("/v1/projects/{project_key}/memory/reflect")
def reflect(project_key: str, component: str, actor: str = Depends(actor_name)):
    with transaction() as connection:
        return consolidation.reflect(connection, service.project_row(connection, project_key), component, actor)


@router.get("/v1/projects/{project_key}/memory/duplicates")
def duplicates(project_key: str, threshold: float = consolidation.DUPLICATE_THRESHOLD):
    """Live facts that mean nearly the same thing. Needs the embeddings; works without a chat model."""
    with transaction() as connection:
        return consolidation.duplicates(connection, service.project_row(connection, project_key), threshold)


@router.post("/v1/projects/{project_key}/memory/supersede")
def supersede(project_key: str, payload: SupersedeIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        return consolidation.supersede(connection, service.project_row(connection, project_key), payload.old, payload.new, actor)


@router.post("/v1/projects/{project_key}/recall/checks", status_code=201)
def add_check(project_key: str, payload: CheckIn):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        row = connection.execute(
            "INSERT INTO recall_check (project_id, query, expect_kind, expect_id, note) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id",
            (project["id"], payload.query, payload.expect_kind, payload.expect_id, payload.note)).fetchone()
        return {"created": bool(row)}


@router.get("/v1/projects/{project_key}/recall/checks/run")
def run_checks(project_key: str, limit: int = 5):
    """Run every check: the expected answer must be in the top `limit`. Reports each rank, and the mode used."""
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        checks = connection.execute("SELECT query, expect_kind, expect_id FROM recall_check WHERE project_id = %s ORDER BY id", (project["id"],)).fetchall()
        results, mode = [], "keyword"
        for check in checks:
            found = service.recall(connection, project, check["query"], max(limit, 10))
            mode = found["mode"]
            rank = next((i for i, r in enumerate(found["items"], 1) if r["kind"] == check["expect_kind"] and r["id"] == check["expect_id"]), None)
            results.append({**check, "rank": rank, "passed": rank is not None and rank <= limit})
    return {"mode": mode, "passed": sum(r["passed"] for r in results), "total": len(results), "checks": results}
