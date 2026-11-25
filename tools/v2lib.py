"""Shared helpers for the Second Brain v2 -> Viber importers (stories, tasks, sprints). Standard library only.

Run inside a throwaway container with E:\\MyWorx mounted read-only at /work, for example:
  docker run --rm -v E:\\MyWorx:/work:ro python:3.12-slim python /work/Viber/tools/import_v2_stories.py [--apply]
Without --apply every script only does a dry run (nothing is written).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

ROOT = os.environ.get("V2_ROOT", "/work/second_brain_os/second_brain/Implementation")
API = os.environ.get("VIBER_URL", "http://host.docker.internal:8088")
ENV_FILE = os.environ.get("VIBER_ENV", "/work/Viber/.env")
PROJECT = "sbos"
APPLY = "--apply" in sys.argv
TEMPLATES = {"story-template", "task-template", "sprint-template", "user-story-template"}

_token = None


def token() -> str:
    global _token
    if _token is None:
        _token = ""
        with open(ENV_FILE, encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VIBER_TOKEN="):
                    _token = line.split("=", 1)[1].strip().strip('"').strip("'")
    return _token


def call(method: str, path: str, body=None, retries: int = 4):
    """Returns (status, parsed json or text). Never raises on an HTTP error status."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(API + path, data=data, method=method, headers={
        "Authorization": "Bearer " + token(), "X-Viber-Actor": "import-stories", "Content-Type": "application/json"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                text = response.read().decode("utf-8")
                return response.status, (json.loads(text) if text else None)
        except urllib.error.HTTPError as error:
            text = error.read().decode("utf-8", "replace")
            try:
                return error.code, json.loads(text)
            except ValueError:
                return error.code, text
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


# ---- reading the markdown -------------------------------------------------------------------------

def _value(raw: str):
    raw = raw.strip()
    if raw.startswith('"'):
        match = re.match(r'"((?:[^"\\]|\\.)*)"', raw)
        if match:
            try:
                return json.loads('"' + match.group(1) + '"')
            except ValueError:
                return match.group(1)
    if raw.startswith("'"):
        match = re.match(r"'((?:[^']|'')*)'", raw)
        if match:
            return match.group(1).replace("''", "'")
    raw = re.sub(r"\s+#.*$", "", raw).strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [part.strip().strip("\"'") for part in raw[1:-1].split(",") if part.strip()]
    return raw


def read_file(folder: str, name: str):
    with open(os.path.join(ROOT, folder, name), encoding="utf-8") as handle:
        text = handle.read().replace("\r\n", "\n").replace("\r", "\n")
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    meta, body = {}, text
    if match:
        for line in match.group(1).splitlines():
            found = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
            if found:
                meta[found.group(1)] = _value(found.group(2))
        body = text[match.end():]
    return meta, body.strip("\n")


def list_files(folder: str):
    """(real files, templates) as sorted name lists."""
    names = sorted(n for n in os.listdir(os.path.join(ROOT, folder)) if os.path.isfile(os.path.join(ROOT, folder, n)))
    real = [n for n in names if os.path.splitext(n)[0] not in TEMPLATES]
    return real, [n for n in names if n not in real]


def sections(body: str):
    """Split a markdown body into (heading line or '', text) at level-2 headings, fences respected."""
    parts, heading, buffer, fenced = [], "", [], False
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            parts.append((heading, "\n".join(buffer)))
            heading, buffer = line, []
        else:
            buffer.append(line)
    parts.append((heading, "\n".join(buffer)))
    return parts


_RULE = re.compile(r"^\s*(?:[-*_]{3,}|\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)*\|?)\s*$")


def to_details(text: str) -> str:
    """Make every source line its own statement for the server's splitter, dropping only pure formatting lines
    (horizontal rules, table divider rows, bare code-fence markers). Everything else is kept as written."""
    out, fenced = [], False
    for line in text.split("\n"):
        stripped = line.strip()
        if re.fullmatch(r"```[\w+-]*", stripped):
            fenced = not fenced
            out.append("")
            continue
        if not stripped or _RULE.match(stripped):
            out.append("")
        elif fenced or stripped.startswith(("|", "#", "<!--")):
            out.extend(["", stripped, ""])  # code lines, table rows, headings and comments stand alone
        else:
            out.append(line.rstrip())  # prose lines of one paragraph stay together; bullets split by the server
    return "\n".join(out)


def one_line(text: str, limit: int) -> str:
    text = " ".join(re.sub(r"[*_`]", "", text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def first_paragraph(text: str) -> str:
    for block in re.split(r"\n\s*\n", text.strip()):
        block = block.strip()
        if block and not block.startswith(("<!--", "|", "```", "#")):
            return " ".join(block.split())
    return ""


def story_status(value: str) -> str:
    return {"Done": "Done", "Cancelled": "Dropped", "Draft": "Open", "Ready": "Open", "In Progress": "In Progress",
            "Blocked": "Blocked"}.get((value or "").strip(), (value or "Open").strip() or "Open")


def plan_status(value: str) -> str:
    return {"Done": "Done", "Cancelled": "Dropped", "Draft": "Draft", "Ready": "Draft", "In Progress": "Active",
            "Blocked": "Active"}.get((value or "").strip(), "Draft")


def date_or_none(value):
    return value if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) else None


def clean_data(**fields) -> dict:
    return {k: v for k, v in fields.items() if v not in (None, "", [])}


# ---- writing to Viber -----------------------------------------------------------------------------

def bulk_items(source: str, records: list, label: str):
    """Dry-run first, then (with --apply) write; batches by size. Returns totals and the invalid list."""
    totals = {"created": 0, "skipped": 0, "invalid": []}
    batches, current, size = [], [], 0
    for record in records:
        n = len(json.dumps(record))
        if current and (len(current) >= 150 or size + n > 2_500_000):
            batches.append(current)
            current, size = [], 0
        current.append(record)
        size += n
    if current:
        batches.append(current)
    offset = 0
    for batch in batches:
        status, result = call("POST", f"/v1/projects/{PROJECT}/import/items?dry_run=true", {"source": source, "records": batch})
        if status != 200:
            print(f"[{label}] dry run failed {status}: {str(result)[:300]}")
            sys.exit(2)
        bad = result["invalid"]
        if APPLY:
            status, result = call("POST", f"/v1/projects/{PROJECT}/import/items?dry_run=false", {"source": source, "records": batch})
            if status != 200:
                print(f"[{label}] import failed {status}: {str(result)[:300]}")
                sys.exit(2)
            bad = result["invalid"]
        for item in bad:
            totals["invalid"].append({"key": batch[item["index"]].get("key"), "error": item["error"]})
        totals["created"] += result["created"]
        totals["skipped"] += result["skipped"]
        offset += len(batch)
    print(f"[{label}] {'APPLIED' if APPLY else 'DRY RUN'}: {len(records)} records, created {totals['created']}, "
          f"already there {totals['skipped']}, invalid {len(totals['invalid'])}")
    for bad in totals["invalid"][:20]:
        print("   invalid:", bad)
    return totals


def post_ref(from_type, from_key, relation, to_type, to_key, source, source_ref, note=None):
    body = {"from_type": from_type, "from_key": from_key, "relation": relation, "to_type": to_type, "to_key": to_key,
            "source": source, "source_ref": source_ref}
    if note:
        body["note"] = note[:200]
    return call("POST", f"/v1/projects/{PROJECT}/refs", body)


def existing_keys(path: str, field: str = "key", params: str = "limit=500"):
    status, rows = call("GET", f"/v1/projects/{PROJECT}/{path}?{params}")
    return {r[field] for r in rows} if status == 200 and isinstance(rows, list) else set()


def all_items(kind: str):
    """Keys of every item of one kind (paged through the list endpoint when it supports it)."""
    keys, seen = set(), 0
    while True:
        status, rows = call("GET", f"/v1/projects/{PROJECT}/items?kind={kind}&limit=500&offset={seen}")
        if status != 200 or not isinstance(rows, list) or not rows:
            break
        before = len(keys)
        keys |= {r["key"] for r in rows}
        seen += len(rows)
        if len(keys) == before or len(rows) < 500:
            break
    return keys
