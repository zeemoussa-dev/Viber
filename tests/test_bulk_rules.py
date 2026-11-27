def propose(client, key, text):
    return client.post(f"/v1/projects/{key}/memory/rules", json={"text": text}).json()["id"]


def statuses(client, key):
    return {r["text"]: r["status"] for r in client.get(f"/v1/projects/{key}/memory/rules").json()}


def test_many_rules_can_be_accepted_or_dismissed_at_once_and_only_proposed_ones_change(client, project_key):
    ids = [propose(client, project_key, f"Bulk rule {n}.") for n in range(4)]
    base = f"/v1/projects/{project_key}/memory/rules/bulk"
    assert client.post(f"{base}/accept", json={"ids": ids[:2]}).json() == {"done": 2, "unchanged": 0}
    # A bulk dismiss never removes a rule that is already accepted.
    assert client.post(f"{base}/retire", json={"ids": ids}).json() == {"done": 2, "unchanged": 2}
    assert statuses(client, project_key) == {"Bulk rule 0.": "accepted", "Bulk rule 1.": "accepted", "Bulk rule 2.": "retired", "Bulk rule 3.": "retired"}
    from viber.db import transaction
    with transaction() as connection:
        audited = connection.execute("SELECT count(*) AS n FROM audit WHERE entity = 'rule' AND action IN ('accept','retire') "
                                     "AND project_id = (SELECT id FROM project WHERE key = %s)", (project_key,)).fetchone()["n"]
    assert audited == 4


def test_bulk_changes_stay_inside_the_project_and_need_a_reviewer(client, project_key, monkeypatch):
    other = project_key + "b"
    client.post("/v1/projects", json={"key": other, "name": other})
    foreign = propose(client, other, "Belongs elsewhere.")
    assert client.post(f"/v1/projects/{project_key}/memory/rules/bulk/accept", json={"ids": [foreign]}).json() == {"done": 0, "unchanged": 1}
    assert statuses(client, other) == {"Belongs elsewhere.": "proposed"}
    mine = propose(client, project_key, "Mine.")
    monkeypatch.setenv("VIBER_TOKEN", "master-secret")
    master = {"Authorization": "Bearer master-secret"}
    writer = {"Authorization": "Bearer " + client.post("/v1/tokens", json={"name": f"bw-{project_key}", "role": "write"}, headers=master).json()["token"]}
    for verb in ("accept", "retire"):
        assert client.post(f"/v1/projects/{project_key}/memory/rules/bulk/{verb}", json={"ids": [mine]}, headers=writer).status_code == 403
    assert client.post(f"/v1/projects/{project_key}/memory/rules/bulk/accept", json={"ids": [mine]}, headers=master).json()["done"] == 1


def test_the_review_queue_says_where_each_rule_came_from(client, project_key):
    client.post(f"/v1/projects/{project_key}/memory/rules", json={"text": "From a file.", "source": "v2-memory", "source_ref": "L1"})
    assert client.get(f"/v1/projects/{project_key}/review").json()["rules"][0]["source"] == "v2-memory"


def test_finished_work_leaves_the_flagged_queue(client, project_key):
    base = f"/v1/projects/{project_key}"
    for title, status in (("Needs you", "Open"), ("Long done", "Done"), ("Cancelled", "Dropped")):
        client.post(f"{base}/items", json={"kind": "task", "title": title, "status": status, "gate": "flagged", "gate_reason": "decide"})
    review = client.get(f"{base}/review").json()
    assert [i["title"] for i in review["items"]] == ["Needs you"] and review["counts"]["items"] == 1
