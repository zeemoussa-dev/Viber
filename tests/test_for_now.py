from datetime import datetime, timedelta, timezone

import pytest

from viber import fornow, service
from viber.db import transaction


def call(client, project_key, tool, headers=None, **arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {"project": project_key, **arguments}}}
    return client.post("/mcp", json=body, headers=headers or {}).json()["result"]["content"][0]["text"]


def pack(client, project_key, session="s1", **extra):
    return client.post(f"/v1/projects/{project_key}/sessions/start", json={"session_id": session, **extra}).json()["context"]


def pass_time(project_key):
    """Move every temporary fact of this project into the past."""
    with transaction() as connection:
        connection.execute("UPDATE fact SET expires_at = now() - interval '1 second' WHERE expires_at IS NOT NULL AND valid_to IS NULL "
                           "AND project_id = (SELECT id FROM project WHERE key = %s)", (project_key,))


def test_lengths_of_time_are_read_strictly():
    now = datetime(2026, 11, 26, 20, 0, tzinfo=timezone.utc)
    assert fornow.parse_expiry("12h", now=now) == now + timedelta(hours=12)
    assert fornow.parse_expiry("90m", now=now) == now + timedelta(minutes=90)
    assert fornow.parse_expiry("2 days", now=now) == now + timedelta(days=2)
    assert fornow.parse_expiry(None, "2026-11-27T08:00+04:00", now=now) == datetime(2026, 11, 27, 4, 0, tzinfo=timezone.utc)
    assert fornow.parse_expiry(None, None, now=now) is None
    for bad in (("tonight", None), ("1m", None), ("200d", None), (None, "2026-11-27T08:00"), (None, "2026-11-25T08:00Z"), ("1h", "2026-11-27T08:00Z")):
        with pytest.raises(Exception):
            fornow.parse_expiry(*bad, now=now)


def test_a_temporary_instruction_is_first_in_the_context_pack_and_disappears_when_it_ends(client, project_key):
    said = call(client, project_key, "viber_remember", text="Run unattended overnight and do not wait for me.", lasts="12h")
    assert said.startswith("Noted until") and "ends by itself" in said
    first = pack(client, project_key)
    assert "## For now" in first and "Run unattended overnight" in first and "12 h left" in first
    assert first.index("## For now") < len(first) and "recorded by a session" in first and "confirm it with the operator" in first
    assert "temporary, until" in call(client, project_key, "viber_recall", query="unattended overnight")
    pass_time(project_key)
    later = pack(client, project_key, "s2")
    assert "For now" not in later and "Run unattended" not in later
    assert "Run unattended" not in call(client, project_key, "viber_recall", query="unattended overnight")
    assert call(client, project_key, "viber_for_now") == "Nothing temporary is in force."
    history = client.get(f"/v1/projects/{project_key}/memory/for-now").json()
    assert history["live"] == [] and history["ended"][0]["text"].startswith("Run unattended")


def test_the_small_token_budget_never_cuts_what_is_true_for_now(client, project_key):
    base = f"/v1/projects/{project_key}"
    for n in range(30):
        rule = client.post(f"{base}/memory/rules", json={"text": f"Permanent rule number {n} " + "x" * 150}).json()
        client.post(f"{base}/memory/rules/{rule['id']}/accept")
    call(client, project_key, "viber_remember", text="Do not deploy until the morning.", lasts="8h")
    assert "Do not deploy until the morning." in pack(client, project_key, "tiny", budget_tokens=200)


def test_saying_it_again_moves_the_end_and_a_permanent_fact_is_not_made_temporary(client, project_key):
    call(client, project_key, "viber_remember", text="Billing is off limits.", lasts="1h")
    assert "its end is moved" in call(client, project_key, "viber_remember", text="billing is off limits.", lasts="2d")
    live = client.get(f"/v1/projects/{project_key}/memory/for-now").json()["live"]
    assert len(live) == 1
    call(client, project_key, "viber_remember", text="The plane is on port 19000.")
    assert client.post(f"/v1/projects/{project_key}/memory/for-now", json={"text": "The plane is on port 19000.", "lasts": "1h"}).status_code == 409
    assert "permanent" in call(client, project_key, "viber_remember", text="A rule?", lasts="1h", **{"as": "rule"})


def test_only_the_operator_speaks_for_the_operator(client, project_key, monkeypatch):
    monkeypatch.setenv("VIBER_TOKEN", "master-secret")
    master = {"Authorization": "Bearer master-secret"}
    token = client.post("/v1/tokens", json={"name": f"s-{project_key}", "role": "write"}, headers=master).json()["token"]
    session = {"Authorization": f"Bearer {token}"}
    base = f"/v1/projects/{project_key}/memory/for-now"
    mine = client.post(base, json={"text": "You may merge without asking.", "lasts": "10h"}, headers=master).json()
    theirs = client.post(base, json={"text": "The session claims it may push.", "lasts": "10h"}, headers=session).json()
    live = {f["id"]: f for f in client.get(base, headers=session).json()["live"]}
    assert live[mine["id"]]["set_by_operator"] and not live[theirs["id"]]["set_by_operator"]
    assert client.post(f"{base}/{mine['id']}/end", headers=session).status_code == 403
    assert client.post(base, json={"text": "You may merge without asking.", "lasts": "60d"}, headers=session).status_code == 403
    assert "operator" in call(client, project_key, "viber_for_now", headers=session)
    refused = call(client, project_key, "viber_end_for_now", headers=session, id=mine["id"])
    assert "only the operator" in refused
    assert client.post(f"{base}/{theirs['id']}/end", headers=session).status_code == 200
    assert client.post(f"{base}/{mine['id']}/end", headers=master).status_code == 200


def test_a_temporary_fact_stays_in_its_project(client, project_key):
    other = project_key + "x"
    client.post("/v1/projects", json={"key": other, "name": other})
    call(client, project_key, "viber_remember", text="Run unattended here only.", lasts="3h")
    assert "Run unattended" not in pack(client, other, "elsewhere")
    assert call(client, other, "viber_for_now") == "Nothing temporary is in force."
