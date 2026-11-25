from datetime import date, datetime

from pydantic import BaseModel, Field


class ProjectIn(BaseModel):
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str
    settings: dict = {}


class ComponentIn(BaseModel):
    key: str
    kind: str = "service"
    repo: str | None = None
    path: str | None = None
    lifecycle: str = "active"
    meta: dict = {}
    aliases: list[str] = []  # "python:sbos-contracts" or "npm:@scope/pkg"; bare names mean python


class ScanIn(BaseModel):
    ref: str | None = None
    commit_sha: str | None = None
    is_tag: bool = False
    files: dict[str, str]


class DiscoverIn(BaseModel):
    repo: str
    paths: list[str]


class LinkIn(BaseModel):
    from_component: str
    to_component: str | None = None
    to_contract: str | None = None
    type: str = "depends_on"
    scope: str = "runtime"
    constraint: str = ""
    syntax: str = "semver"
    note: str = ""


class ContractIn(BaseModel):
    key: str
    kind: str = "api"
    notes: str = ""


class ContractVersionIn(BaseModel):
    semver: str
    spec_ref: str | None = None


class ProvideIn(BaseModel):
    contract: str
    semver: str


class ReleaseMemberIn(BaseModel):
    component: str
    version: str


class ReleaseIn(BaseModel):
    name: str
    notes: str = ""
    members: list[ReleaseMemberIn]


class ItemIn(BaseModel):
    kind: str
    title: str
    body: str = ""
    key: str | None = None
    status: str = "Open"
    lane: str = "quick"
    severity: str | None = None
    area: str | None = None
    gate: str = "clear"
    gate_reason: str | None = None
    found_on: date | None = None
    component_keys: list[str] = []
    data: dict = {}
    source: str | None = None
    source_ref: str | None = None


class ItemUpdate(BaseModel):
    status: str | None = None
    title: str | None = None
    body: str | None = None
    severity: str | None = None
    gate: str | None = None
    gate_reason: str | None = None


class DecisionIn(BaseModel):
    key: str
    title: str
    status: str = "Accepted"
    decided_on: date | None = None
    context: str = ""
    decision: str = ""
    alternatives: str = ""
    consequences: str = ""
    supersedes: str | None = None
    superseded_by: str | None = None
    data: dict = {}
    source: str | None = None
    source_ref: str | None = None


class ChangeIn(BaseModel):
    summary: str
    occurred_on: date
    kind: str = "change"
    body: str = ""
    version: str | None = None
    commit_sha: str | None = None
    component_key: str | None = None
    source: str | None = None
    source_ref: str | None = None


class EpisodeIn(BaseModel):
    content: str
    kind: str = "note"
    scope: str = "project"
    occurred_at: datetime | None = None
    source: str | None = None
    source_ref: str | None = None


class FactIn(BaseModel):
    text: str
    subject: str | None = None
    scope: str = "project"
    trust: str = "agent"
    valid_from: datetime | None = None
    source: str | None = None
    source_ref: str | None = None


class RuleIn(BaseModel):
    text: str
    category: str = "constraint"
    scope: str = "project"
    status: str = "proposed"
    proposed_by: str | None = None
    source: str | None = None
    source_ref: str | None = None


class ImportBatch(BaseModel):
    source: str
    records: list[dict]
