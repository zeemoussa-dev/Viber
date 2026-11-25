"""Decide component boundaries from a repo's file list. Default: one component per repo."""
import re
from dataclasses import dataclass

VERSIONED_MANIFESTS = ("plugin.json", "pyproject.toml", "package.json", "Chart.yaml")
ROOT_ONLY_MANIFESTS = ("VERSION",)
ALL_MANIFESTS = VERSIONED_MANIFESTS + ROOT_ONLY_MANIFESTS
KIND_BY_MANIFEST = {"plugin.json": "plugin", "Chart.yaml": "chart"}
NOISE_DIRECTORY = re.compile(
    r"(^|/)(node_modules|vendor|tests?|fixtures?|fixture_[a-z_]+|examples?|samples?|templates?|demo[-_a-z]*|"
    r"docs?|\.venv|venv|build|dist|\.git[a-z]*)(/|$)", re.IGNORECASE)


@dataclass
class Proposal:
    key: str
    path: str
    kind: str
    manifests: list[str]


def directory_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def kind_for(filenames: set[str]) -> str:
    for manifest_name, kind in KIND_BY_MANIFEST.items():
        if manifest_name in filenames:
            return kind
    return "service"


def plan_components(repo: str, paths: list[str]) -> dict:
    candidates: dict[str, set[str]] = {}
    ignored: list[dict] = []
    for path in paths:
        filename = path.rsplit("/", 1)[-1]
        if filename not in ALL_MANIFESTS:
            continue
        directory = directory_of(path)
        if NOISE_DIRECTORY.search(path):
            ignored.append({"path": path, "reason": "test, vendor, template or build directory"})
        elif filename in ROOT_ONLY_MANIFESTS and directory:
            ignored.append({"path": path, "reason": f"{filename} is only read at the repo root"})
        else:
            candidates.setdefault(directory, set()).add(filename)

    proposals: list[Proposal] = []
    root_files = candidates.pop("", set())
    root_has_real_manifest = bool(root_files & set(VERSIONED_MANIFESTS))
    if root_files:
        proposals.append(Proposal(repo, "", kind_for(root_files), sorted(root_files)))
    if root_has_real_manifest:
        ignored += [{"path": f"{directory}/{name}", "reason": "repo has a root manifest: one component per repo"}
                    for directory, names in sorted(candidates.items()) for name in sorted(names)]
        candidates = {}
    leaf_counts: dict[str, int] = {}
    for directory in candidates:
        leaf_counts[directory.rsplit("/", 1)[-1]] = leaf_counts.get(directory.rsplit("/", 1)[-1], 0) + 1
    for directory, names in sorted(candidates.items()):
        leaf = directory.rsplit("/", 1)[-1]
        suffix = leaf if leaf_counts[leaf] == 1 else directory.replace("/", "-")
        proposals.append(Proposal(f"{repo}.{suffix}", directory, kind_for(names), sorted(names)))
    return {
        "components": [
            {"key": p.key, "path": p.path, "kind": p.kind,
             "manifests": [f"{p.path}/{name}" if p.path else name for name in p.manifests]}
            for p in proposals],
        "ignored": ignored,
    }
