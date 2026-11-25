import os

import pytest

from viber import embeddings


@pytest.fixture(autouse=True)
def fake_provider(monkeypatch):
    monkeypatch.setenv("VIBER_EMBED_PROVIDER", "fake")
    monkeypatch.setenv("VIBER_EMBED_MODEL", "fake-64")
    monkeypatch.setenv("VIBER_EMBED_MIN_SCORE", "0.2")
    embeddings._failed_at = 0.0


def fact(client, key, text):
    assert client.post(f"/v1/projects/{key}/memory/facts", json={"text": text}).status_code in (200, 201)


def recall(client, key, query):
    return client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
        "name": "viber_recall", "arguments": {"project": key, "query": query}}}).json()["result"]["content"][0]["text"]


def test_sync_embeds_what_is_missing_and_only_that(client, project_key):
    fact(client, project_key, "The updater verifies image digests before it starts.")
    fact(client, project_key, "Backups are kept for fourteen days.")
    first = client.post("/v1/embeddings/sync").json()
    assert first["embedded"] >= 2 and "error" not in first
    again = client.post("/v1/embeddings/sync").json()
    assert again["embedded"] == 0
    health = client.get("/v1/memory-health").json()
    assert health["model"] == "fake-64" and health["pending"] == 0 and health["vectors"] >= 2 and health["healthy"]


def test_a_changed_text_is_embedded_again(client, project_key):
    fact(client, project_key, "Original wording about caches.")
    client.post("/v1/embeddings/sync")
    from viber.db import transaction
    with transaction() as connection:
        connection.execute("UPDATE fact SET text = 'Completely different wording about queues.' WHERE text LIKE 'Original wording%'")
    assert client.get("/v1/memory-health").json()["pending"] >= 1
    assert client.post("/v1/embeddings/sync").json()["embedded"] >= 1


def test_text_that_looks_like_a_secret_is_withheld_but_still_found_by_keyword(client, project_key):
    fact(client, project_key, "The deploy password: hunter2hunter2 is set on the box.")
    result = client.post("/v1/embeddings/sync").json()
    assert result["withheld"] >= 1
    assert "hunter2hunter2" in recall(client, project_key, "deploy password")


def test_recall_uses_meaning_and_says_which_mode(client, project_key):
    fact(client, project_key, "Signing keys rotate every ninety days.")
    fact(client, project_key, "Charts need axes and a legend.")
    client.post("/v1/embeddings/sync")
    from viber import service
    from viber.db import transaction
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        found = service.recall(connection, project, "keys rotate signing", 3)
    assert found["mode"] == "hybrid" and found["items"][0]["content"].startswith("Signing keys")
    assert found["items"][0]["via"] == "both"


def test_recall_falls_back_to_keywords_when_the_service_is_down(client, project_key, monkeypatch):
    fact(client, project_key, "Retention is seven days on Personal.")
    client.post("/v1/embeddings/sync")
    monkeypatch.setenv("VIBER_EMBED_PROVIDER", "ollama")
    monkeypatch.setenv("VIBER_EMBED_URL", "http://127.0.0.1:9")
    from viber import service
    from viber.db import transaction
    with transaction() as connection:
        found = service.recall(connection, service.project_row(connection, project_key), "retention personal", 3)
    assert found["mode"] == "keyword" and "Retention is seven days" in found["context"]


def test_with_no_provider_it_says_keyword_only(client, project_key, monkeypatch):
    monkeypatch.setenv("VIBER_EMBED_PROVIDER", "none")
    health = client.get("/v1/memory-health").json()
    assert health["mode"] == "keyword only" and not health["healthy"]


def test_recall_checks_report_the_rank_of_the_expected_answer(client, project_key):
    fact(client, project_key, "Admins are never blocked, only asked for the second factor.")
    fact(client, project_key, "Charts need axes and a legend.")
    from viber import service
    from viber.db import transaction
    with transaction() as connection:
        fact_id = connection.execute("SELECT id FROM fact WHERE text LIKE 'Admins%' ORDER BY created_at DESC LIMIT 1").fetchone()["id"]
    client.post(f"/v1/projects/{project_key}/recall/checks", json={"query": "admin second factor", "expect_kind": "fact", "expect_id": str(fact_id)})
    client.post(f"/v1/projects/{project_key}/recall/checks", json={"query": "pizza", "expect_kind": "fact", "expect_id": str(fact_id)})
    report = client.get(f"/v1/projects/{project_key}/recall/checks/run").json()
    assert report["total"] == 2 and report["passed"] == 1
    assert [c["passed"] for c in report["checks"]] == [True, False]
