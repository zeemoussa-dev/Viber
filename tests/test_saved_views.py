def view(list_name="memory-rules", name="Mine", group="status", filters=None, query=""):
    return {"list": list_name, "name": name, "choice": {"group": group, "filters": filters or {}, "query": query}}


def test_a_view_is_saved_listed_per_list_replaced_by_name_and_removed(client, project_key):
    base = f"/v1/projects/{project_key}/saved-views"
    first = client.put(base, json=view(filters={"component": ["sb-web"]}, query="login")).json()
    assert first["created"] is True and first["choice"] == {"group": "status", "filters": {"component": ["sb-web"]}, "query": "login"}
    client.put(base, json=view(list_name="decisions", name="Other list"))
    assert [v["name"] for v in client.get(base, params={"list": "memory-rules"}).json()] == ["Mine"]
    assert len(client.get(base).json()) == 2
    # The same name in other capitals replaces the view instead of making a second one.
    again = client.put(base, json=view(name="  MINE ", group="")).json()
    assert again["id"] == first["id"] and again["created"] is False and again["name"] == "MINE" and again["choice"]["group"] == ""
    assert client.delete(f"{base}/{first['id']}").json() == {"deleted": "MINE"}
    assert client.get(base, params={"list": "memory-rules"}).json() == []
    assert client.delete(f"{base}/{first['id']}").status_code == 404


def test_views_need_a_name_stay_small_and_stay_inside_their_project(client, project_key):
    base = f"/v1/projects/{project_key}/saved-views"
    assert client.put(base, json=view(name="   ")).status_code == 422
    assert client.put(base, json=view(name="x" * 61)).status_code == 422
    assert client.put(base, json=view(query="x" * 201)).status_code == 422
    assert client.put(base, json=view(filters={"component": [str(n) for n in range(201)]})).status_code == 422
    other = project_key + "v"
    client.post("/v1/projects", json={"key": other, "name": other})
    mine = client.put(base, json=view()).json()
    assert client.get(f"/v1/projects/{other}/saved-views").json() == []
    assert client.delete(f"/v1/projects/{other}/saved-views/{mine['id']}").status_code == 404
    assert len(client.get(base).json()) == 1


def test_a_reader_sees_views_but_cannot_change_them(client, project_key, monkeypatch):
    base = f"/v1/projects/{project_key}/saved-views"
    monkeypatch.setenv("VIBER_TOKEN", "master-secret")
    master = {"Authorization": "Bearer master-secret"}
    reader = {"Authorization": "Bearer " + client.post("/v1/tokens", json={"name": f"sv-{project_key}", "role": "read"}, headers=master).json()["token"]}
    saved = client.put(base, json=view(), headers=master).json()
    assert client.get(base, headers=reader).status_code == 200
    assert client.put(base, json=view(name="Theirs"), headers=reader).status_code == 403
    assert client.delete(f"{base}/{saved['id']}", headers=reader).status_code == 403
