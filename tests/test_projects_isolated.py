"""Memory is per project: nothing written in one project may be read, found, linked or counted in another."""
import uuid

import pytest

from viber import embeddings, service
from viber.db import transaction


def call(client, project, tool, headers=None, **arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {"project": project, **arguments}}}
    return client.post("/mcp", json=body, headers=headers or {})


def text(client, project, tool, **arguments):
    return call(client, project, tool, **arguments).json()["result"]["content"][0]["text"]


@pytest.fixture()
def two(client):
    keys = [f"iso{uuid.uuid4().hex[:6]}", f"iso{uuid.uuid4().hex[:6]}"]
    for key in keys:
        assert client.post("/v1/projects", json={"key": key, "name": key}).status_code == 201
    return keys


def test_what_one_project_remembers_is_invisible_to_another(client, two, monkeypatch):
    monkeypatch.setenv("VIBER_EMBED_PROVIDER", "fake")
    monkeypatch.setenv("VIBER_EMBED_MODEL", "fake-64")
    monkeypatch.setenv("VIBER_EMBED_MIN_SCORE", "0.1")
    a, b = two
    text(client, a, "viber_remember", text="Zebra migration uses the quartz ledger.", about=["quartz"])
    text(client, a, "viber_link", subject="quartz", relation="depends on", object="zebra")
    text(client, a, "viber_spec_add", text="The quartz ledger is append only.")
    text(client, a, "viber_decide", title="Quartz ledger", decision="Use the quartz ledger.")
    text(client, a, "viber_plan", title="Quartz plan", key="PLAN-q")
    embeddings.sync()
    for query in ("quartz ledger", "zebra migration", "what is quartz tied to"):
        assert "quartz" in text(client, a, "viber_recall", query=query).lower()
        leaked = text(client, b, "viber_recall", query=query)
        assert "quartz" not in leaked.lower() and "zebra" not in leaked.lower(), leaked
    assert client.get(f"/v1/projects/{b}/graph/entity", params={"name": "quartz"}).status_code == 404
    assert client.get(f"/v1/projects/{b}/specs").json() == []
    assert client.get(f"/v1/projects/{b}/plans").json() == []
    assert "quartz" not in client.get(f"/v1/projects/{b}/views/specs").text.lower()
    assert "quartz" not in client.get(f"/v1/projects/{b}/views/status").text.lower()
    assert client.get(f"/v1/projects/{b}/adr/1").status_code == 404
    assert client.get(f"/v1/projects/{b}/memory/duplicates", params={"threshold": 0.1}).json() == []


def test_a_link_cannot_point_across_projects(client, two):
    a, b = two
    text(client, a, "viber_spec_add", text="Only in A.")
    text(client, b, "viber_plan", title="B plan", key="PLAN-b")
    refused = client.post(f"/v1/projects/{b}/plans/PLAN-b/members", json={"members": [{"type": "spec", "key": "REQ-001"}]})
    assert refused.status_code == 404


def test_numbering_is_per_project(client, two):
    a, b = two
    for key in (a, b):
        client.post(f"/v1/projects/{key}/decisions", json={"key": "ADR-001", "title": "first", "decision": "x"})
    assert "ADR-002" in text(client, a, "viber_next_adr") and "ADR-002" in text(client, b, "viber_next_adr")
    assert text(client, a, "viber_spec_add", text="One.").endswith("REQ-001") and text(client, b, "viber_spec_add", text="Two.").endswith("REQ-001")


@pytest.fixture()
def secured(client, monkeypatch):
    monkeypatch.setenv("VIBER_TOKEN", "master-secret")
    return {"Authorization": "Bearer master-secret"}


def test_a_token_limited_to_one_project_cannot_touch_another(client, two, secured):
    a, b = two
    made = client.post("/v1/tokens", json={"name": f"only-{a}", "role": "write", "project_keys": [a]}, headers=secured)
    assert made.status_code == 201 and made.json()["project_keys"] == [a]
    mine = {"Authorization": f"Bearer {made.json()['token']}"}
    assert client.post(f"/v1/projects/{a}/memory/facts", json={"text": "Mine."}, headers=mine).status_code in (200, 201)
    refused = client.post(f"/v1/projects/{b}/memory/facts", json={"text": "Not mine."}, headers=mine)
    assert refused.status_code == 403 and a in refused.text and b in refused.text
    assert client.get(f"/v1/projects/{b}/views/status", headers=mine).status_code == 403
    assert call(client, a, "viber_remember", headers=mine, text="Via MCP.").status_code == 200
    assert call(client, b, "viber_remember", headers=mine, text="Via MCP.").status_code == 403
    assert call(client, b, "viber_recall", headers=mine, query="x").status_code == 403
    assert [p["key"] for p in client.get("/v1/projects", headers=mine).json()] == [a]
    assert {a, b} <= {p["key"] for p in client.get("/v1/projects", headers=secured).json()}


def test_the_resolver_names_the_project_by_repo_then_folder_and_never_guesses(client, two, secured):
    a, b = two
    client.post(f"/v1/projects/{a}/components", json={"key": "svc", "repo": f"acme/{a}-svc"}, headers=secured)
    with transaction() as connection:
        connection.execute("UPDATE project SET settings = settings || jsonb_build_object('workspaces', jsonb_build_array('C:/work/" + b + "')) WHERE key = %s", (b,))
    by_repo = client.get("/v1/resolve", params={"repo": f"acme/{a}-svc"}, headers=secured).json()
    assert by_repo == {"project": a, "how": "repo"}
    by_folder = client.get("/v1/resolve", params={"cwd": f"C:\\work\\{b}\\deep\\er"}, headers=secured).json()
    assert by_folder == {"project": b, "how": "workspace"}
    assert client.get("/v1/resolve", params={"repo": "nobody/nothing", "cwd": "D:/elsewhere"}, headers=secured).json() == {"project": None, "how": None}
    limited = client.post("/v1/tokens", json={"name": f"lim-{b}", "role": "read", "project_keys": [b]}, headers=secured).json()["token"]
    assert client.get("/v1/resolve", params={"repo": f"acme/{a}-svc"}, headers={"Authorization": f"Bearer {limited}"}).json()["project"] is None


def test_prompts_are_per_project_and_fill_in_the_project_and_component(client, two):
    a, b = two
    assert client.post(f"/v1/projects/{a}/prompts/seed").json()["prompts_made"] >= 8
    assert client.post(f"/v1/projects/{a}/prompts/seed").json()["prompts_made"] == 0
    start = client.get(f"/v1/projects/{a}/prompts/start").text
    assert f"project='{a}'" in start and "viber_context" in start and "{project}" not in start
    assert f"component '{'svc'}'" in client.get(f"/v1/projects/{a}/prompts/component", params={"component": "svc"}).text
    assert client.get(f"/v1/projects/{b}/prompts/start").status_code == 404
    assert "start:" in text(client, a, "viber_prompt")
    assert f"project='{a}'" in text(client, a, "viber_prompt", key="finish")
    saved = client.put(f"/v1/projects/{a}/prompts/mine", json={"title": "Mine", "purpose": "p", "text": "Line one.\nLine two for {project}."})
    assert saved.json()["lines"] == 2 and f"Line two for {a}." in client.get(f"/v1/projects/{a}/prompts/mine").text
