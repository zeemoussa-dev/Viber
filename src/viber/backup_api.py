"""Backups: status, make one now, check one again, download one. Admin only, except reading the status."""
import threading

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from . import backup
from .db import transaction
from .security import require_token

router = APIRouter(prefix="/v1/backups", dependencies=[Depends(require_token)])


@router.get("")
def status():
    """Is there a checked backup, how old, how big, where, and the last runs."""
    return backup.health()


@router.post("/run", status_code=202)
def run_now():
    """Start a backup and its restore check in the background; poll GET /v1/backups for the result."""
    threading.Thread(target=backup.run, args=("manual",), name="viber-backup-now", daemon=True).start()
    return {"started": True, "note": "It takes a few seconds to a few minutes. Watch GET /v1/backups."}


@router.post("/{run_id}/verify", status_code=202)
def verify_again(run_id: int):
    with transaction() as connection:
        if not connection.execute("SELECT 1 FROM backup_run WHERE id = %s AND file IS NOT NULL", (run_id,)).fetchone():
            raise HTTPException(404, "no such backup with a file")
    threading.Thread(target=backup.verify, args=(run_id,), name="viber-backup-verify", daemon=True).start()
    return {"started": True}


@router.get("/{run_id}/download")
def download(run_id: int):
    """The dump file itself, to keep a copy somewhere else. It holds every project's data and the token hashes: guard it."""
    with transaction() as connection:
        row = connection.execute("SELECT file FROM backup_run WHERE id = %s AND file IS NOT NULL AND status IN ('ok', 'unverified')", (run_id,)).fetchone()
    path = backup.backup_dir() / row["file"] if row else None
    if not path or not path.exists():
        raise HTTPException(404, "no such backup file")
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")
