from collections import deque

from fastapi import HTTPException

from .constraints import ConstraintError, highest, parse_version, satisfies
from .db import insert_idempotent, record_audit, to_database_value
from .manifests import parse_manifests


def component_row(connection, project: dict, component_key: str) -> dict:
    row = connection.execute(
        "SELECT * FROM component WHERE project_id = %s AND key = %s", (project["id"], component_key)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"component '{component_key}' not found")
    return row


def contract_row(connection, project: dict, contract_key: str) -> dict:
    row = connection.execute(
        "SELECT * FROM contract WHERE project_id = %s AND key = %s", (project["id"], contract_key)
    ).fetchone()
    if not row:
        raise HTTPException(404, f"contract '{contract_key}' not found")
    return row


def register_aliases(connection, project_id, component_id, aliases: list[tuple[str, str]]) -> list[dict]:
    conflicts = []
    for ecosystem, alias in aliases:
        inserted = connection.execute(
            "INSERT INTO component_alias (project_id, component_id, ecosystem, alias) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING component_id",
            (project_id, component_id, ecosystem, alias),
        ).fetchone()
        if not inserted:
            owner = connection.execute(
                "SELECT component_id FROM component_alias WHERE project_id=%s AND ecosystem=%s AND alias=%s",
                (project_id, ecosystem, alias),
            ).fetchone()
            if owner["component_id"] != component_id:
                conflicts.append({"ecosystem": ecosystem, "alias": alias, "owned_by": str(owner["component_id"])})
    return conflicts


def parse_alias_text(text: str) -> tuple[str, str]:
    ecosystem, _, alias = text.partition(":")
    return (ecosystem, alias.lower()) if alias else ("python", ecosystem.lower())


def ingest_scan(connection, project: dict, component: dict, ref: str | None, commit_sha: str | None,
                is_tag: bool, files: dict[str, str], actor: str) -> dict:
    if is_tag and not ref:
        raise HTTPException(422, "a tag scan needs the tag name in 'ref'")
    manifests, problems = parse_manifests(files)
    primary = next((manifest for manifest in manifests if manifest.version), None)
    if primary is None:
        raise HTTPException(422, {"error": "no manifest with a version found", "problems": problems})
    directory = primary.file.rsplit("/", 1)[0] if "/" in primary.file else ""
    same_directory = [m for m in manifests if (m.file.rsplit("/", 1)[0] if "/" in m.file else "") == directory]
    try:
        parse_version(primary.version)
    except ConstraintError as error:
        raise HTTPException(422, f"{primary.file}: {error}")
    declares = {
        "name": primary.name,
        "manifests": [m.file for m in same_directory],
        "entry_point_groups": sorted({group for m in same_directory for group in m.entry_point_groups}),
        "dependencies": [vars(dep) for m in same_directory for dep in m.dependencies],
        "contracts": [contract for m in same_directory for contract in m.contracts],
    }
    alias_conflicts = register_aliases(
        connection, project["id"], component["id"],
        [(m.ecosystem, m.name) for m in same_directory if m.name],
    )
    if is_tag:
        version_id, created = insert_idempotent(connection, "version", {
            "component_id": component["id"], "semver": primary.version, "is_head": False, "git_ref": ref,
            "commit_sha": commit_sha, "status": "released", "declares": declares,
        })
        if not created:
            version_id = str(connection.execute(
                "SELECT id FROM version WHERE component_id=%s AND semver=%s AND NOT is_head",
                (component["id"], primary.version)).fetchone()["id"])
        connection.execute("UPDATE version SET released_at = COALESCE(released_at, now()) WHERE id = %s", (version_id,))
    else:
        row = connection.execute(
            "INSERT INTO version (component_id, semver, is_head, git_ref, commit_sha, status, declares) "
            "VALUES (%s,%s,true,%s,%s,'dev',%s) ON CONFLICT (component_id, semver, is_head) DO UPDATE SET "
            "git_ref = EXCLUDED.git_ref, commit_sha = EXCLUDED.commit_sha, declares = EXCLUDED.declares, scanned_at = now() "
            "RETURNING id",
            (component["id"], primary.version, ref, commit_sha, to_database_value(declares)),
        ).fetchone()
        version_id, created = str(row["id"]), True
        connection.execute("DELETE FROM version WHERE component_id=%s AND is_head AND id<>%s", (component["id"], version_id))
        connection.execute("UPDATE component SET current_version_id=%s WHERE id=%s", (version_id, component["id"]))
    relinked = relink_project(connection, project)
    record_audit(connection, actor, "scan", "component", str(component["id"]), project["id"],
                 {"semver": primary.version, "tag": is_tag, "ref": ref})
    return {"component": component["key"], "semver": primary.version, "is_tag": is_tag,
            "version_id": version_id, "new_release_row": bool(is_tag and created),
            "dependencies": len(declares["dependencies"]), "links_from_manifests": relinked,
            "alias_conflicts": alias_conflicts, "unreadable": problems}


def relink_project(connection, project: dict) -> int:
    alias_map = {
        (row["ecosystem"], row["alias"]): row["component_id"]
        for row in connection.execute("SELECT * FROM component_alias WHERE project_id = %s", (project["id"],))
    }
    components = connection.execute("SELECT id, current_version_id FROM component WHERE project_id = %s", (project["id"],)).fetchall()
    written = 0
    for component in components:
        version = connection.execute(
            "SELECT * FROM version WHERE component_id = %s ORDER BY (id = %s) DESC, scanned_at DESC LIMIT 1",
            (component["id"], component["current_version_id"]),
        ).fetchone()
        if not version:
            continue
        seen: set[tuple] = set()
        for dependency in version["declares"].get("dependencies", []):
            target = alias_map.get((dependency["ecosystem"], dependency["name"]))
            if not target or target == component["id"]:
                continue
            seen.add((target, dependency["scope"]))
            connection.execute(
                "INSERT INTO link (project_id, from_component_id, to_component_id, type, scope, constraint_text, syntax, "
                "declared_by, state, evidence) VALUES (%s,%s,%s,'depends_on',%s,%s,%s,'manifest','verified',%s) "
                "ON CONFLICT (from_component_id, type, scope, to_component_id) WHERE to_component_id IS NOT NULL "
                "DO UPDATE SET constraint_text = EXCLUDED.constraint_text, syntax = EXCLUDED.syntax, "
                "declared_by = 'manifest', state = 'verified', evidence = EXCLUDED.evidence, updated_at = now()",
                (project["id"], component["id"], target, dependency["scope"], dependency["constraint"],
                 dependency["syntax"], to_database_value({
                     "semver": version["semver"], "commit_sha": version["commit_sha"], "ref": version["git_ref"]})),
            )
            written += 1
        for stale in connection.execute(
            "SELECT id, to_component_id, scope FROM link WHERE from_component_id = %s AND declared_by = 'manifest' "
            "AND to_component_id IS NOT NULL AND state <> 'drifted'", (component["id"],),
        ).fetchall():
            if (stale["to_component_id"], stale["scope"]) not in seen:
                connection.execute("UPDATE link SET state='drifted', updated_at=now() WHERE id=%s", (stale["id"],))
        written += relink_contracts(connection, project, component, version)
    return written


def relink_contracts(connection, project: dict, component: dict, version: dict) -> int:
    seen_contract_ids: set = set()
    for consumed in version["declares"].get("contracts", []):
        connection.execute(
            "INSERT INTO contract (project_id, key, kind) VALUES (%s,%s,'api') ON CONFLICT DO NOTHING",
            (project["id"], consumed["contract"]))
        contract_id = connection.execute(
            "SELECT id FROM contract WHERE project_id=%s AND key=%s", (project["id"], consumed["contract"])).fetchone()["id"]
        seen_contract_ids.add(contract_id)
        connection.execute(
            "INSERT INTO link (project_id, from_component_id, to_contract_id, type, scope, constraint_text, syntax, "
            "declared_by, state, evidence) VALUES (%s,%s,%s,'consumes','runtime',%s,%s,'manifest','verified',%s) "
            "ON CONFLICT (from_component_id, type, scope, to_contract_id) WHERE to_contract_id IS NOT NULL "
            "DO UPDATE SET constraint_text = EXCLUDED.constraint_text, syntax = EXCLUDED.syntax, "
            "declared_by = 'manifest', state = 'verified', evidence = EXCLUDED.evidence, updated_at = now()",
            (project["id"], component["id"], contract_id, consumed["constraint"], consumed["syntax"],
             to_database_value({"semver": version["semver"], "commit_sha": version["commit_sha"], "ref": version["git_ref"]})))
    for stale in connection.execute(
        "SELECT id, to_contract_id FROM link WHERE from_component_id = %s AND declared_by = 'manifest' "
        "AND to_contract_id IS NOT NULL AND state <> 'drifted'", (component["id"],)).fetchall():
        if stale["to_contract_id"] not in seen_contract_ids:
            connection.execute("UPDATE link SET state='drifted', updated_at=now() WHERE id=%s", (stale["id"],))
    return len(seen_contract_ids)


def target_version(connection, component_id) -> tuple[str | None, str | None]:
    """The version a dependent is judged against: the branch head if scanned, else the highest tag."""
    head = connection.execute(
        "SELECT v.semver FROM component c JOIN version v ON v.id = c.current_version_id WHERE c.id = %s",
        (component_id,)).fetchone()
    if head:
        return head["semver"], "head"
    released = [r["semver"] for r in connection.execute(
        "SELECT semver FROM version WHERE component_id=%s AND NOT is_head", (component_id,))]
    best = highest(released)
    return (best, "released") if best else (None, None)


def link_view(connection, project: dict, component_key: str | None = None) -> list[dict]:
    where, parameters = "l.project_id = %s", [project["id"]]
    if component_key:
        component = component_row(connection, project, component_key)
        where += " AND (l.from_component_id = %s OR l.to_component_id = %s)"
        parameters += [component["id"], component["id"]]
    return connection.execute(
        "SELECT l.id, f.key AS from_component, t.key AS to_component, k.key AS to_contract, l.type, l.scope, "
        "l.constraint_text AS constraint, l.syntax, l.declared_by, l.state, l.evidence, l.note "
        "FROM link l JOIN component f ON f.id = l.from_component_id "
        "LEFT JOIN component t ON t.id = l.to_component_id LEFT JOIN contract k ON k.id = l.to_contract_id "
        f"WHERE {where} ORDER BY f.key, t.key, k.key",
        parameters,
    ).fetchall()


def check_links(connection, project: dict) -> dict:
    problems: list[dict] = []
    links = connection.execute(
        "SELECT l.*, f.key AS from_key, t.key AS to_key, k.key AS contract_key FROM link l "
        "JOIN component f ON f.id = l.from_component_id LEFT JOIN component t ON t.id = l.to_component_id "
        "LEFT JOIN contract k ON k.id = l.to_contract_id WHERE l.project_id = %s", (project["id"],)).fetchall()
    for link in links:
        base = {"from": link["from_key"], "to": link["to_key"] or link["contract_key"], "type": link["type"],
                "scope": link["scope"], "constraint": link["constraint_text"]}
        if link["state"] == "drifted":
            problems.append({**base, "issue": "drifted", "detail": "no longer declared in the component's manifest"})
        if link["to_component_id"] and link["constraint_text"] and link["scope"] != "dev":
            semver, source = target_version(connection, link["to_component_id"])
            if semver is None:
                problems.append({**base, "issue": "target_unversioned", "detail": "target has no scanned version"})
            else:
                try:
                    ok = satisfies(semver, link["constraint_text"], link["syntax"])
                except ConstraintError as error:
                    problems.append({**base, "issue": "unreadable_constraint", "detail": str(error)})
                    continue
                if not ok:
                    problems.append({**base, "issue": "unsatisfied", "target_version": semver, "target_source": source})
        if link["to_contract_id"]:
            provided = [r["semver"] for r in connection.execute(
                "SELECT DISTINCT cv.semver FROM contract_version cv JOIN provides p ON p.contract_version_id = cv.id "
                "WHERE cv.contract_id = %s", (link["to_contract_id"],))]
            if not any(satisfies(version, link["constraint_text"], link["syntax"]) for version in provided):
                problems.append({**base, "issue": "no_provider", "detail": f"provided versions: {provided or 'none'}"})
    counts = connection.execute(
        "SELECT state, count(*) AS n FROM link WHERE project_id = %s GROUP BY state", (project["id"],)).fetchall()
    return {"problems": problems, "link_states": {row["state"]: row["n"] for row in counts}}


def impact(connection, project: dict, component_key: str, proposed_version: str | None) -> dict:
    root = component_row(connection, project, component_key)
    dependents, visited = [], {root["id"]}
    queue = deque([(root["id"], 0, None)])
    while queue:
        current_id, depth, via = queue.popleft()
        for link in connection.execute(
            "SELECT l.from_component_id, f.key AS from_key, l.constraint_text, l.syntax, l.scope, l.state FROM link l "
            "JOIN component f ON f.id = l.from_component_id WHERE l.to_component_id = %s AND l.scope <> 'dev'",
            (current_id,)).fetchall():
            satisfied = None
            if depth == 0 and proposed_version:
                satisfied = satisfies(proposed_version, link["constraint_text"], link["syntax"])
            dependents.append({"component": link["from_key"], "depth": depth + 1, "via": via or component_key,
                               "constraint": link["constraint_text"], "scope": link["scope"],
                               "link_state": link["state"], "satisfied_by_proposed": satisfied})
            if link["from_component_id"] not in visited:
                visited.add(link["from_component_id"])
                queue.append((link["from_component_id"], depth + 1, link["from_key"]))
    breaks = [d["component"] for d in dependents if d["satisfied_by_proposed"] is False]
    return {"component": component_key, "proposed_version": proposed_version, "dependents": dependents,
            "would_break": breaks}


def resolve_release_members(connection, project: dict, members: list[dict]) -> tuple[list[dict], list[dict]]:
    resolved, violations = [], []
    for member in members:
        row = connection.execute(
            "SELECT v.id, v.semver, v.declares, c.id AS component_id, c.key FROM version v "
            "JOIN component c ON c.id = v.component_id WHERE c.project_id=%s AND c.key=%s AND v.semver=%s AND NOT v.is_head",
            (project["id"], member["component"], member["version"])).fetchone()
        if not row:
            violations.append({"issue": "unknown_version", "component": member["component"], "version": member["version"],
                               "detail": "no tagged (released) version scanned for this component"})
        else:
            resolved.append(row)
    return resolved, violations


def evaluate_release(connection, project: dict, members: list[dict]) -> dict:
    resolved, violations = resolve_release_members(connection, project, members)
    warnings: list[dict] = []
    alias_map = {(r["ecosystem"], r["alias"]): r["component_id"]
                 for r in connection.execute("SELECT * FROM component_alias WHERE project_id=%s", (project["id"],))}
    in_release = {row["component_id"]: row for row in resolved}
    keys = {row["component_id"]: row["key"] for row in resolved}
    for row in resolved:
        for dependency in row["declares"].get("dependencies", []):
            if dependency["scope"] not in ("runtime", "peer"):
                continue
            target_id = alias_map.get((dependency["ecosystem"], dependency["name"]))
            if not target_id or target_id == row["component_id"]:
                continue
            target = in_release.get(target_id)
            if not target:
                name = connection.execute("SELECT key FROM component WHERE id=%s", (target_id,)).fetchone()["key"]
                warnings.append({"issue": "dependency_not_in_release", "component": row["key"], "needs": name,
                                 "constraint": dependency["constraint"]})
                continue
            try:
                ok = satisfies(target["semver"], dependency["constraint"], dependency["syntax"])
            except ConstraintError as error:
                violations.append({"issue": "unreadable_constraint", "component": row["key"], "detail": str(error)})
                continue
            if not ok:
                violations.append({"issue": "constraint_violated", "component": row["key"], "needs": keys[target_id],
                                   "constraint": dependency["constraint"], "release_has": target["semver"]})
    provided = {}
    for row in resolved:
        for p in connection.execute(
            "SELECT k.id, cv.semver FROM provides p JOIN contract_version cv ON cv.id = p.contract_version_id "
            "JOIN contract k ON k.id = cv.contract_id WHERE p.version_id = %s", (row["id"],)):
            provided.setdefault(p["id"], []).append(p["semver"])
    contract_links = connection.execute(
        "SELECT l.*, f.key AS from_key, k.key AS contract_key FROM link l JOIN component f ON f.id = l.from_component_id "
        "JOIN contract k ON k.id = l.to_contract_id WHERE l.project_id=%s AND l.from_component_id = ANY(%s)",
        (project["id"], list(in_release))).fetchall() if in_release else []
    for link in contract_links:
        if not any(satisfies(v, link["constraint_text"], link["syntax"]) for v in provided.get(link["to_contract_id"], [])):
            violations.append({"issue": "contract_unprovided", "component": link["from_key"],
                               "needs": f"{link['contract_key']} {link['constraint_text']}".strip()})
    return {"consistent": not violations, "violations": violations, "warnings": warnings,
            "members": [{"component": r["key"], "version": r["semver"]} for r in resolved]}
