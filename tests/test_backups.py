from datetime import datetime, timedelta, timezone

import pytest

from viber import backup
from viber.db import transaction


@pytest.fixture(autouse=True)
def folder(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBER_BACKUP_DIR", str(tmp_path))
    monkeypatch.setenv("VIBER_BACKUP_EVERY_HOURS", "24")
    with transaction() as connection:
        connection.execute("DELETE FROM backup_run")
    return tmp_path


def test_a_backup_is_made_restored_into_a_scratch_database_and_counted(client, project_key, folder):
    client.post(f"/v1/projects/{project_key}/memory/facts", json={"text": "Something worth keeping."})
    result = backup.run("test")
    assert result["status"] == "ok", result
    assert "every table's count matched" in result["note"]
    files = list(folder.glob("viber-*.dump"))
    assert len(files) == 1 and files[0].stat().st_size > 0 and not list(folder.glob("*.partial"))
    with transaction() as connection:
        row = connection.execute("SELECT * FROM backup_run").fetchone()
        scratch = connection.execute("SELECT 1 FROM pg_database WHERE datname = 'viber_verify'").fetchone()
    assert row["status"] == "ok" and row["counts_restored"]["fact"] >= 1 and row["sha256"] and row["verified_at"]
    assert scratch is None  # the scratch database is dropped afterwards


def test_a_damaged_backup_is_caught_and_never_counts_as_good(client, project_key, folder):
    assert backup.run("test")["status"] == "ok"
    path = next(folder.glob("viber-*.dump"))
    data = bytearray(path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    path.write_bytes(bytes(data))
    with transaction() as connection:
        run_id = connection.execute("SELECT id FROM backup_run").fetchone()["id"]
    again = backup.verify(run_id)
    assert again["status"] == "failed" and "checksum" in again["error"]
    health = backup.health()
    assert health["last_good"] is None and not health["healthy"]


def test_a_missing_file_makes_the_backups_unhealthy(client, project_key, folder):
    backup.run("test")
    assert backup.health()["healthy"]
    next(folder.glob("viber-*.dump")).unlink()
    health = backup.health()
    assert not health["healthy"] and health["files_missing"]


def test_health_says_plainly_when_there_is_no_checked_backup(client):
    health = backup.health()
    assert not health["healthy"] and health["good_backups"] == 0 and "no checked backup" in health["note"]


def test_retention_keeps_the_newest_per_day_week_and_month_and_always_the_newest():
    now = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
    times = [now - timedelta(hours=h) for h in (1, 5, 30, 31, 100, 24 * 12, 24 * 13, 24 * 50, 24 * 51, 24 * 400)]
    kept = backup.keep_set(times, now)
    assert 0 in kept                      # the newest
    assert 1 not in kept                  # a second one on the same day
    assert 2 in kept and 3 not in kept    # the newest of the day before, not the older that day
    assert 4 in kept                      # a different day within the week
    assert 9 not in kept                  # older than six months
    assert len(kept) < len(times)


def test_pruning_deletes_files_and_marks_rows_but_never_the_last_good_one(client, folder):
    old = datetime.now(timezone.utc) - timedelta(days=400)
    with transaction() as connection:
        for n, when in enumerate([datetime.now(timezone.utc), old, old - timedelta(hours=1)]):
            name = f"viber-test-{n}.dump"
            (folder / name).write_bytes(b"x")
            connection.execute("INSERT INTO backup_run (status, file, started_at) VALUES ('ok', %s, %s)", (name, when))
    assert backup.prune() == 2
    assert [p.name for p in folder.glob("viber-test-*.dump")] == ["viber-test-0.dump"]
    with transaction() as connection:
        assert connection.execute("SELECT count(*) AS n FROM backup_run WHERE status = 'pruned'").fetchone()["n"] == 2


def test_only_an_admin_may_run_or_download_a_backup_and_anyone_may_read_the_status(client, project_key, folder, monkeypatch):
    monkeypatch.setenv("VIBER_TOKEN", "master-secret")
    master = {"Authorization": "Bearer master-secret"}
    writer = {"Authorization": "Bearer " + client.post("/v1/tokens", json={"name": "bk-writer", "role": "write"}, headers=master).json()["token"]}
    reader = {"Authorization": "Bearer " + client.post("/v1/tokens", json={"name": "bk-reader", "role": "read"}, headers=master).json()["token"]}
    assert client.get("/v1/backups", headers=reader).status_code == 200
    assert client.post("/v1/backups/run", headers=writer).status_code == 403
    assert client.get("/v1/backups/1/download", headers=reader).status_code == 403
    assert client.post("/v1/backups/run", headers=master).status_code == 202
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "viber_backup_status", "arguments": {"project": project_key}}}
    assert client.post("/mcp", json=body, headers=reader).status_code == 200
