import pytest


@pytest.fixture()
def secured(client, monkeypatch):
    monkeypatch.setenv("VIBER_TOKEN", "master-secret")
    return {"Authorization": "Bearer master-secret"}


def make(client, master, name, role):
    response = client.post("/v1/tokens", json={"name": name, "role": role}, headers=master)
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def mcp(client, headers, project_key, tool, **arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {"project": project_key, **arguments}}}
    return client.post("/mcp", json=body, headers=headers)


def test_no_token_and_a_wrong_token_are_refused(client, project_key, secured):
    assert client.get(f"/v1/projects/{project_key}/sessions").status_code == 401
    assert client.get(f"/v1/projects/{project_key}/sessions", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_a_read_token_reads_and_cannot_write(client, project_key, secured):
    reader = make(client, secured, "viewer", "read")
    assert client.get(f"/v1/projects/{project_key}/views/status", headers=reader).status_code == 200
    assert mcp(client, reader, project_key, "viber_recall", query="anything").status_code == 200
    refused = client.post(f"/v1/projects/{project_key}/memory/facts", json={"text": "x"}, headers=reader)
    assert refused.status_code == 403 and "'read'" in refused.text
    assert mcp(client, reader, project_key, "viber_remember", text="x").status_code == 403


def test_a_write_token_records_work_but_cannot_accept_rules(client, project_key, secured):
    writer = make(client, secured, "session-s7", "write")
    assert client.post(f"/v1/projects/{project_key}/memory/facts", json={"text": "A fact."}, headers=writer).status_code in (200, 201)
    assert mcp(client, writer, project_key, "viber_remember", text="Another fact.").status_code == 200
    rule = client.post(f"/v1/projects/{project_key}/memory/rules", json={"text": "Be careful."}, headers=writer).json()
    assert client.post(f"/v1/projects/{project_key}/memory/rules/{rule['id']}/accept", headers=writer).status_code == 403
    assert mcp(client, writer, project_key, "viber_retire", thing="spec:REQ-001").status_code == 403
    assert client.post("/v1/tokens", json={"name": "x", "role": "read"}, headers=writer).status_code == 403


def test_a_review_token_accepts_rules_and_the_master_does_everything(client, project_key, secured):
    writer, reviewer = make(client, secured, "w", "write"), make(client, secured, "judge", "review")
    rule = client.post(f"/v1/projects/{project_key}/memory/rules", json={"text": "Be careful."}, headers=writer).json()
    assert client.post(f"/v1/projects/{project_key}/memory/rules/{rule['id']}/accept", headers=reviewer).status_code in (200, 204)
    assert client.get("/v1/tokens", headers=reviewer).status_code == 403
    listed = client.get("/v1/tokens", headers=secured).json()
    assert {"w", "judge"} <= {t["name"] for t in listed} and "token" not in listed[0] and "token_hash" not in listed[0]


def test_a_named_token_is_the_actor_in_the_audit_log(client, project_key, secured):
    writer = make(client, secured, "session-s9", "write")
    client.post(f"/v1/projects/{project_key}/memory/facts", json={"text": "Audited fact."}, headers={**writer, "X-Viber-Actor": "someone-else"})
    from viber.db import transaction
    with transaction() as connection:
        actors = {r["actor"] for r in connection.execute("SELECT actor FROM audit WHERE entity = 'fact' ORDER BY id DESC LIMIT 3").fetchall()}
    assert "session-s9" in actors and "someone-else" not in actors


def test_a_revoked_token_stops_working_and_names_are_unique(client, project_key, secured):
    token = make(client, secured, "temp", "write")
    assert client.post("/v1/tokens", json={"name": "TEMP", "role": "read"}, headers=secured).status_code == 409
    token_id = next(t["id"] for t in client.get("/v1/tokens", headers=secured).json() if t["name"] == "temp")
    assert client.delete(f"/v1/tokens/{token_id}", headers=secured).status_code == 200
    assert client.get(f"/v1/projects/{project_key}/views/status", headers=token).status_code == 401
    assert client.post("/v1/tokens", json={"name": "temp", "role": "read"}, headers=secured).status_code == 201
