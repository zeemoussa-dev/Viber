def call(client, project_key, name, **arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {"project": project_key, **arguments}}}
    return client.post("/mcp", json=body).json()["result"]["content"][0]["text"]


def seed(client, project_key):
    base = f"/v1/projects/{project_key}"
    assert client.post(f"{base}/components", json={"key": "sb-fleet"}).status_code == 201
    assert client.post(f"{base}/components", json={"key": "sb-old"}).status_code == 201
    client.post(f"{base}/decisions", json={"key": "ADR-v3.009", "title": "Fleet signs manifests", "decision": "Fleet signs them."})
    client.post(f"{base}/decisions", json={"key": "ADR-v3.010", "title": "Old thing", "decision": "Legacy."})
    call(client, project_key, "viber_spec_add", text="Updates are signed.\nUnsigned updates are refused.")
    bug = client.post(f"{base}/items", json={"kind": "bug", "title": "Refused update leaves install degraded"}).json()
    return bug["key"]


def test_a_plan_is_rows_linked_in_order_with_progress(client, project_key):
    bug = seed(client, project_key)
    assert "created" in call(client, project_key, "viber_plan", key="PLAN-live", title="Live update", goal="Update both live installs safely")
    call(client, project_key, "viber_plan_add", plan="PLAN-live", members=["decision:ADR-v3.009", "spec:REQ-001", "spec:REQ-002", f"item:{bug}"])
    call(client, project_key, "viber_spec_status", key="REQ-001", status="Built")
    shown = call(client, project_key, "viber_plan", key="PLAN-live")
    assert "PLAN-live [Draft] Live update" in shown and "Goal: Update both live installs safely" in shown
    assert "Progress: 2 of 4 settled" in shown
    assert shown.index("REQ-001") < shown.index("REQ-002")
    assert "Fleet signs manifests" in shown and "Refused update leaves install degraded" in shown


def test_a_link_must_point_at_things_that_exist(client, project_key):
    seed(client, project_key)
    response = client.post(f"/v1/projects/{project_key}/refs", json={
        "from_type": "decision", "from_key": "ADR-v3.009", "relation": "applies_to", "to_type": "component", "to_key": "sb-nope"})
    assert response.status_code == 404 and "sb-nope" in response.text
    assert client.post(f"/v1/projects/{project_key}/refs", json={
        "from_type": "decision", "from_key": "ADR-v3.009", "relation": "likes", "to_type": "component", "to_key": "sb-fleet"}).status_code == 422


def test_a_decision_applies_to_a_component_version_range_and_shows_both_ways(client, project_key):
    seed(client, project_key)
    assert "(new)" in call(client, project_key, "viber_ref", **{"from": "decision:ADR-v3.009", "relation": "applies_to", "to": "component:sb-fleet", "version_range": ">=0.5,<1.0"})
    assert "(already linked)" in call(client, project_key, "viber_ref", **{"from": "decision:adr-v3.009", "relation": "applies_to", "to": "component:sb-fleet"})
    assert "applies_to component sb-fleet (>=0.5,<1.0)" in call(client, project_key, "viber_refs", thing="decision:ADR-v3.009")
    assert "decision ADR-v3.009 applies_to this (>=0.5,<1.0)" in call(client, project_key, "viber_refs", thing="component:sb-fleet")


def test_retiring_marks_obsolete_ends_links_and_hides_it_from_recall(client, project_key):
    seed(client, project_key)
    call(client, project_key, "viber_ref", **{"from": "decision:ADR-v3.010", "relation": "applies_to", "to": "component:sb-old"})
    assert "1 link(s) ended" in call(client, project_key, "viber_retire", thing="decision:ADR-v3.010", reason="component removed")
    assert "Obsolete" in call(client, project_key, "viber_get_adr", adr="ADR-v3.010")
    assert "Legacy" not in call(client, project_key, "viber_recall", query="legacy")
    assert "[ended]" in call(client, project_key, "viber_refs", thing="decision:ADR-v3.010", ended=True)


def test_stale_lists_things_tied_to_an_archived_component(client, project_key):
    seed(client, project_key)
    call(client, project_key, "viber_ref", **{"from": "decision:ADR-v3.010", "relation": "applies_to", "to": "component:sb-old"})
    assert "Nothing is tied" in call(client, project_key, "viber_stale")
    from viber.db import transaction
    with transaction() as connection:
        connection.execute("UPDATE component SET lifecycle = 'archived' WHERE key = 'sb-old'")
    assert "decision:ADR-v3.010 applies_to sb-old (archived)" in call(client, project_key, "viber_stale")


def test_a_plan_goal_is_one_line(client, project_key):
    response = client.post(f"/v1/projects/{project_key}/plans", json={"title": "x", "goal": "g" * 400})
    assert response.status_code == 422
