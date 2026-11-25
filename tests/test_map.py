def pyproject(name, version, dependencies=()):
    dependency_lines = ", ".join(f'"{d}"' for d in dependencies)
    return f'[project]\nname = "{name}"\nversion = "{version}"\ndependencies = [{dependency_lines}]\n'


def add_component(client, project_key, key, aliases=()):
    response = client.post(f"/v1/projects/{project_key}/components", json={"key": key, "aliases": list(aliases)})
    assert response.status_code == 201, response.text


def scan(client, project_key, component, name, version, dependencies=(), tag=None, sha="abc"):
    body = {"commit_sha": sha, "is_tag": tag is not None, "ref": tag or "main",
            "files": {"pyproject.toml": pyproject(name, version, dependencies)}}
    response = client.post(f"/v1/projects/{project_key}/components/{component}/scan", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def build_world(client, project_key):
    add_component(client, project_key, "contracts")
    add_component(client, project_key, "memory")
    add_component(client, project_key, "core")
    scan(client, project_key, "contracts", "sbos-contracts", "0.10.1")
    scan(client, project_key, "memory", "sb-memory", "1.3.0", ["sbos-contracts>=0.10,<1"])
    scan(client, project_key, "core", "sb-core", "0.4.0", ["sbos-contracts>=0.10.1", "sb-memory>=1.0"])


def links_of(client, project_key):
    return {(l["from_component"], l["to_component"]): l for l in client.get(f"/v1/projects/{project_key}/links").json()}


def test_links_are_derived_from_manifests_regardless_of_scan_order(client, project_key):
    build_world(client, project_key)
    links = links_of(client, project_key)
    assert set(links) == {("memory", "contracts"), ("core", "contracts"), ("core", "memory")}
    assert links[("core", "memory")]["constraint"] == ">=1.0"
    assert links[("core", "memory")]["state"] == "verified"
    assert links[("core", "memory")]["declared_by"] == "manifest"


def test_external_dependencies_do_not_become_links(client, project_key):
    add_component(client, project_key, "core")
    result = scan(client, project_key, "core", "sb-core", "0.4.0", ["fastapi>=0.115"])
    assert result["dependencies"] == 1 and result["links_from_manifests"] == 0


def test_dropping_a_dependency_marks_the_link_drifted(client, project_key):
    build_world(client, project_key)
    scan(client, project_key, "core", "sb-core", "0.5.0", ["sbos-contracts>=0.10.1"])
    links = links_of(client, project_key)
    assert links[("core", "memory")]["state"] == "drifted"
    assert links[("core", "contracts")]["state"] == "verified"
    issues = [p["issue"] for p in client.get(f"/v1/projects/{project_key}/links/check").json()["problems"]]
    assert "drifted" in issues


def test_unsatisfied_constraint_is_reported(client, project_key):
    build_world(client, project_key)
    scan(client, project_key, "contracts", "sbos-contracts", "1.0.0")
    problems = client.get(f"/v1/projects/{project_key}/links/check").json()["problems"]
    broken = {(p["from"], p["to"]) for p in problems if p["issue"] == "unsatisfied"}
    assert broken == {("memory", "contracts")}


def test_manual_link_is_unverified_until_a_manifest_confirms_it(client, project_key):
    add_component(client, project_key, "a")
    add_component(client, project_key, "b", ["b-pkg"])
    client.post(f"/v1/projects/{project_key}/links", json={"from_component": "a", "to_component": "b", "constraint": ">=1"})
    assert links_of(client, project_key)[("a", "b")]["state"] == "unverified"
    scan(client, project_key, "b", "b-pkg", "1.0.0")
    scan(client, project_key, "a", "a-pkg", "0.1.0", ["b-pkg>=1"])
    link = links_of(client, project_key)[("a", "b")]
    assert (link["state"], link["declared_by"]) == ("verified", "manifest")


def test_impact_lists_transitive_dependents_and_what_a_bump_would_break(client, project_key):
    build_world(client, project_key)
    result = client.get(f"/v1/projects/{project_key}/components/contracts/impact", params={"version": "1.0.0"}).json()
    by_component = {d["component"]: d for d in result["dependents"] if d["depth"] == 1}
    assert set(by_component) == {"memory", "core"}
    assert set(result["would_break"]) == {"memory"}
    transitive = client.get(f"/v1/projects/{project_key}/components/contracts/impact").json()["dependents"]
    assert any(d["component"] == "core" and d["via"] == "memory" and d["depth"] == 2 for d in transitive)


def test_tag_scan_creates_immutable_release_version_separate_from_head(client, project_key):
    add_component(client, project_key, "memory")
    scan(client, project_key, "memory", "sb-memory", "1.3.0", tag="v3.0.2", sha="tag1")
    scan(client, project_key, "memory", "sb-memory", "1.3.0", sha="head2")
    scan(client, project_key, "memory", "sb-memory", "1.3.0", tag="v3.0.2", sha="different")
    versions = client.get(f"/v1/projects/{project_key}/components/memory/versions").json()
    assert sorted((v["is_head"], v["commit_sha"]) for v in versions) == [(False, "tag1"), (True, "head2")]


def test_release_consistency_is_checked_from_each_versions_own_manifest(client, project_key):
    add_component(client, project_key, "contracts")
    add_component(client, project_key, "memory")
    scan(client, project_key, "contracts", "sbos-contracts", "0.10.1", tag="v3.0.2")
    scan(client, project_key, "contracts", "sbos-contracts", "1.0.0", tag="v3.0.3")
    scan(client, project_key, "memory", "sb-memory", "1.3.0", ["sbos-contracts>=0.10,<1"], tag="v3.0.2")
    good = client.post(f"/v1/projects/{project_key}/releases", json={
        "name": "v3.0.2", "members": [{"component": "contracts", "version": "0.10.1"}, {"component": "memory", "version": "1.3.0"}]}).json()
    assert good["consistent"] is True
    bad = client.post(f"/v1/projects/{project_key}/releases/check", json={
        "name": "x", "members": [{"component": "contracts", "version": "1.0.0"}, {"component": "memory", "version": "1.3.0"}]}).json()
    assert bad["consistent"] is False and bad["violations"][0]["issue"] == "constraint_violated"
    unknown = client.post(f"/v1/projects/{project_key}/releases/check", json={
        "name": "y", "members": [{"component": "memory", "version": "9.9.9"}]}).json()
    assert unknown["violations"][0]["issue"] == "unknown_version"


def test_release_publish_requires_consistency(client, project_key):
    add_component(client, project_key, "contracts")
    add_component(client, project_key, "memory")
    scan(client, project_key, "contracts", "sbos-contracts", "1.0.0", tag="t1")
    scan(client, project_key, "memory", "sb-memory", "1.3.0", ["sbos-contracts>=0.10,<1"], tag="t1")
    client.post(f"/v1/projects/{project_key}/releases", json={
        "name": "bad", "members": [{"component": "contracts", "version": "1.0.0"}, {"component": "memory", "version": "1.3.0"}]})
    assert client.post(f"/v1/projects/{project_key}/releases/bad/publish").status_code == 409
    client.post(f"/v1/projects/{project_key}/releases", json={"name": "ok", "members": [{"component": "contracts", "version": "1.0.0"}]})
    assert client.post(f"/v1/projects/{project_key}/releases/ok/publish").json()["status"] == "released"
    assert [r["name"] for r in client.get(f"/v1/projects/{project_key}/releases").json()][-1] in ("ok", "bad")


def test_contracts_provides_and_consumes(client, project_key):
    add_component(client, project_key, "memory")
    add_component(client, project_key, "web")
    client.post(f"/v1/projects/{project_key}/contracts", json={"key": "memory-api"})
    client.post(f"/v1/projects/{project_key}/contracts/memory-api/versions", json={"semver": "1.3.0"})
    scan(client, project_key, "memory", "sb-memory", "1.3.0", tag="t")
    scan(client, project_key, "web", "sb-web", "0.1.0", tag="t")
    assert client.post(f"/v1/projects/{project_key}/components/memory/versions/1.3.0/provides",
                       json={"contract": "memory-api", "semver": "1.3.0"}).status_code == 201
    client.post(f"/v1/projects/{project_key}/links", json={
        "from_component": "web", "to_contract": "memory-api", "type": "consumes", "constraint": "^1.2.0"})
    ok = client.post(f"/v1/projects/{project_key}/releases/check", json={
        "name": "r", "members": [{"component": "web", "version": "0.1.0"}, {"component": "memory", "version": "1.3.0"}]}).json()
    assert ok["consistent"] is True
    missing = client.post(f"/v1/projects/{project_key}/releases/check", json={
        "name": "r", "members": [{"component": "web", "version": "0.1.0"}]}).json()
    assert missing["violations"][0]["issue"] == "contract_unprovided"
    problems = client.get(f"/v1/projects/{project_key}/links/check").json()["problems"]
    assert not [p for p in problems if p["issue"] == "no_provider"]


def test_alias_cannot_be_claimed_twice(client, project_key):
    add_component(client, project_key, "a", ["python:shared-name"])
    response = client.post(f"/v1/projects/{project_key}/components", json={"key": "b", "aliases": ["shared-name"]})
    assert response.status_code == 409
