"""Read dependency facts out of manifests. Deterministic only: no model ever decides a version or a link."""
import json
import tomllib
from dataclasses import dataclass, field

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from .constraints import ConstraintError, parse_version


@dataclass
class Dependency:
    name: str
    ecosystem: str
    constraint: str
    syntax: str
    scope: str


@dataclass
class ParsedManifest:
    file: str
    ecosystem: str
    name: str | None
    version: str | None
    dependencies: list[Dependency] = field(default_factory=list)
    entry_point_groups: list[str] = field(default_factory=list)
    contracts: list[dict] = field(default_factory=list)  # contracts this manifest consumes


def python_dependency(requirement_text: str, scope: str) -> Dependency | None:
    try:
        requirement = Requirement(requirement_text)
    except InvalidRequirement:
        return None
    return Dependency(canonicalize_name(requirement.name), "python", str(requirement.specifier), "pep440", scope)


def parse_pyproject(file: str, text: str) -> ParsedManifest:
    document = tomllib.loads(text)
    project = document.get("project", {})
    manifest = ParsedManifest(file, "python", None, project.get("version"))
    if project.get("name"):
        manifest.name = canonicalize_name(project["name"])
    for requirement_text in project.get("dependencies", []):
        if dependency := python_dependency(requirement_text, "runtime"):
            manifest.dependencies.append(dependency)
    for group_requirements in project.get("optional-dependencies", {}).values():
        for requirement_text in group_requirements:
            if dependency := python_dependency(requirement_text, "optional"):
                manifest.dependencies.append(dependency)
    for group_requirements in document.get("dependency-groups", {}).values():
        for entry in group_requirements:
            if isinstance(entry, str) and (dependency := python_dependency(entry, "dev")):
                manifest.dependencies.append(dependency)
    manifest.entry_point_groups = sorted(project.get("entry-points", {}))
    return manifest


NPM_SCOPES = {
    "dependencies": "runtime",
    "peerDependencies": "peer",
    "optionalDependencies": "optional",
    "devDependencies": "dev",
}


def parse_package_json(file: str, text: str) -> ParsedManifest:
    document = json.loads(text)
    manifest = ParsedManifest(file, "npm", (document.get("name") or "").lower() or None, document.get("version"))
    for section, scope in NPM_SCOPES.items():
        for name, constraint in (document.get(section) or {}).items():
            if isinstance(constraint, str) and not constraint.startswith(("file:", "link:", "workspace:", "git", "http")):
                manifest.dependencies.append(Dependency(name.lower(), "npm", constraint, "semver", scope))
    return manifest


PLUGIN_API_CONTRACT = "plugin-api"


def parse_plugin_json(file: str, text: str) -> ParsedManifest:
    document = json.loads(text)
    manifest = ParsedManifest(file, "plugin", (document.get("id") or "").lower() or None, document.get("version"))
    for required in document.get("requires") or []:
        name, constraint = (required, "") if isinstance(required, str) else (required.get("id"), required.get("version", ""))
        if name:
            manifest.dependencies.append(Dependency(name.lower(), "plugin", constraint, "semver", "runtime"))
    if document.get("framework_api"):
        manifest.contracts.append({"contract": PLUGIN_API_CONTRACT, "constraint": f">={document['framework_api']}", "syntax": "semver"})
    return manifest


def parse_chart_yaml(file: str, text: str) -> ParsedManifest:
    document = yaml.safe_load(text) or {}
    manifest = ParsedManifest(file, "helm", (document.get("name") or "").lower() or None, str(document["version"]) if document.get("version") else None)
    for dependency in document.get("dependencies") or []:
        if dependency.get("name"):
            manifest.dependencies.append(Dependency(dependency["name"].lower(), "helm", str(dependency.get("version") or ""), "semver", "runtime"))
    return manifest


def parse_version_file(file: str, text: str) -> ParsedManifest:
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    try:
        parse_version(first_line)
        version = first_line.lstrip("vV")
    except ConstraintError:
        version = None
    return ParsedManifest(file, "version", None, version)


MANIFEST_PARSERS = {
    "pyproject.toml": parse_pyproject,
    "package.json": parse_package_json,
    "plugin.json": parse_plugin_json,
    "Chart.yaml": parse_chart_yaml,
    "VERSION": parse_version_file,
}


def parse_manifests(files: dict[str, str]) -> tuple[list[ParsedManifest], list[dict]]:
    parsed: list[ParsedManifest] = []
    problems: list[dict] = []
    for path in sorted(files, key=lambda candidate: (candidate.count("/"), candidate)):
        filename = path.rsplit("/", 1)[-1]
        parser = MANIFEST_PARSERS.get(filename)
        if not parser:
            continue
        try:
            parsed.append(parser(path, files[path]))
        except Exception as error:
            problems.append({"file": path, "error": str(error)[:200]})
    return parsed, problems
