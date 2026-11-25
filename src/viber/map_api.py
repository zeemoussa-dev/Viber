from fastapi import APIRouter, Depends, HTTPException, Query

from . import links, service
from .constraints import ConstraintError, parse_version
from .db import insert_idempotent, record_audit, transaction
from .models import (ContractIn, ContractVersionIn, LinkIn, ProvideIn, ReleaseIn, ScanIn)
from .security import actor_name, require_token

router = APIRouter(prefix="/v1/projects/{project_key}", dependencies=[Depends(require_token)])


def checked_version(text: str) -> str:
    try:
        parse_version(text)
    except ConstraintError as error:
        raise HTTPException(422, str(error))
    return text


@router.post("/components/{component_key}/scan")
def scan_component(project_key: str, component_key: str, payload: ScanIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        component = links.component_row(connection, project, component_key)
        return links.ingest_scan(connection, project, component, payload.ref, payload.commit_sha,
                                 payload.is_tag, payload.files, actor)


@router.get("/components/{component_key}/versions")
def list_versions(project_key: str, component_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        component = links.component_row(connection, project, component_key)
        return connection.execute(
            "SELECT semver, is_head, git_ref, commit_sha, status, released_at, scanned_at FROM version "
            "WHERE component_id = %s ORDER BY is_head DESC, scanned_at DESC", (component["id"],)).fetchall()


@router.post("/components/{component_key}/versions/{semver}/provides", status_code=201)
def declare_provides(project_key: str, component_key: str, semver: str, payload: ProvideIn,
                     actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        component = links.component_row(connection, project, component_key)
        version = connection.execute(
            "SELECT id FROM version WHERE component_id=%s AND semver=%s ORDER BY is_head", (component["id"], semver)).fetchone()
        if not version:
            raise HTTPException(404, f"component '{component_key}' has no version {semver}")
        contract = links.contract_row(connection, project, payload.contract)
        contract_version = connection.execute(
            "SELECT id FROM contract_version WHERE contract_id=%s AND semver=%s", (contract["id"], payload.semver)).fetchone()
        if not contract_version:
            raise HTTPException(404, f"contract '{payload.contract}' has no version {payload.semver}")
        connection.execute("INSERT INTO provides (version_id, contract_version_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                           (version["id"], contract_version["id"]))
        record_audit(connection, actor, "provide", "version", str(version["id"]), project["id"], payload.model_dump())
    return {"component": component_key, "version": semver, "provides": f"{payload.contract}@{payload.semver}"}


@router.post("/contracts", status_code=201)
def create_contract(project_key: str, payload: ContractIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        contract_id, created = insert_idempotent(connection, "contract", {"project_id": project["id"], **payload.model_dump()})
        if not created:
            raise HTTPException(409, f"contract '{payload.key}' already exists")
        record_audit(connection, actor, "create", "contract", contract_id, project["id"])
    return {"id": contract_id, "key": payload.key}


@router.post("/contracts/{contract_key}/versions", status_code=201)
def create_contract_version(project_key: str, contract_key: str, payload: ContractVersionIn):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        contract = links.contract_row(connection, project, contract_key)
        _, created = insert_idempotent(connection, "contract_version", {
            "contract_id": contract["id"], "semver": checked_version(payload.semver), "spec_ref": payload.spec_ref})
    return {"contract": contract_key, "semver": payload.semver, "created": created}


@router.get("/contracts")
def list_contracts(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return connection.execute(
            "SELECT k.key, k.kind, COALESCE(array_agg(cv.semver ORDER BY cv.semver) FILTER (WHERE cv.id IS NOT NULL), '{}') AS versions "
            "FROM contract k LEFT JOIN contract_version cv ON cv.contract_id = k.id WHERE k.project_id = %s "
            "GROUP BY k.id ORDER BY k.key", (project["id"],)).fetchall()


@router.post("/links", status_code=201)
def create_link(project_key: str, payload: LinkIn, actor: str = Depends(actor_name)):
    if bool(payload.to_component) == bool(payload.to_contract):
        raise HTTPException(422, "give exactly one of to_component or to_contract")
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        source = links.component_row(connection, project, payload.from_component)
        values = {"project_id": project["id"], "from_component_id": source["id"], "type": payload.type,
                  "scope": payload.scope, "constraint_text": payload.constraint, "syntax": payload.syntax,
                  "note": payload.note}
        if payload.to_component:
            values["to_component_id"] = links.component_row(connection, project, payload.to_component)["id"]
        else:
            values["to_contract_id"] = links.contract_row(connection, project, payload.to_contract)["id"]
        link_id, created = insert_idempotent(connection, "link", values)
        if created:
            record_audit(connection, actor, "create", "link", link_id, project["id"], payload.model_dump())
    return {"id": link_id, "created": created}


@router.get("/links")
def list_links(project_key: str, component: str | None = None):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return links.link_view(connection, project, component)


@router.get("/links/check")
def check_links(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return links.check_links(connection, project)


@router.get("/components/{component_key}/impact")
def component_impact(project_key: str, component_key: str, version: str | None = Query(None)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return links.impact(connection, project, component_key, checked_version(version) if version else None)


@router.post("/releases/check")
def check_release(project_key: str, payload: ReleaseIn):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return links.evaluate_release(connection, project, [m.model_dump() for m in payload.members])


@router.post("/releases", status_code=201)
def create_release(project_key: str, payload: ReleaseIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        evaluation = links.evaluate_release(connection, project, [m.model_dump() for m in payload.members])
        release_id, created = insert_idempotent(connection, "release", {
            "project_id": project["id"], "name": payload.name, "notes": payload.notes})
        if not created:
            raise HTTPException(409, f"release '{payload.name}' already exists")
        for member in payload.members:
            connection.execute(
                "INSERT INTO release_member (release_id, version_id) "
                "SELECT %s, v.id FROM version v JOIN component c ON c.id = v.component_id "
                "WHERE c.project_id=%s AND c.key=%s AND v.semver=%s AND NOT v.is_head ON CONFLICT DO NOTHING",
                (release_id, project["id"], member.component, member.version))
        record_audit(connection, actor, "create", "release", release_id, project["id"], {"name": payload.name})
    return {"id": release_id, "name": payload.name, "status": "draft", **evaluation}


def release_members(connection, release_id) -> list[dict]:
    return [{"component": r["key"], "version": r["semver"]} for r in connection.execute(
        "SELECT c.key, v.semver FROM release_member m JOIN version v ON v.id = m.version_id "
        "JOIN component c ON c.id = v.component_id WHERE m.release_id = %s ORDER BY c.key", (release_id,))]


@router.post("/releases/{release_name}/publish")
def publish_release(project_key: str, release_name: str, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        release = connection.execute("SELECT * FROM release WHERE project_id=%s AND name=%s",
                                     (project["id"], release_name)).fetchone()
        if not release:
            raise HTTPException(404, f"release '{release_name}' not found")
        evaluation = links.evaluate_release(connection, project, release_members(connection, release["id"]))
        if not evaluation["consistent"]:
            raise HTTPException(409, {"error": "release is not consistent", **evaluation})
        connection.execute("UPDATE release SET status='released', released_at=now() WHERE id=%s", (release["id"],))
        record_audit(connection, actor, "publish", "release", str(release["id"]), project["id"])
    return {"name": release_name, "status": "released", **evaluation}


@router.get("/releases")
def list_releases(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        rows = connection.execute("SELECT id, name, status, released_at, notes FROM release WHERE project_id=%s ORDER BY created_at DESC",
                                  (project["id"],)).fetchall()
        return [{**{k: v for k, v in r.items() if k != "id"}, "members": release_members(connection, r["id"])} for r in rows]
