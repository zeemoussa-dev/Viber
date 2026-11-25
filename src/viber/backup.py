"""Backups of Viber's own database, checked by actually restoring them.

A backup is one `pg_dump` file in a folder that is visible on the host (`./backups`, so it survives losing the Docker
volume and can be copied anywhere). It is only trusted after a restore check: the file is restored into a scratch database,
the rows of the important tables are counted, and the counts must fall between what the live database held just before and
just after the dump. A backup that fails the check is marked failed and never counts as the last good one.

Vectors are not dumped (`memory_vector`): they are derived data and the embedding sync rebuilds them.
Retention keeps the newest backup of each of the last 7 days, 5 weeks and 6 months, and never the only good one."""
import hashlib
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse

import psycopg

from .db import transaction

COUNT_TABLES = ["project", "component", "version", "link", "contract", "release", "item", "item_point", "decision", "decision_point",
                "change", "change_point", "spec", "plan", "ref", "fact", "rule", "episode", "entity", "edge", "fact_entity", "session",
                "prompt", "prompt_line", "api_token"]
SCRATCH = "viber_verify"
KEEP_DAYS, KEEP_WEEKS, KEEP_MONTHS = 7, 5, 6
_lock = threading.Lock()


def backup_dir() -> Path:
    return Path(os.environ.get("VIBER_BACKUP_DIR", "/backups"))


def every_hours() -> float:
    return float(os.environ.get("VIBER_BACKUP_EVERY_HOURS", "24"))


def _target() -> dict:
    u = urlparse(os.environ["VIBER_DATABASE_URL"])
    return {"host": u.hostname, "port": str(u.port or 5432), "user": unquote(u.username or ""), "password": unquote(u.password or ""),
            "dbname": u.path.lstrip("/")}


def _env(t: dict) -> dict:
    return {**os.environ, "PGPASSWORD": t["password"]}


def _tool(name: str, t: dict, *args: str, timeout: int = 1800) -> None:
    done = subprocess.run([name, "-h", t["host"], "-p", t["port"], "-U", t["user"], *args], env=_env(t), capture_output=True, text=True, timeout=timeout)
    if done.returncode != 0:
        raise RuntimeError(f"{name} failed: {(done.stderr or done.stdout).strip()[-300:]}")


def _counts(dsn: str) -> dict:
    with psycopg.connect(dsn, autocommit=True) as connection:
        return {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in COUNT_TABLES}


def _dsn(t: dict, dbname: str) -> str:
    return f"postgresql://{t['user']}:{t['password']}@{t['host']}:{t['port']}/{dbname}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _update(run_id: int, **fields) -> None:
    from psycopg.types.json import Jsonb
    columns = ", ".join(f"{k} = %s" for k in fields)
    values = [Jsonb(v) if isinstance(v, dict) else v for v in fields.values()]
    with transaction() as connection:
        connection.execute(f"UPDATE backup_run SET {columns} WHERE id = %s", [*values, run_id])


def run(trigger: str = "manual") -> dict:
    """Make a backup, then check it. Returns the finished row's summary."""
    if not _lock.acquire(blocking=False):
        return {"status": "already running"}
    try:
        t, directory = _target(), backup_dir()
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        final = directory / f"viber-{stamp}.dump"
        partial = directory / f"viber-{stamp}.dump.partial"
        with transaction() as connection:
            run_id = connection.execute("INSERT INTO backup_run (trigger) VALUES (%s) RETURNING id", (trigger,)).fetchone()["id"]
        try:
            live = _dsn(t, t["dbname"])
            before = _counts(live)
            _tool("pg_dump", t, "-d", t["dbname"], "-Fc", "--no-owner", "--exclude-table-data=memory_vector", "-f", str(partial))
            after = _counts(live)
            os.replace(partial, final)
            _update(run_id, file=final.name, bytes=final.stat().st_size, sha256=_sha256(final), counts_before=before, counts_after=after,
                    status="unverified", finished_at=datetime.now(timezone.utc))
        except Exception as failure:
            partial.unlink(missing_ok=True)
            _update(run_id, status="failed", error=str(failure)[:400], finished_at=datetime.now(timezone.utc))
            return {"id": run_id, "status": "failed", "error": str(failure)[:400]}
        result = _verify(run_id)
        prune()
        return result
    finally:
        _lock.release()


def verify(run_id: int) -> dict:
    """Check an existing backup again: its checksum, then a restore into a scratch database and a count."""
    if not _lock.acquire(blocking=False):
        return {"status": "already running"}
    try:
        return _verify(run_id)
    finally:
        _lock.release()


def _verify(run_id: int) -> dict:
    t = _target()
    with transaction() as connection:
        row = connection.execute("SELECT * FROM backup_run WHERE id = %s", (run_id,)).fetchone()
    if not row or not row["file"]:
        return {"id": run_id, "status": "failed", "error": "no such backup file"}
    path = backup_dir() / row["file"]
    if not path.exists():
        _update(run_id, status="failed", verify_note="the file is missing from the backup folder", verified_at=datetime.now(timezone.utc))
        return {"id": run_id, "status": "failed", "error": "file missing"}
    if _sha256(path) != row["sha256"]:
        _update(run_id, status="failed", verify_note="the file's checksum no longer matches: it has changed or is damaged", verified_at=datetime.now(timezone.utc))
        return {"id": run_id, "status": "failed", "error": "checksum mismatch"}
    admin = _dsn(t, "postgres")
    restored: dict | None = None
    note = ""
    try:
        with psycopg.connect(admin, autocommit=True) as connection:
            connection.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)')
            connection.execute(f'CREATE DATABASE "{SCRATCH}"')
        _tool("pg_restore", t, "-d", SCRATCH, "--no-owner", "--exit-on-error", str(path))
        restored = _counts(_dsn(t, SCRATCH))
        off = [f"{k}: restored {restored[k]}, expected {min(row['counts_before'][k], row['counts_after'][k])} to {max(row['counts_before'][k], row['counts_after'][k])}"
               for k in COUNT_TABLES if not (min(row["counts_before"][k], row["counts_after"][k]) <= restored[k] <= max(row["counts_before"][k], row["counts_after"][k]))]
        note = "restored into a scratch database and every table's count matched" if not off else "counts do not match: " + "; ".join(off)[:340]
        ok = not off
    except Exception as failure:
        ok, note = False, f"the restore check failed: {str(failure)[:340]}"
    finally:
        try:
            with psycopg.connect(admin, autocommit=True) as connection:
                connection.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}" WITH (FORCE)')
        except Exception:
            pass
    _update(run_id, status="ok" if ok else "failed", verify_note=note, verified_at=datetime.now(timezone.utc), counts_restored=restored)
    return {"id": run_id, "status": "ok" if ok else "failed", "note": note}


def keep_set(times: list[datetime], now: datetime) -> set[int]:
    """Which backups to keep, given their times newest first: the newest of each of the last 7 days, 5 weeks and 6 months.
    Returns indexes. The newest is always kept."""
    keep, days, weeks, months = set(), set(), set(), set()
    for index, when in enumerate(times):
        age = now - when
        day, week, month = when.date(), when.isocalendar()[:2], (when.year, when.month)
        if index == 0:
            keep.add(index)
        if age <= timedelta(days=KEEP_DAYS) and day not in days:
            days.add(day), keep.add(index)
        if age <= timedelta(weeks=KEEP_WEEKS) and week not in weeks:
            weeks.add(week), keep.add(index)
        if age <= timedelta(days=31 * KEEP_MONTHS) and month not in months:
            months.add(month), keep.add(index)
    return keep


def prune() -> int:
    """Delete the backups retention no longer needs. Only checked-good backups count towards what is kept, so a failed or
    unchecked one never pushes out a good one."""
    with transaction() as connection:
        good = connection.execute("SELECT id, file, started_at FROM backup_run WHERE status = 'ok' AND file IS NOT NULL ORDER BY started_at DESC").fetchall()
    if len(good) < 2:
        return 0
    keep = keep_set([g["started_at"] for g in good], datetime.now(timezone.utc))
    removed = 0
    for index, entry in enumerate(good):
        if index not in keep:
            (backup_dir() / entry["file"]).unlink(missing_ok=True)
            _update(entry["id"], status="pruned", file=None)
            removed += 1
    for stray in backup_dir().glob("*.partial"):
        if time.time() - stray.stat().st_mtime > 86400:
            stray.unlink(missing_ok=True)
    return removed


def health() -> dict:
    directory, hours = backup_dir(), every_hours()
    with transaction() as connection:
        runs = connection.execute("SELECT id, trigger, status, file, bytes, started_at, finished_at, verified_at, verify_note, error "
                                  "FROM backup_run WHERE status <> 'pruned' ORDER BY started_at DESC LIMIT 20").fetchall()
        last_ok = connection.execute("SELECT id, file, bytes, started_at, verified_at FROM backup_run WHERE status = 'ok' ORDER BY started_at DESC LIMIT 1").fetchone()
        count = connection.execute("SELECT count(*) AS n FROM backup_run WHERE status = 'ok'").fetchone()["n"]
    age = (datetime.now(timezone.utc) - last_ok["started_at"]).total_seconds() / 3600 if last_ok else None
    try:
        free = shutil.disk_usage(directory if directory.exists() else directory.parent).free
    except OSError:
        free = None
    missing = [r["file"] for r in runs if r["status"] == "ok" and r["file"] and not (directory / r["file"]).exists()]
    return {"folder": str(directory), "schedule_hours": hours, "good_backups": count, "last_good": last_ok, "last_good_age_hours": round(age, 1) if age is not None else None,
            "healthy": bool(last_ok) and not missing and (hours <= 0 or age <= hours * 1.5), "files_missing": missing, "disk_free_bytes": free, "runs": runs,
            "note": None if last_ok else "There is no checked backup yet."}


def start_scheduler(poll_s: float = 60.0) -> None:
    """Back up when the last good backup is older than the interval (so a machine that was off catches up at once)."""
    def loop():
        time.sleep(poll_s)
        while True:
            try:
                hours = every_hours()
                if hours > 0:
                    with transaction() as connection:
                        last = connection.execute("SELECT max(started_at) AS t FROM backup_run WHERE status = 'ok'").fetchone()["t"]
                        recent_fail = connection.execute("SELECT 1 FROM backup_run WHERE status = 'failed' AND started_at > now() - interval '30 minutes'").fetchone()
                    if (last is None or datetime.now(timezone.utc) - last > timedelta(hours=hours)) and not recent_fail:
                        run("scheduled")
            except Exception:
                pass
            time.sleep(poll_s)
    threading.Thread(target=loop, name="viber-backups", daemon=True).start()
