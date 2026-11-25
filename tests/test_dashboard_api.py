def seed(client, project_key):
    base = f"/v1/projects/{project_key}"
    client.post(f"{base}/components", json={"key": "web", "repo": "o/web"})
    session = client.post(f"{base}/sessions/start", json={"session_id": "dash-1", "repo": "o/web", "goal": "ship"}).json()
    client.post(f"{base}/sessions/dash-1/touch", json={"path": "a.ts"})
    client.post(f"{base}/sessions/dash-1/handoff", json={"summary": "left a note"})
    client.post(f"{base}/sessions/start", json={"session_id": "dash-2", "parent_session_id": "dash-1"})
    client.post(f"{base}/memory/rules", json={"text": "never edit generated code", "proposed_by": "agent"})
    client.post(f"{base}/decisions", json={"key": "ADR-9", "title": "Use X", "status": "Proposed", "decision": "x"})
    client.post(f"{base}/items", json={"kind": "bug", "title": "broken", "gate": "flagged", "gate_reason": "ambiguous"})
    client.post(f"{base}/changes", json={"summary": "did a thing", "occurred_on": "2026-11-25", "component_key": "web"})
    client.post(f"{base}/memory/facts", json={"text": "web talks to api"})
    return session


def test_overview_summarises_the_project(client, project_key):
    seed(client, project_key)
    data = client.get(f"/v1/projects/{project_key}/overview").json()
    assert data["counts"]["active_sessions"] == 2 and data["counts"]["open_bugs"] == 1
    assert data["counts"]["awaiting_review"] == 3 and data["counts"]["components"] == 1 and data["counts"]["facts"] == 1
    assert data["recent_changes"][0]["summary"] == "did a thing"
    assert data["recent_handoffs"][0]["content"] == "left a note" and data["recent_handoffs"][0]["tag"] == "S1"
    assert {s["tag"] for s in data["active_sessions"]} == {"S1", "S2"}
    assert data["session_stats"]["sessions"]["forks"] == 1


def test_review_queue_lists_everything_waiting_for_a_human(client, project_key):
    seed(client, project_key)
    review = client.get(f"/v1/projects/{project_key}/review").json()
    assert review["counts"] == {"rules": 1, "decisions": 1, "items": 1}
    assert review["rules"][0]["text"] == "never edit generated code"
    assert review["decisions"][0]["key"] == "ADR-9" and review["items"][0]["gate_reason"] == "ambiguous"


def test_accepting_and_rejecting_clear_the_queue_and_are_audited(client, project_key):
    seed(client, project_key)
    base = f"/v1/projects/{project_key}"
    rule_id = client.get(f"{base}/review").json()["rules"][0]["id"]
    assert client.post(f"{base}/memory/rules/{rule_id}/accept").status_code == 200
    assert client.post(f"{base}/decisions/ADR-9/accept").json()["status"] == "Accepted"
    assert client.post(f"{base}/decisions/ADR-9/reject").status_code == 404
    assert client.get(f"{base}/review").json()["counts"]["rules"] == 0
    assert client.get(f"{base}/review").json()["counts"]["decisions"] == 0
    other = client.post(f"{base}/memory/rules", json={"text": "retire me"}).json()["id"]
    assert client.post(f"{base}/memory/rules/{other}/retire").json()["status"] == "retired"
    assert client.post(f"{base}/memory/rules/{other}/retire").status_code == 200
    assert client.post(f"{base}/memory/rules/00000000-0000-0000-0000-000000000000/retire").status_code == 404


def test_session_history_and_detail(client, project_key):
    seed(client, project_key)
    base = f"/v1/projects/{project_key}"
    history = {s["tag"]: s for s in client.get(f"{base}/sessions/history").json()}
    assert history["S2"]["parent_tag"] == "S1" and history["S1"]["files_touched"] == 1 and history["S1"]["handoffs"] == 1
    assert history["S1"]["component"] == "web" and history["S1"]["active"] is True
    detail = client.get(f"{base}/sessions/S1/detail").json()
    assert detail["forks"] == ["S2"] and detail["files"][0]["path"] == "a.ts" and detail["handoffs"][0]["content"] == "left a note"
    assert client.get(f"{base}/sessions/S99/detail").status_code == 404


def test_component_summary_reports_versions_and_link_counts(client, project_key):
    base = f"/v1/projects/{project_key}"
    for key in ("lib", "app"):
        client.post(f"{base}/components", json={"key": key})
    scan = lambda comp, text, **kw: client.post(f"{base}/components/{comp}/scan", json={"files": {"pyproject.toml": text}, **kw})
    scan("lib", '[project]\nname="lib-pkg"\nversion="1.2.0"\n', is_tag=True, ref="v1.2.0")
    scan("lib", '[project]\nname="lib-pkg"\nversion="1.3.0"\n')
    scan("app", '[project]\nname="app-pkg"\nversion="0.1.0"\ndependencies=["lib-pkg>=1"]\n')
    rows = {r["key"]: r for r in client.get(f"{base}/components/summary").json()}
    assert (rows["lib"]["head_version"], rows["lib"]["latest_release"], rows["lib"]["dependents"]) == ("1.3.0", "1.2.0", 1)
    assert (rows["app"]["depends_on"], rows["app"]["latest_release"]) == (1, None)


def test_fact_and_change_lists(client, project_key):
    seed(client, project_key)
    base = f"/v1/projects/{project_key}"
    assert client.get(f"{base}/memory/facts").json()[0]["text"] == "web talks to api"
    change = client.get(f"{base}/changes").json()[0]
    assert (change["summary"], change["component"]) == ("did a thing", "web")
