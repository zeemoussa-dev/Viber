from fastapi import APIRouter, Depends

from . import service, sessions
from .db import transaction
from .models import EndIn, HandoffIn, SessionStartIn, TouchIn
from .security import actor_name, require_token

router = APIRouter(prefix="/v1/projects/{project_key}", dependencies=[Depends(require_token)])


@router.post("/sessions/start")
def start_session(project_key: str, payload: SessionStartIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return sessions.start_session(connection, project, payload, actor)


@router.post("/sessions/{external_id}/touch")
def touch_file(project_key: str, external_id: str, payload: TouchIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return sessions.touch_file(connection, project, external_id, payload.path, payload.tool, actor)


@router.post("/sessions/{external_id}/heartbeat")
def heartbeat(project_key: str, external_id: str, state: str = "idle"):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return sessions.heartbeat(connection, project, external_id, state)


@router.post("/sessions/{external_id}/end")
def end_session(project_key: str, external_id: str, payload: EndIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return sessions.end_session(connection, project, external_id, payload.summary, actor)


@router.post("/sessions/{external_id}/handoff", status_code=201)
def handoff(project_key: str, external_id: str, payload: HandoffIn, actor: str = Depends(actor_name)):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return sessions.record_handoff(connection, project, external_id, payload, actor)


@router.get("/sessions")
def list_active_sessions(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return sessions.active_sessions(connection, project)


@router.get("/stats/sessions")
def session_stats(project_key: str):
    with transaction() as connection:
        project = service.project_row(connection, project_key)
        return sessions.session_stats(connection, project)
