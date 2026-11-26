def seed(client, key, names=("alpha", "beta", "gamma")):
    for name in names:
        assert client.post(f"/v1/projects/{key}/components", json={"key": name, "repo": f"o/{key}-{name}"}).status_code == 201


def pack(client, key, component):
    return client.post(f"/v1/projects/{key}/sessions/start",
                       json={"session_id": f"s-{key}-{component}", "repo": f"o/{key}-{component}" if component else None}).json()["context"]


def propose(client, key, text, **extra):
    return client.post(f"/v1/projects/{key}/memory/rules", json={"text": text, **extra}).json()


def accept(client, key, rule_id):
    assert client.post(f"/v1/projects/{key}/memory/rules/{rule_id}/accept").status_code == 200


def rule_row(client, key, rule_id):
    return next(r for r in client.get(f"/v1/projects/{key}/memory/rules").json() if r["id"] == rule_id)


def test_one_rule_reaches_exactly_the_components_it_lists(client, project_key):
    seed(client, project_key)
    made = propose(client, project_key, "Check access before reading the body.", components=["beta", "alpha", "beta"])
    accept(client, project_key, made["id"])
    assert "Check access before reading the body." in pack(client, project_key, "alpha")
    assert "Check access before reading the body." in pack(client, project_key, "beta")
    assert "Check access before reading the body." not in pack(client, project_key, "gamma")
    assert "Check access before reading the body." not in pack(client, project_key, None)
    row = rule_row(client, project_key, made["id"])
    assert row["components"] == ["alpha", "beta"] and row["scope"] == "component:alpha,beta"


def test_the_same_rule_proposed_twice_is_one_rule_however_the_list_is_ordered(client, project_key):
    first = propose(client, project_key, "One lock per move.", components=["b", "a"])
    again = propose(client, project_key, "One lock per move.", scope="component:a,b")
    assert again["id"] == first["id"]


def test_the_old_single_component_spelling_still_works(client, project_key):
    seed(client, project_key)
    made = propose(client, project_key, "Only alpha.", scope="component:alpha")
    accept(client, project_key, made["id"])
    assert rule_row(client, project_key, made["id"])["components"] == ["alpha"]
    assert "Only alpha." in pack(client, project_key, "alpha") and "Only alpha." not in pack(client, project_key, "beta")


def test_a_rule_can_be_widened_narrowed_and_made_project_wide(client, project_key):
    seed(client, project_key)
    made = propose(client, project_key, "Tests run in Docker.", scope="component:alpha")
    accept(client, project_key, made["id"])
    url = f"/v1/projects/{project_key}/memory/rules/{made['id']}/components"
    assert client.put(url, json={"components": ["gamma", "alpha"]}).json()["scope"] == "component:alpha,gamma"
    assert "Tests run in Docker." in pack(client, project_key, "gamma")
    assert client.put(url, json={"components": []}).json() == {"id": made["id"], "scope": "project", "components": []}
    assert "Tests run in Docker." in pack(client, project_key, "beta") and "Tests run in Docker." in pack(client, project_key, None)
    assert client.put(url, json={"components": ["nope"]}).status_code == 422
    client.post(f"/v1/projects/{project_key}/memory/rules/{made['id']}/retire")
    assert client.put(url, json={"components": ["alpha"]}).status_code == 409


def test_the_list_and_the_scope_cannot_disagree_even_when_written_with_sql(client, project_key):
    from viber.db import transaction
    made = propose(client, project_key, "Written straight into the table.")
    with transaction() as connection:
        connection.execute("UPDATE rule SET scope = 'component:z,y' WHERE id::text = %s", (made["id"],))
        row = connection.execute("SELECT scope, components FROM rule WHERE id::text = %s", (made["id"],)).fetchone()
        assert (row["scope"], row["components"]) == ("component:y,z", ["y", "z"])
        connection.execute("UPDATE rule SET scope = 'project' WHERE id::text = %s", (made["id"],))
        assert connection.execute("SELECT components FROM rule WHERE id::text = %s", (made["id"],)).fetchone()["components"] == []


def test_recall_says_when_a_rule_is_only_for_some_components(client, project_key):
    made = propose(client, project_key, "Pelican uploads are signed.", components=["alpha", "beta"])
    accept(client, project_key, made["id"])
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "viber_recall", "arguments": {"project": project_key, "query": "pelican uploads"}}}
    assert "[only for alpha, beta] Pelican uploads are signed." in client.post("/mcp", json=body).json()["result"]["content"][0]["text"]


def test_only_a_reviewer_may_change_what_a_rule_covers(client, project_key, monkeypatch):
    seed(client, project_key)
    made = propose(client, project_key, "Guard the gate.")
    monkeypatch.setenv("VIBER_TOKEN", "master-secret")
    master = {"Authorization": "Bearer master-secret"}
    writer = {"Authorization": "Bearer " + client.post("/v1/tokens", json={"name": f"w-{project_key}", "role": "write"}, headers=master).json()["token"]}
    url = f"/v1/projects/{project_key}/memory/rules/{made['id']}/components"
    assert client.put(url, json={"components": ["alpha"]}, headers=writer).status_code == 403
    assert client.put(url, json={"components": ["alpha"]}, headers=master).status_code == 200
