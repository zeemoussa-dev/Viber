import json

from viber.discovery import plan_components
from viber.manifests import parse_manifests

PLUGIN_JSON = json.dumps({"id": "Dev-Center", "name": "Dev Center", "version": "0.12.0", "framework_api": "14.33.0",
                          "requires": [], "flavours": [{"id": "github"}]})

CHART_YAML = """
apiVersion: v2
name: sbos-cell
version: 0.1.0
appVersion: "v3.0"
dependencies:
  - name: cell-database
    version: "^0.1.0"
    repository: file://../cell-database
"""


def test_plugin_json_gives_id_version_and_plugin_api_contract():
    manifest = parse_manifests({"plugin.json": PLUGIN_JSON})[0][0]
    assert (manifest.name, manifest.version, manifest.ecosystem) == ("dev-center", "0.12.0", "plugin")
    assert manifest.contracts == [{"contract": "plugin-api", "constraint": ">=14.33.0", "syntax": "semver"}]


def test_plugin_requires_become_plugin_dependencies():
    text = json.dumps({"id": "b", "version": "1.0.0", "requires": ["a", {"id": "c", "version": "^1.2.0"}]})
    manifest = parse_manifests({"plugin.json": text})[0][0]
    assert {(d.name, d.ecosystem, d.constraint) for d in manifest.dependencies} == {("a", "plugin", ""), ("c", "plugin", "^1.2.0")}


def test_helm_chart_and_version_file():
    chart = parse_manifests({"Chart.yaml": CHART_YAML})[0][0]
    assert (chart.name, chart.version, chart.ecosystem) == ("sbos-cell", "0.1.0", "helm")
    assert [(d.name, d.constraint) for d in chart.dependencies] == [("cell-database", "^0.1.0")]
    assert parse_manifests({"VERSION": "v1.1.1059\n"})[0][0].version == "1.1.1059"
    assert parse_manifests({"VERSION": "\n"})[0][0].version is None
    assert parse_manifests({"VERSION": "not a version"})[0][0].version is None


def test_repo_with_root_manifest_is_one_component_and_nested_ones_are_ignored():
    plan = plan_components("sb-core", ["pyproject.toml", "tests/pyproject.toml", "docs/package.json", "sub/package.json"])
    assert [c["key"] for c in plan["components"]] == ["sb-core"]
    assert {i["path"] for i in plan["ignored"]} == {"tests/pyproject.toml", "docs/package.json", "sub/package.json"}


def test_plugin_repo_is_a_plugin_component():
    plan = plan_components("sb-plugins-x", ["plugin.json", "backend/main.py", "ui/package.json"])
    assert plan["components"] == [{"key": "sb-plugins-x", "path": "", "kind": "plugin", "manifests": ["plugin.json"]}]


def test_monorepo_without_root_manifest_splits_by_directory_and_skips_noise():
    plan = plan_components("sb-platform", [
        "charts/sbos-cell/Chart.yaml", "charts/cell-database/Chart.yaml", "deployer/pyproject.toml",
        "deployer/Dockerfile", "tests/e2e/package.json"])
    keys = {c["key"]: c for c in plan["components"]}
    assert set(keys) == {"sb-platform.sbos-cell", "sb-platform.cell-database", "sb-platform.deployer"}
    assert keys["sb-platform.sbos-cell"]["kind"] == "chart" and keys["sb-platform.deployer"]["kind"] == "service"
    assert keys["sb-platform.sbos-cell"]["path"] == "charts/sbos-cell"
    assert [i["path"] for i in plan["ignored"]] == ["tests/e2e/package.json"]


def test_version_only_root_still_allows_nested_components():
    plan = plan_components("second_brain", [
        "VERSION", "src/frontend/package.json", "src/channels/whatsapp_bridge/package.json",
        "src/backend/tests/fixture_plugin/plugin.json", "docs/VERSION"])
    keys = [c["key"] for c in plan["components"]]
    assert keys == ["second_brain", "second_brain.whatsapp_bridge", "second_brain.frontend"] or \
        sorted(keys) == sorted(["second_brain", "second_brain.whatsapp_bridge", "second_brain.frontend"])
    assert len(plan["ignored"]) == 2


def test_colliding_leaf_names_use_the_full_path():
    plan = plan_components("r", ["a/web/package.json", "b/web/package.json"])
    assert sorted(c["key"] for c in plan["components"]) == ["r.a-web", "r.b-web"]


def test_discover_endpoint(client, project_key):
    response = client.post(f"/v1/projects/{project_key}/discover", json={"repo": "r", "paths": ["plugin.json"]})
    assert response.json()["components"][0]["kind"] == "plugin"
    assert client.post("/v1/projects/nope/discover", json={"repo": "r", "paths": []}).status_code == 404


def scan_plugin(client, project_key, component, plugin_id, version, framework_api, requires=()):
    body = {"commit_sha": "c", "ref": "main", "files": {"plugin.json": json.dumps(
        {"id": plugin_id, "version": version, "framework_api": framework_api, "requires": list(requires)})}}
    response = client.post(f"/v1/projects/{project_key}/components/{component}/scan", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_plugin_scan_creates_a_contract_link_and_flags_missing_provider(client, project_key):
    client.post(f"/v1/projects/{project_key}/components", json={"key": "dev-center", "kind": "plugin"})
    result = scan_plugin(client, project_key, "dev-center", "dev-center", "0.12.0", "14.33.0")
    assert result["links_from_manifests"] == 1
    links = client.get(f"/v1/projects/{project_key}/links").json()
    assert (links[0]["to_contract"], links[0]["type"], links[0]["constraint"], links[0]["state"]) == \
        ("plugin-api", "consumes", ">=14.33.0", "verified")
    problems = client.get(f"/v1/projects/{project_key}/links/check").json()["problems"]
    assert [p["issue"] for p in problems] == ["no_provider"]


def test_provider_resolves_the_contract_and_plugin_dependencies_link(client, project_key):
    for key, kind in (("runtime", "service"), ("a", "plugin"), ("b", "plugin")):
        client.post(f"/v1/projects/{project_key}/components", json={"key": key, "kind": kind})
    client.post(f"/v1/projects/{project_key}/components/runtime/scan", json={
        "commit_sha": "r", "ref": "main", "files": {"pyproject.toml": '[project]\nname="rt"\nversion="0.1.0"\n'}})
    assert client.post(f"/v1/projects/{project_key}/contracts", json={"key": "plugin-api"}).status_code == 201
    assert client.post(f"/v1/projects/{project_key}/contracts/plugin-api/versions", json={"semver": "14.40.0"}).status_code == 201
    scan_plugin(client, project_key, "a", "a", "1.0.0", "14.33.0")
    scan_plugin(client, project_key, "b", "b", "1.0.0", "14.33.0", requires=["a"])
    client.post(f"/v1/projects/{project_key}/components/runtime/versions/0.1.0/provides",
                json={"contract": "plugin-api", "semver": "14.40.0"})
    assert client.get(f"/v1/projects/{project_key}/links/check").json()["problems"] == []
    plugin_links = {(l["from_component"], l["to_component"] or l["to_contract"]) for l in client.get(f"/v1/projects/{project_key}/links").json()}
    assert ("b", "a") in plugin_links and ("a", "plugin-api") in plugin_links


def test_dropping_the_framework_requirement_marks_the_contract_link_drifted(client, project_key):
    client.post(f"/v1/projects/{project_key}/components", json={"key": "p", "kind": "plugin"})
    scan_plugin(client, project_key, "p", "p", "1.0.0", "14.33.0")
    body = {"commit_sha": "c2", "ref": "main", "files": {"plugin.json": json.dumps({"id": "p", "version": "1.1.0"})}}
    client.post(f"/v1/projects/{project_key}/components/p/scan", json=body)
    states = [l["state"] for l in client.get(f"/v1/projects/{project_key}/links").json()]
    assert states == ["drifted"]


def test_tag_scan_without_a_tag_name_is_rejected(client, project_key):
    client.post(f"/v1/projects/{project_key}/components", json={"key": "p", "kind": "plugin"})
    body = {"is_tag": True, "files": {"plugin.json": json.dumps({"id": "p", "version": "1.0.0"})}}
    assert client.post(f"/v1/projects/{project_key}/components/p/scan", json=body).status_code == 422
    assert client.get(f"/v1/projects/{project_key}/components/p/versions").json() == []


def test_invalid_version_in_manifest_is_rejected_clearly(client, project_key):
    client.post(f"/v1/projects/{project_key}/components", json={"key": "p"})
    body = {"files": {"plugin.json": json.dumps({"id": "p", "version": "banana"})}}
    response = client.post(f"/v1/projects/{project_key}/components/p/scan", json=body)
    assert response.status_code == 422 and "banana" in response.text
