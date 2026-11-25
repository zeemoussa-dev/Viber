"""REST for decision numbers, specs and the memory graph. The MCP tools wrap the same functions."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from . import adr, graph, refs, service, specs
from .atoms import EPISODE_MAX, FACT_MAX, RELATION_MAX, RULE_MAX, SPEC_MAX, split_atoms
from .db import transaction
from .models import EpisodeIn, FactIn, RuleIn
from .security import actor_name, require_token

router = APIRouter(prefix="/v1/projects/{project_key}", dependencies=[Depends(require_token)])


class SpecIn(BaseModel):
    statement: str = Field(max_length=SPEC_MAX)
    kind: str = "requirement"
    component_key: str | None = None
    parent_key: str | None = None
    key: str | None = None
    status: str = "Draft"
    source: str | None = None
    source_ref: str | None = None


class SpecTextIn(BaseModel):
    text: str  # any length: it is split into one row per statement
    kind: str = "requirement"
    component_key: str | None = None
    parent_key: str | None = None
    source: str | None = None


class SpecUpdate(BaseModel):
    statement: str | None = Field(None, max_length=SPEC_MAX)
    status: str | None = None


class LinkIn(BaseModel):
    subject: str
    relation: str = Field(max_length=RELATION_MAX)
    object: str
    subject_kind: str | None = None
    object_kind: str | None = None


class AliasIn(BaseModel):
    name: str
    aliases: list[str]
    kind: str | None = None


class MemorySplitIn(BaseModel):
    kind: str = "fact"  # fact | rule | episode. A rule note: its first statement is the rule, the rest become facts about it.
    text: str
    subject: str | None = None
    category: str = "preference"
    source: str | None = None
    source_ref: str | None = None


@router.post("/memory/split", status_code=201)
def split_memory(project_key: str, payload: MemorySplitIn, actor: str = Depends(actor_name)):
    """Store a long note as short rows. Idempotent by source + source_ref (each row gets '#n' appended)."""
    atoms = split_atoms(payload.text, FACT_MAX if payload.kind != "episode" else EPISODE_MAX)
    made = {"rules": 0, "facts": 0, "episodes": 0}
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        for n, atom in enumerate(atoms, start=1):
            ref = f"{payload.source_ref}#{n}" if payload.source_ref else None
            if payload.kind == "rule" and n == 1:
                text = atom if len(atom) <= RULE_MAX else atom[:RULE_MAX - 1].rstrip() + "…"
                _, created = service.create_rule(connection, project, RuleIn(
                    text=text, category=payload.category, proposed_by=actor, source=payload.source, source_ref=ref), actor)
                made["rules"] += int(created)
            elif payload.kind == "episode":
                _, created = service.create_episode(connection, project, EpisodeIn(
                    content=atom, source=payload.source, source_ref=ref), actor)
                made["episodes"] += int(created)
            else:
                _, created = service.create_fact(connection, project, FactIn(
                    text=atom, subject=payload.subject, source=payload.source, source_ref=ref), actor)
                made["facts"] += int(created)
    return {"statements": len(atoms), **made}


class PlanIn(BaseModel):
    title: str = Field(max_length=200)
    goal: str = Field("", max_length=300)
    key: str | None = None
    status: str = "Draft"
    source: str | None = None
    source_ref: str | None = None


class PlanMembersIn(BaseModel):
    members: list[dict]  # [{"type": "spec", "key": "REQ-001"}, ...]


class RefIn(BaseModel):
    from_type: str
    from_key: str
    relation: str
    to_type: str
    to_key: str
    version_range: str | None = Field(None, max_length=60)
    seq: int | None = None
    note: str | None = Field(None, max_length=200)
    source: str | None = None
    source_ref: str | None = None


class RetireIn(BaseModel):
    type: str
    key: str
    reason: str | None = Field(None, max_length=200)


@router.post("/plans", status_code=201)
def create_plan(project_key: str, payload: PlanIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.create_plan(connection, project, payload.key, payload.title, payload.goal, payload.status,
                                payload.source, payload.source_ref, actor)


@router.get("/plans")
def list_plans(project_key: str, status: str | None = None):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.list_plans(connection, project, status)


@router.get("/plans/{key}")
def get_plan(project_key: str, key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.plan_view(connection, project, key)


@router.post("/plans/{key}/members", status_code=201)
def add_plan_members(project_key: str, key: str, payload: PlanMembersIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.add_to_plan(connection, project, key, [(m["type"], m["key"]) for m in payload.members], actor)


class PlanUpdate(BaseModel):
    title: str | None = Field(None, max_length=200)
    goal: str | None = Field(None, max_length=300)


@router.patch("/plans/{key}")
def update_plan(project_key: str, key: str, payload: PlanUpdate, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.update_plan(connection, project, key, payload.title, payload.goal, actor)


@router.post("/plans/{key}/status")
def set_plan_status(project_key: str, key: str, status: str, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.set_plan_status(connection, project, key, status, actor)


@router.post("/refs", status_code=201)
def add_ref(project_key: str, payload: RefIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.add(connection, project, payload.from_type, payload.from_key, payload.relation, payload.to_type, payload.to_key,
                        payload.version_range, payload.seq, payload.note, payload.source, payload.source_ref, actor)


@router.post("/refs/end")
def end_ref(project_key: str, payload: RefIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.end(connection, project, payload.from_type, payload.from_key, payload.relation, payload.to_type, payload.to_key, actor)


@router.get("/refs")
def show_refs(project_key: str, type: str, key: str, ended: bool = False):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.show(connection, project, type, key, ended)


@router.post("/retire")
def retire(project_key: str, payload: RetireIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.retire(connection, project, payload.type, payload.key, payload.reason, actor)


@router.get("/stale")
def stale(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return refs.stale(connection, project)


@router.get("/adr/next")
def next_adr(project_key: str, prefix: str | None = None, actor: str = Depends(actor_name)):
    """Reserve and return the next decision key, for example ADR-v3.018."""
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return {"key": adr.next_key(connection, project, prefix, actor)}


@router.get("/adr/{reference}")
def get_adr(project_key: str, reference: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return adr.read(connection, project, reference)


@router.post("/specs", status_code=201)
def create_spec(project_key: str, payload: SpecIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return specs.create(connection, project, actor=actor, **payload.model_dump())


@router.post("/specs/split", status_code=201)
def create_specs_from_text(project_key: str, payload: SpecTextIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return specs.create_from_text(connection, project, payload.text, kind=payload.kind, component_key=payload.component_key,
                                      parent_key=payload.parent_key, source=payload.source, actor=actor)


@router.get("/specs")
def list_specs(project_key: str, component: str | None = None, kind: str | None = None, status: str | None = None,
               q: str | None = None, limit: int = 100):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return specs.list_specs(connection, project, component, kind, status, q, limit)


@router.get("/specs/{key}")
def get_spec(project_key: str, key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return specs.read(connection, project, key)


@router.patch("/specs/{key}")
def update_spec(project_key: str, key: str, payload: SpecUpdate, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return specs.update(connection, project, key, payload.statement, payload.status, actor)


@router.post("/graph/link", status_code=201)
def link(project_key: str, payload: LinkIn):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return graph.link(connection, project, payload.subject, payload.relation, payload.object,
                          payload.subject_kind, payload.object_kind)


@router.post("/graph/unlink")
def unlink(project_key: str, payload: LinkIn):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return graph.unlink(connection, project, payload.subject, payload.relation, payload.object)


@router.post("/graph/aliases")
def add_aliases(project_key: str, payload: AliasIn):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        entity = graph.entity_for(connection, project, payload.name, payload.kind)
        graph.add_aliases(connection, project, entity, payload.aliases)
        return {"entity": entity["name"], "aliases": payload.aliases}


@router.get("/graph/entity")
def entity_around(project_key: str, name: str, limit: int = 40):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return graph.around(connection, project, name, limit)


@router.get("/graph/entities")
def list_entities(project_key: str, q: str | None = None, limit: int = 100):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT e.name, e.kind, (SELECT count(*) FROM edge g WHERE g.valid_to IS NULL AND (g.subject_id = e.id OR g.object_id = e.id)) AS edges "
            "FROM entity e WHERE e.project_id = %s AND e.merged_into IS NULL AND (%s::text IS NULL OR e.name ILIKE '%%' || %s || '%%') "
            "ORDER BY edges DESC, e.name LIMIT %s", (project["id"], q, q, min(limit, 500))).fetchall()
