import pytest

from viber import embeddings, service
from viber.db import transaction


def call(client, project_key, name, **arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {"project": project_key, **arguments}}}
    return client.post("/mcp", json=body).json()["result"]["content"][0]["text"]


def test_recall_follows_the_graph_when_the_question_names_an_entity(client, project_key):
    call(client, project_key, "viber_link", subject="sb-fleet", relation="depends on", object="sb-contracts")
    call(client, project_key, "viber_remember", text="Fleet signs every release manifest.", about=["sb-fleet"])
    with transaction() as connection:
        found = service.recall(connection, service.project_row(connection, project_key), "what is sb-fleet tied to", 5)
    assert found["mode"] == "keyword+graph"
    texts = [i["content"] for i in found["items"]]
    assert "sb-fleet depends on sb-contracts" in texts and "Fleet signs every release manifest." in texts
    assert all(i["via"] == "graph" for i in found["items"])


def test_a_question_naming_nothing_known_uses_no_graph(client, project_key):
    with transaction() as connection:
        found = service.recall(connection, service.project_row(connection, project_key), "completely unrelated question", 5)
    assert found["mode"] == "keyword"


def episode(client, project_key, content):
    assert client.post(f"/v1/projects/{project_key}/memory/episodes", json={"content": content, "kind": "note"}).status_code in (200, 201)


def test_consolidation_needs_a_chat_model_and_says_so(client, project_key, monkeypatch):
    monkeypatch.setenv("VIBER_LLM_PROVIDER", "none")
    response = client.post(f"/v1/projects/{project_key}/memory/consolidate")
    assert response.status_code == 409 and "no chat model" in response.text


def test_consolidation_stores_facts_proposes_rules_and_reads_only_new_episodes(client, project_key, monkeypatch):
    monkeypatch.setenv("VIBER_LLM_PROVIDER", "fake")
    episode(client, project_key, "The updater now checks image digests. Done on Tuesday.")
    episode(client, project_key, "Always take a checked backup before an update.")
    first = client.post(f"/v1/projects/{project_key}/memory/consolidate").json()
    assert first["episodes"] == 2 and first["facts"] == 2 and first["rules"] == 1
    again = client.post(f"/v1/projects/{project_key}/memory/consolidate").json()
    assert again["episodes"] == 0
    rules = client.get(f"/v1/projects/{project_key}/memory/rules").json()
    rules = rules["value"] if isinstance(rules, dict) else rules
    assert any(r["text"].startswith("Always take a checked backup") and r["status"] == "proposed" for r in rules)
    episode(client, project_key, "A third thing happened.")
    assert client.post(f"/v1/projects/{project_key}/memory/consolidate").json()["episodes"] == 1


def test_reflection_replaces_the_previous_summary_of_a_component(client, project_key, monkeypatch):
    monkeypatch.setenv("VIBER_LLM_PROVIDER", "fake")
    base = f"/v1/projects/{project_key}"
    assert client.post(f"{base}/components", json={"key": "sb-fleet"}).status_code == 201
    client.post(f"{base}/items", json={"kind": "bug", "title": "Heartbeat refused", "component_keys": ["sb-fleet"]})
    assert client.post(f"{base}/memory/reflect", params={"component": "sb-fleet"}).json()["statements"] == 1
    client.post(f"{base}/items", json={"kind": "bug", "title": "Manifest unsigned", "component_keys": ["sb-fleet"]})
    assert client.post(f"{base}/memory/reflect", params={"component": "sb-fleet"}).json()["statements"] == 1
    with transaction() as connection:
        live = connection.execute("SELECT count(*) AS n FROM fact WHERE subject = 'reflection:sb-fleet' AND valid_to IS NULL").fetchone()["n"]
        ended = connection.execute("SELECT count(*) AS n FROM fact WHERE subject = 'reflection:sb-fleet' AND valid_to IS NOT NULL").fetchone()["n"]
    assert (live, ended) == (1, 1)


def test_duplicates_are_found_by_meaning_and_the_older_can_be_superseded(client, project_key, monkeypatch):
    monkeypatch.setenv("VIBER_EMBED_PROVIDER", "fake")
    monkeypatch.setenv("VIBER_EMBED_MODEL", "fake-64")
    base = f"/v1/projects/{project_key}"
    client.post(f"{base}/memory/facts", json={"text": "Backups are kept for fourteen days on Business."})
    client.post(f"{base}/memory/facts", json={"text": "Business keeps backups for fourteen days."})
    client.post(f"{base}/memory/facts", json={"text": "Charts need axes and a legend."})
    embeddings.sync()
    pairs = client.get(f"{base}/memory/duplicates", params={"threshold": 0.7}).json()
    pairs = pairs["value"] if isinstance(pairs, dict) else pairs
    assert len(pairs) == 1 and pairs[0]["older_text"].startswith("Backups are kept")  # the older one is the first written
    done = client.post(f"{base}/memory/supersede", json={"old": pairs[0]["older"], "new": pairs[0]["newer"]}).json()
    assert done["superseded_by"] == pairs[0]["newer"]
    assert client.get(f"{base}/memory/duplicates", params={"threshold": 0.7}).json() in ([], {"value": [], "Count": 0})
