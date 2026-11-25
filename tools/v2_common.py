"""Shared helpers for the v2 ledger importers (standard library only).

Run inside a throwaway container with E:\\MyWorx mounted at /work (read-only):
  docker run --rm -v E:\\MyWorx:/work:ro python:3.12-slim python /work/Viber/tools/import_v2_adr.py
Environment: VIBER_URL (default http://host.docker.internal:8088), MODE=dry|apply|verify (default dry).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

WORK = os.environ.get("WORK_DIR", "/work")
V2 = os.path.join(WORK, "second_brain_os", "second_brain")
BASE = os.environ.get("VIBER_URL", "http://host.docker.internal:8088")
PROJECT = "sbos"
ACTOR = "import-ledgers"
MODE = os.environ.get("MODE", "dry")  # dry | apply | verify


def token() -> str:
    with open(os.path.join(WORK, "Viber", ".env"), encoding="utf-8") as handle:
        for line in handle:
            if line.startswith("VIBER_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("VIBER_TOKEN not found in Viber/.env")


TOKEN = token()


def call(method: str, path: str, body=None, ok_404=False):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": "Bearer " + TOKEN, "X-Viber-Actor": ACTOR, "Content-Type": "application/json; charset=utf-8"})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, json.loads(response.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        try:
            payload = json.loads(text)
        except ValueError:
            payload = {"detail": text[:300]}
        if error.code == 404 and ok_404:
            return 404, payload
        return error.code, payload


def read_text(relative: str) -> str:
    with open(os.path.join(V2, relative), encoding="utf-8") as handle:
        return handle.read()


def fix_mojibake(text: str) -> str:
    """Some v2 files were saved through a wrong code page (UTF-8 read as cp1252). Undo it only if clearly present."""
    if "â€" in text or "Â·" in text:
        try:
            return text.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return text


def import_batches(kind: str, source: str, records: list, size: int = 20, dry: bool | None = None) -> dict:
    """POST records to the bulk importer in batches. Returns totals and every invalid record with its index."""
    dry = (MODE != "apply") if dry is None else dry
    totals = {"sent": 0, "created": 0, "skipped": 0, "invalid": []}
    for start in range(0, len(records), size):
        chunk = records[start:start + size]
        status, answer = call("POST", f"/v1/projects/{PROJECT}/import/{kind}?dry_run={'true' if dry else 'false'}",
                              {"source": source, "records": chunk})
        if status >= 300:
            raise SystemExit(f"import {kind} failed at batch {start}: HTTP {status} {answer}")
        totals["sent"] += len(chunk)
        totals["created"] += answer["created"]
        totals["skipped"] += answer["skipped"]
        for problem in answer["invalid"]:
            problem = dict(problem)
            problem["record"] = chunk[problem["index"]].get("key") or chunk[problem["index"]].get("source_ref")
            problem["index"] += start
            totals["invalid"].append(problem)
    return totals


def list_items(limit: int = 1000) -> list:
    rows, offset = [], 0
    while True:
        status, page = call("GET", f"/v1/projects/{PROJECT}/items?limit={limit}&offset={offset}")
        if status != 200:
            raise SystemExit(f"list items failed {status} {page}")
        rows += page
        if len(page) < limit:
            return rows
        offset += limit


def say(*parts):
    print(*parts)
    sys.stdout.flush()
