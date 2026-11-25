"""The behaviours the project-scaffold and PROMPTS.md import steps rely on. If one of these changes, those documents are wrong."""


def importing(client, project_key, kind, source, records, dry_run=False):
    suffix = "?dry_run=true" if dry_run else ""
    response = client.post(f"/v1/projects/{project_key}/import/{kind}{suffix}", json={"source": source, "records": records})
    assert response.status_code == 200, response.text
    return response.json()


def bug(key, title="t", ref=None):
    return {"kind": "bug", "key": key, "title": title, "source_ref": ref or key}


def test_a_key_that_another_repo_already_holds_shows_up_as_skipped_on_a_dry_run(client, project_key):
    importing(client, project_key, "items", "second_brain/BUGS.md", [bug("BUG-001", "from second_brain")])
    dry = importing(client, project_key, "items", "sb-orchestration/BUGS.md", [bug("BUG-001", "from orchestration")], dry_run=True)
    assert (dry["created"], dry["skipped"]) == (0, 1)
    items = client.get(f"/v1/projects/{project_key}/items").json()
    assert [i["title"] for i in items] == ["from second_brain"]


def test_a_repo_prefixed_key_avoids_the_collision_and_keeps_the_original_id_as_the_reference(client, project_key):
    importing(client, project_key, "items", "second_brain/BUGS.md", [bug("BUG-001", "first")])
    result = importing(client, project_key, "items", "sb-orchestration/BUGS.md", [bug("ORCH-BUG-001", "second", ref="BUG-001")])
    assert (result["created"], result["skipped"]) == (1, 0)
    assert {i["key"] for i in client.get(f"/v1/projects/{project_key}/items").json()} == {"BUG-001", "ORCH-BUG-001"}
    fresh = client.post(f"/v1/projects/{project_key}/items", json={"kind": "bug", "title": "new"}).json()
    assert fresh["key"] == "BUG-002"


def test_the_same_reference_from_two_repos_does_not_collide_when_the_source_is_prefixed(client, project_key):
    entry = [{"occurred_on": "2026-11-20", "summary": "Added the thing", "source_ref": "CHANGELOG.md:2026-11-20:1"}]
    assert importing(client, project_key, "changes", "sb-core/CHANGELOG.md", entry)["created"] == 1
    assert importing(client, project_key, "changes", "sb-memory/CHANGELOG.md", entry)["created"] == 1
    assert importing(client, project_key, "changes", "sb-core/CHANGELOG.md", entry)["skipped"] == 1


def test_a_changelog_entry_naming_an_unknown_component_is_reported_not_imported(client, project_key):
    client.post(f"/v1/projects/{project_key}/components", json={"key": "sb-orchestration"})
    entries = [
        {"occurred_on": "2026-11-20", "summary": "known", "component_key": "sb-orchestration", "source_ref": "a"},
        {"occurred_on": "2026-11-20", "summary": "unknown", "component_key": "sb-nowhere", "source_ref": "b"},
    ]
    result = importing(client, project_key, "changes", "sb-orchestration/CHANGELOG.md", entries)
    assert (result["created"], len(result["invalid"])) == (1, 1)


def test_component_scoped_rules_reach_only_that_components_sessions_and_project_rules_reach_all(client, project_key):
    base = f"/v1/projects/{project_key}"
    for key in ("a", "b"):
        client.post(f"{base}/components", json={"key": key, "repo": f"o/{key}"})
    importing(client, project_key, "rules", "a/MEMORY.md", [
        {"category": "constraint", "text": "Only for component a.", "scope": "component:a", "status": "accepted", "source_ref": "1"}])
    importing(client, project_key, "rules", "hub/MEMORY.md", [
        {"category": "pattern", "text": "Applies everywhere.", "scope": "project", "status": "accepted", "source_ref": "1"}])
    pack = lambda repo: client.post(f"{base}/sessions/start", json={"session_id": f"s-{repo}", "repo": f"o/{repo}"}).json()["context"]
    in_a, in_b = pack("a"), pack("b")
    assert "Only for component a." in in_a and "Applies everywhere." in in_a
    assert "Only for component a." not in in_b and "Applies everywhere." in in_b


def test_an_auditor_can_read_back_every_field_and_the_source_of_what_was_imported(client, project_key):
    base = f"/v1/projects/{project_key}"
    client.post(f"{base}/components", json={"key": "sb-core"})
    importing(client, project_key, "decisions", "sb-core/ADR.md", [
        {"key": "ADR-141", "title": "Admin key", "status": "Superseded", "decided_on": "2026-05-01", "context": "why",
         "decision": "what", "alternatives": "else", "consequences": "so", "superseded_by": "ADR-v2.060", "source_ref": "ADR-141"}])
    importing(client, project_key, "changes", "sb-core/CHANGELOG.md", [
        {"occurred_on": "2026-11-20", "kind": "fix", "summary": "Fixed it", "body": "detail", "component_key": "sb-core",
         "source_ref": "CHANGELOG.md:2026-11-20:1"}])
    listed = client.get(f"{base}/decisions").json()[0]
    assert (listed["key"], listed["source"]) == ("ADR-141", "sb-core/ADR.md")
    detail = client.get(f"{base}/decisions/ADR-141").json()
    assert (detail["context"], detail["decision"], detail["alternatives"], detail["consequences"], detail["superseded_by"]) == \
        ("why", "what", "else", "so", "ADR-v2.060")
    assert client.get(f"{base}/decisions/ADR-999").status_code == 404
    change = client.get(f"{base}/changes").json()[0]
    assert (change["source"], change["source_ref"], change["body"], change["component"]) == \
        ("sb-core/CHANGELOG.md", "CHANGELOG.md:2026-11-20:1", "detail", "sb-core")


def test_identical_rule_text_in_different_scopes_is_kept_for_each(client, project_key):
    rules = lambda scope: [{"text": "Never store secrets in memory.", "scope": scope, "status": "accepted", "source_ref": scope}]
    assert importing(client, project_key, "rules", "a/MEMORY.md", rules("component:a"))["created"] == 1
    assert importing(client, project_key, "rules", "b/MEMORY.md", rules("component:b"))["created"] == 1
