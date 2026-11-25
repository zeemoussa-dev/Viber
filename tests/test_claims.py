import uuid


def start(client, project_key, goal=None):
    sid = f"sess-{uuid.uuid4().hex[:10]}"
    body = {"session_id": sid}
    if goal:
        body["goal"] = goal
    assert client.post(f"/v1/projects/{project_key}/sessions/start", json=body).status_code == 200
    return sid


def claim(client, project_key, sid, paths, **extra):
    response = client.post(f"/v1/projects/{project_key}/sessions/{sid}/claim", json={"paths": paths, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_second_session_is_told_who_holds_the_file(client, project_key):
    first, second = start(client, project_key, "fix billing"), start(client, project_key)
    assert claim(client, project_key, first, ["src/a.py", "src/b.py"])["granted"] == ["src/a.py", "src/b.py"]
    result = claim(client, project_key, second, ["src/a.py", "src/c.py"])
    assert result["granted"] == ["src/c.py"]
    assert [(b["path"], b["held_by"], b["goal"]) for b in result["blocked"]] == [("src/a.py", "S1", "fix billing")]


def test_reclaiming_your_own_file_is_fine_and_paths_are_normalised(client, project_key):
    sid = start(client, project_key)
    claim(client, project_key, sid, ["src\\a.py"])
    assert claim(client, project_key, sid, ["src/a.py"])["granted"] == ["src/a.py"]


def test_release_frees_the_file_for_others(client, project_key):
    first, second = start(client, project_key), start(client, project_key)
    claim(client, project_key, first, ["x.py", "y.py"])
    response = client.post(f"/v1/projects/{project_key}/sessions/{first}/release", json={"paths": ["x.py"]})
    assert response.status_code == 200, response.text
    assert response.json()["released"] == ["x.py"]
    result = claim(client, project_key, second, ["x.py", "y.py"])
    assert result["granted"] == ["x.py"] and [b["path"] for b in result["blocked"]] == ["y.py"]


def test_ending_a_session_releases_everything_it_held(client, project_key):
    first, second = start(client, project_key), start(client, project_key)
    claim(client, project_key, first, ["x.py", "y.py"])
    client.post(f"/v1/projects/{project_key}/sessions/{first}/end", json={})
    assert claim(client, project_key, second, ["x.py", "y.py"])["blocked"] == []
    assert {c["tag"] for c in client.get(f"/v1/projects/{project_key}/claims").json()} == {"S2"}


def test_an_expired_claim_does_not_block(client, project_key):
    from viber.db import transaction
    first, second = start(client, project_key), start(client, project_key)
    claim(client, project_key, first, ["old.py"])
    with transaction() as connection:
        connection.execute("UPDATE file_claim SET expires_at = now() - interval '1 minute'")
    assert claim(client, project_key, second, ["old.py"])["granted"] == ["old.py"]


def test_sessions_racing_for_one_file_cannot_both_win(client, project_key):
    from concurrent.futures import ThreadPoolExecutor
    sessions = [start(client, project_key) for _ in range(6)]
    with ThreadPoolExecutor(6) as pool:
        results = list(pool.map(lambda s: claim(client, project_key, s, ["race.py"]), sessions))
    assert sum(1 for r in results if r["granted"]) == 1


def test_mcp_claim_reports_the_blocker(client, project_key):
    first, second = start(client, project_key), start(client, project_key)

    def call(name, **arguments):
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": {"project": project_key, **arguments}}}
        return client.post("/mcp", json=body).json()["result"]["content"][0]["text"]

    assert "Claimed: a.py" in call("viber_claim", session_id=first, paths=["a.py"])
    assert "BLOCKED a.py: held by S1" in call("viber_claim", session_id=second, paths=["a.py"])
    assert "Released: a.py" in call("viber_release", session_id=first)
