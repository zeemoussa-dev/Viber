from viber.atoms import split_atoms


def call(client, project_key, name, **arguments):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {"project": project_key, **arguments}}}
    return client.post("/mcp", json=body).json()["result"]["content"][0]["text"]


def decide(client, project_key, key, title="t", **sections):
    payload = {"key": key, "title": title, "status": "Accepted", **sections}
    assert client.post(f"/v1/projects/{project_key}/decisions", json=payload).status_code in (200, 201)


def test_splitter_makes_one_short_row_per_statement():
    text = "- first point\n2. second point\n\n" + ("A sentence of some length. " * 40)
    atoms = split_atoms(text, 100)
    assert atoms[:2] == ["first point", "second point"]
    assert all(len(a) <= 100 for a in atoms) and len(atoms) > 3


def test_a_wrapped_paragraph_stays_one_statement_and_a_bullet_starts_a_new_one():
    text = "Freeze new scope until the operator\ncan use Personal end to end.\n- Port from v2\n  first, always.\n- Show the work."
    assert split_atoms(text, 200) == ["Freeze new scope until the operator can use Personal end to end.",
                                      "Port from v2 first, always.", "Show the work."]


def test_next_adr_follows_the_projects_own_numbering_and_never_repeats(client, project_key):
    decide(client, project_key, "ADR-v3.016")
    decide(client, project_key, "ADR-v3.017")
    first = call(client, project_key, "viber_next_adr")
    second = call(client, project_key, "viber_next_adr")
    assert "ADR-v3.018" in first and "ADR-v3.019" in second


def test_get_adr_by_key_or_number_returns_statements_as_rows(client, project_key):
    decide(client, project_key, "ADR-v3.017", title="Freeze scope", context="Too much was in flight.",
           decision="- No new scope.\n- Port from v2 first.", consequences="Fewer surprises.")
    by_key = call(client, project_key, "viber_get_adr", adr="ADR-v3.017")
    by_number = call(client, project_key, "viber_get_adr", adr="17")
    assert by_key == by_number
    assert "- No new scope." in by_key and "- Port from v2 first." in by_key and "Freeze scope" in by_key
    rows = client.get(f"/v1/projects/{project_key}/adr/17").json()
    assert rows["decision"] == ["No new scope.", "Port from v2 first."]


def test_viber_decide_fills_a_reserved_number(client, project_key):
    decide(client, project_key, "ADR-001")
    reserved = call(client, project_key, "viber_next_adr").split()[0]
    assert reserved == "ADR-002"
    call(client, project_key, "viber_decide", key=reserved, title="Use rows", decision="Everything is a row.")
    assert "Use rows" in call(client, project_key, "viber_get_adr", adr=reserved)


def test_long_text_is_refused_for_facts_and_rules_and_specs(client, project_key):
    assert "Too long" in call(client, project_key, "viber_remember", text="x " * 400)
    assert "Too long" in call(client, project_key, "viber_remember", text="y " * 300, **{"as": "rule"})
    assert client.post(f"/v1/projects/{project_key}/specs", json={"statement": "z " * 300}).status_code == 422


def test_specs_are_rows_with_keys_and_a_status(client, project_key):
    added = call(client, project_key, "viber_spec_add", text="The API answers in 200 ms.\nIt refuses unsigned updates.", kind="requirement")
    assert "REQ-001" in added and "REQ-002" in added
    assert "REQ-002 [requirement, Draft] It refuses unsigned updates." in call(client, project_key, "viber_spec_get", key="REQ-002")
    call(client, project_key, "viber_spec_status", key="REQ-001", status="Agreed")
    assert "Agreed" in call(client, project_key, "viber_spec_get", query="200 ms")
    assert "Verified" not in call(client, project_key, "viber_spec_get", status="Agreed")


def test_graph_links_entities_aliases_and_facts(client, project_key):
    assert "(new)" in call(client, project_key, "viber_link", subject="sb-fleet", relation="depends on", object="sb-contracts")
    assert "(already known)" in call(client, project_key, "viber_link", subject="SB-Fleet", relation="Depends On", object="sb-contracts")
    client.post(f"/v1/projects/{project_key}/graph/aliases", json={"name": "sb-contracts", "aliases": ["contracts"]})
    call(client, project_key, "viber_link", subject="sb-billing", relation="depends on", object="contracts")
    call(client, project_key, "viber_remember", text="Contracts are versioned with semver.", about=["sb-contracts"])
    shown = call(client, project_key, "viber_graph", entity="contracts")
    assert "sb-fleet depends on sb-contracts" in shown and "sb-billing depends on sb-contracts" in shown
    assert "Contracts are versioned with semver." in shown
    client.post(f"/v1/projects/{project_key}/graph/unlink", json={"subject": "sb-fleet", "relation": "depends on", "object": "sb-contracts"})
    assert "sb-fleet" not in call(client, project_key, "viber_graph", entity="sb-contracts")


def test_recall_finds_decision_statements_and_specs(client, project_key):
    decide(client, project_key, "ADR-v3.001", title="Storage", decision="Postgres holds everything as tables.")
    call(client, project_key, "viber_spec_add", text="Backups run every night.")
    assert "Postgres holds everything" in call(client, project_key, "viber_recall", query="postgres tables")
    assert "Backups run every night." in call(client, project_key, "viber_recall", query="nightly backups")
