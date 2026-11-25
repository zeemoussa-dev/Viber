import pytest

from viber.constraints import ConstraintError, highest, satisfies
from viber.manifests import parse_manifests


@pytest.mark.parametrize("version, constraint, syntax, expected", [
    ("1.4.0", ">=1.2,<2", "pep440", True),
    ("2.0.0", ">=1.2,<2", "pep440", False),
    ("0.10.1", ">=0.10.1", "pep440", True),
    ("1.2.3", "^1.2.0", "semver", True),
    ("2.0.0", "^1.2.0", "semver", False),
    ("0.2.5", "^0.2.3", "semver", True),
    ("0.3.0", "^0.2.3", "semver", False),
    ("0.0.4", "^0.0.3", "semver", False),
    ("1.2.9", "~1.2.3", "semver", True),
    ("1.3.0", "~1.2.3", "semver", False),
    ("1.9.0", "1.x", "semver", True),
    ("2.0.0", "1.x", "semver", False),
    ("1.2.5", "1.2", "semver", True),
    ("3.1.0", ">=1.0.0 <2.0.0 || >=3.0.0", "semver", True),
    ("2.5.0", ">=1.0.0 <2.0.0 || >=3.0.0", "semver", False),
    ("1.5.0", "1.2.3 - 2.0.0", "semver", True),
    ("2.0.1", "1.2.3 - 2.0.0", "semver", False),
    ("9.9.9", "*", "semver", True),
    ("9.9.9", "", "semver", True),
    ("v3.0.2", ">=3.0.0", "pep440", True),
    ("2.0.0", ">= 1.0.0", "semver", True),
])
def test_satisfies(version, constraint, syntax, expected):
    assert satisfies(version, constraint, syntax) is expected


def test_unreadable_things_raise_clearly():
    with pytest.raises(ConstraintError):
        satisfies("not-a-version", ">=1")
    with pytest.raises(ConstraintError):
        satisfies("1.0.0", "^banana")


def test_highest_ignores_garbage():
    assert highest(["0.9.0", "0.10.1", "junk", "0.10.0"]) == "0.10.1"
    assert highest([]) is None


PYPROJECT = """
[project]
name = "SB_Core"
version = "0.4.0"
dependencies = ["sbos-contracts>=0.10.1", "fastapi>=0.115,<1", "pyyaml>=6"]
[project.optional-dependencies]
postgres = ["psycopg[binary]>=3.1,<4"]
[project.entry-points."sbos.components"]
identity = "x:y"
"""


def test_pyproject_is_parsed_with_names_versions_scopes_and_entry_points():
    manifests, problems = parse_manifests({"pyproject.toml": PYPROJECT})
    assert not problems
    manifest = manifests[0]
    assert (manifest.name, manifest.version, manifest.ecosystem) == ("sb-core", "0.4.0", "python")
    by_name = {d.name: d for d in manifest.dependencies}
    assert by_name["sbos-contracts"].constraint == ">=0.10.1" and by_name["sbos-contracts"].scope == "runtime"
    assert by_name["psycopg"].scope == "optional"
    assert manifest.entry_point_groups == ["sbos.components"]


def test_package_json_is_parsed_and_local_references_are_skipped():
    text = ('{"name": "@sbos/Web", "version": "1.2.0", "dependencies": {"react": "^18.2.0", "local": "file:../x"},'
            ' "devDependencies": {"vite": "~5.0.0"}}')
    manifests, _ = parse_manifests({"package.json": text})
    manifest = manifests[0]
    assert manifest.name == "@sbos/web" and manifest.ecosystem == "npm"
    assert {(d.name, d.scope) for d in manifest.dependencies} == {("react", "runtime"), ("vite", "dev")}


def test_bad_manifest_is_reported_not_raised():
    manifests, problems = parse_manifests({"pyproject.toml": "this is [not toml"})
    assert manifests == [] and problems[0]["file"] == "pyproject.toml"
