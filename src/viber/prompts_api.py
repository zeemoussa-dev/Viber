"""The prompt vault and the project resolver."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from . import prompts, service
from .db import transaction
from .security import require_token, visible_projects

router = APIRouter(dependencies=[Depends(require_token)])


class PromptIn(BaseModel):
    title: str = Field(max_length=120)
    purpose: str = Field("", max_length=200)
    text: str  # one line per statement; {project} and {component} are filled in when read


@router.get("/v1/projects/{project_key}/prompts")
def list_prompts(project_key: str):
    with transaction() as connection:
        return prompts.list_prompts(connection, service.project_row(connection, project_key))


@router.post("/v1/projects/{project_key}/prompts/seed", status_code=201)
def seed_prompts(project_key: str):
    """Add the default prompts to this project (the ones already there are left as they are)."""
    with transaction() as connection:
        return prompts.seed(connection, service.project_row(connection, project_key))


@router.get("/v1/projects/{project_key}/prompts/{key}", response_class=PlainTextResponse)
def read_prompt(project_key: str, key: str, component: str | None = None):
    """The prompt as plain text, ready to paste into a session."""
    with transaction() as connection:
        return prompts.render(connection, service.project_row(connection, project_key), key, component)


@router.put("/v1/projects/{project_key}/prompts/{key}")
def save_prompt(project_key: str, key: str, payload: PromptIn):
    with transaction() as connection:
        return prompts.save(connection, service.project_row(connection, project_key), key, payload.title, payload.purpose, payload.text)


@router.get("/v1/resolve")
def resolve(request: Request, repo: str | None = None, cwd: str | None = None):
    """Which project a session belongs to: by its repository (a component's repo), else by the folder it works in
    (a project's settings.workspaces). A project the caller's token may not see is never returned. Answers null when
    nothing matches, so a session in an unknown place gets no project's memory at all."""
    allowed = visible_projects(request)
    found, how = None, None
    with transaction() as connection:
        if repo:
            wanted = repo.strip().lower().removesuffix(".git")
            rows = connection.execute("SELECT DISTINCT p.key FROM component c JOIN project p ON p.id = c.project_id "
                                      "WHERE lower(c.repo) = %s OR lower(c.repo) = split_part(%s, '/', 2)", (wanted, wanted)).fetchall()
            keys = [r["key"] for r in rows if allowed is None or r["key"] in allowed]
            if len(keys) == 1:
                found, how = keys[0], "repo"
        if not found and cwd:
            here = cwd.replace("\\", "/").rstrip("/").lower()
            best = ("", None)
            for project in connection.execute("SELECT key, settings FROM project").fetchall():
                if allowed is not None and project["key"] not in allowed:
                    continue
                for folder in (project["settings"] or {}).get("workspaces", []):
                    prefix = folder.replace("\\", "/").rstrip("/").lower()
                    if (here == prefix or here.startswith(prefix + "/")) and len(prefix) > len(best[0]):
                        best = (prefix, project["key"])
            if best[1]:
                found, how = best[1], "workspace"
    return {"project": found, "how": how}
