import uuid


def new_id():
    return f"sess-{uuid.uuid4().hex[:10]}"


def start(client, project_key, session_id=None, **extra):
    body = {"session_id": session_id or new_id(), **extra}
    response = client.post(f"/v1/projects/{project_key}/sessions/start", json=body)
    assert response.status_code == 200, response.text
    return {**response.json(), "session_id": body["session_id"]}


def add_component(client, project_key, key, repo=None, path=None):
    assert client.post(f"/v1/projects/{project_key}/components", json={"key": key, "repo": repo, "path": path}).status_code == 201


def test_sessions_get_sequential_tags_and_resuming_keeps_the_tag(client, project_key):
    first = start(client, project_key)
    second = start(client, project_key)
    assert (first["tag"], second["tag"]) == ("S1", "S2")
    assert start(client, project_key, first["session_id"], source="resume")["tag"] == "S1"


def test_session_resolves_component_by_repo_and_longest_subpath(client, project_key):
    add_component(client, project_key, "mono", repo="o/mono")
    add_component(client, project_key, "mono.web", repo="o/mono", path="apps/web")
    assert start(client, project_key, repo="o/mono", subpath="")["component"] == "mono"
    assert start(client, project_key, repo="o/mono", subpath="apps/web/src/")["component"] == "mono.web"
    assert start(client, project_key, repo="o/unknown")["component"] is None


def test_context_pack_carries_accepted_rules_only_and_stays_in_budget(client, project_key):
    accepted = client.post(f"/v1/projects/{project_key}/memory/rules", json={"text": "always run the migration under a lock"}).json()
    client.post(f"/v1/projects/{project_key}/memory/rules", json={"text": "unaccepted proposal about colours"})
    client.post(f"/v1/projects/{project_key}/memory/rules/{accepted['id']}/accept")
    for number in range(40):
        client.post(f"/v1/projects/{project_key}/decisions", json={"key": f"ADR-{number}", "title": "decision " + "x" * 120})
    small = start(client, project_key, budget_tokens=300)
    assert "always run the migration under a lock" in small["context"]
    assert "colours" not in small["context"]
    assert small["tokens_estimate"] <= 320
    assert small["context"].count("ADR-") <= 5


def test_handoff_reaches_a_fork_and_a_sibling_but_not_its_author(client, project_key):
    parent = start(client, project_key, goal="build the importer")
    r = client.post(f"/v1/projects/{project_key}/sessions/{parent['session_id']}/handoff", json={
        "summary": "Importer parses BUGS.md rows", "decisions": ["keys stay as written"], "next_steps": ["parse ADR files"]})
    assert r.status_code == 201
    fork = start(client, project_key, parent_session_id=parent["session_id"], source="resume")
    assert fork["parent"] == parent["session_id"]
    assert "Importer parses BUGS.md rows" in fork["context"] and "keys stay as written" in fork["context"]
    again = start(client, project_key, parent["session_id"])
    assert "Importer parses BUGS.md rows" not in again["context"]


def test_handoff_is_scoped_to_the_component(client, project_key):
    add_component(client, project_key, "a", repo="o/a")
    add_component(client, project_key, "b", repo="o/b")
    author = start(client, project_key, repo="o/a")
    client.post(f"/v1/projects/{project_key}/sessions/{author['session_id']}/handoff", json={"summary": "only about component a"})
    assert "only about component a" in start(client, project_key, repo="o/a")["context"]
    assert "only about component a" not in start(client, project_key, repo="o/b")["context"]


def test_two_sessions_editing_the_same_file_get_a_collision_warning(client, project_key):
    a = start(client, project_key, goal="fix header")
    b = start(client, project_key, goal="restyle nav")
    url = lambda s: f"/v1/projects/{project_key}/sessions/{s['session_id']}/touch"
    assert client.post(url(a), json={"path": "src\\app.ts", "tool": "Edit"}).json()["overlaps"] == []
    overlap = client.post(url(b), json={"path": "./src/app.ts", "tool": "Edit"}).json()
    assert overlap["path"] == "src/app.ts" and [o["tag"] for o in overlap["overlaps"]] == [a["tag"]]
    assert client.post(url(b), json={"path": "src/other.ts"}).json()["overlaps"] == []
    assert "editing: src/app.ts" in start(client, project_key)["context"]


def test_ended_sessions_no_longer_collide(client, project_key):
    a, b = start(client, project_key), start(client, project_key)
    base = f"/v1/projects/{project_key}/sessions"
    client.post(f"{base}/{a['session_id']}/touch", json={"path": "x.py"})
    client.post(f"{base}/{a['session_id']}/end", json={"summary": "done"})
    assert client.post(f"{base}/{b['session_id']}/touch", json={"path": "x.py"}).json()["overlaps"] == []
    assert [s["tag"] for s in client.get(base).json()] == [b["tag"]]


def test_unregistered_session_is_a_clear_404(client, project_key):
    assert client.post(f"/v1/projects/{project_key}/sessions/ghost/touch", json={"path": "x"}).status_code == 404


def test_session_stats_report_pack_sizes_forks_overlaps_and_handoffs(client, project_key):
    a = start(client, project_key)
    start(client, project_key, parent_session_id=a["session_id"])
    client.post(f"/v1/projects/{project_key}/sessions/{a['session_id']}/handoff", json={"summary": "s"})
    stats = client.get(f"/v1/projects/{project_key}/stats/sessions").json()
    assert stats["context_packs"]["packs"] == 2 and stats["sessions"]["forks"] == 1 and stats["handoffs"] == 1


def rpc(client, method, params=None, request_id=1, headers=None):
    body = {"jsonrpc": "2.0", "method": method, **({"id": request_id} if request_id is not None else {}), "params": params or {}}
    return client.post("/mcp", json=body, headers=headers or {})


def call(client, name, arguments):
    result = rpc(client, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
    return result["content"][0]["text"], result["isError"]


def test_mcp_handshake_and_tool_list(client):
    init = rpc(client, "initialize", {"protocolVersion": "2025-06-18"}).json()["result"]
    assert init["protocolVersion"] == "2025-06-18" and init["serverInfo"]["name"] == "viber"
    assert rpc(client, "notifications/initialized", request_id=None).status_code == 202
    names = {t["name"] for t in rpc(client, "tools/list").json()["result"]["tools"]}
    assert {"viber_recall", "viber_context", "viber_quick", "viber_bug", "viber_remember", "viber_decide",
            "viber_handoff", "viber_sessions"} <= names
    assert rpc(client, "nope").json()["error"]["code"] == -32601
    assert client.get("/mcp").status_code == 405


def test_mcp_quick_bug_remember_recall_roundtrip(client, project_key):
    text, error = call(client, "viber_quick", {"project": project_key, "title": "Renamed the header class"})
    assert not error and "Logged" in text
    assert "feat: " not in client.get(f"/v1/projects/{project_key}/views/changelog").text
    assert "- change: Renamed the header class" in client.get(f"/v1/projects/{project_key}/views/changelog").text
    text, _ = call(client, "viber_bug", {"project": project_key, "title": "Login button dead", "repro": "click it", "severity": "Major"})
    assert "BUG-001" in text
    call(client, "viber_remember", {"project": project_key, "text": "Login goes through the gateway"})
    recalled, _ = call(client, "viber_recall", {"project": project_key, "query": "login"})
    assert "Login goes through the gateway" in recalled and "BUG-001" in recalled
    proposed, _ = call(client, "viber_remember", {"project": project_key, "text": "never log tokens", "as": "rule"})
    assert "human must accept" in proposed
    assert client.get(f"/v1/projects/{project_key}/memory/rules", params={"status": "proposed"}).json()[0]["text"] == "never log tokens"


def test_mcp_decide_continues_the_imported_adr_numbering(client, project_key):
    client.post(f"/v1/projects/{project_key}/decisions", json={"key": "ADR-141", "title": "old"})
    text, _ = call(client, "viber_decide", {"project": project_key, "title": "New thing", "decision": "do it"})
    assert "ADR-142" in text
    status = [d for d in client.get(f"/v1/projects/{project_key}/decisions").json() if d["key"] == "ADR-142"][0]["status"]
    assert status == "Proposed"


def test_mcp_handoff_and_sessions_tools(client, project_key):
    session = start(client, project_key, goal="wire hooks")
    text, error = call(client, "viber_handoff", {"project": project_key, "session_id": session["session_id"], "summary": "hooks wired"})
    assert not error and session["tag"] in text
    other = start(client, project_key, goal="other")
    listing, _ = call(client, "viber_sessions", {"project": project_key})
    assert "wire hooks" in listing and other["tag"] in listing
    ctx, _ = call(client, "viber_context", {"project": project_key, "session_id": other["session_id"]})
    assert "hooks wired" in ctx


def test_a_session_can_use_its_tag_where_a_tool_asks_for_its_session_id(client, project_key):
    session = start(client, project_key, goal="by tag")
    assert f"session_id='{session['tag']}'" in session["context"]
    text, error = call(client, "viber_handoff", {"project": project_key, "session_id": session["tag"].lower(), "summary": "via tag"})
    assert not error and session["tag"] in text
    other = start(client, project_key)
    ctx, _ = call(client, "viber_context", {"project": project_key, "session_id": other["tag"]})
    assert "via tag" in ctx
    base = f"/v1/projects/{project_key}/sessions"
    assert client.post(f"{base}/{session['tag']}/touch", json={"path": "x.py"}).status_code == 200
    assert client.post(f"{base}/S999/touch", json={"path": "x.py"}).status_code == 404


def test_mcp_errors_are_reported_not_raised(client, project_key):
    assert call(client, "viber_recall", {"project": "nope", "query": "x"})[1] is True
    assert call(client, "viber_recall", {"project": project_key})[1] is True
    assert call(client, "viber_nothing", {"project": project_key})[1] is True


def test_mcp_requires_the_token_when_set(client, monkeypatch):
    monkeypatch.setenv("VIBER_TOKEN", "secret")
    assert rpc(client, "ping").status_code == 401
    assert rpc(client, "ping", headers={"Authorization": "Bearer secret"}).status_code == 200


def test_the_newest_handoff_reaches_the_next_session_whole_and_older_ones_are_shortened(client, project_key):
    first = start(client, project_key)
    client.post(f"/v1/projects/{project_key}/sessions/{first['session_id']}/handoff",
                json={"summary": "old " + "o" * 900, "next_steps": ["old-last-step"]})
    second = start(client, project_key)
    client.post(f"/v1/projects/{project_key}/sessions/{second['session_id']}/handoff",
                json={"summary": "new " + "n" * 900, "open_questions": ["pick A or C"], "next_steps": ["do the final step"]})
    pack = start(client, project_key)["context"]
    assert "pick A or C" in pack and "do the final step" in pack
    assert "old-last-step" not in pack
