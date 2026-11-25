"""Shared helpers for the v2 importers (changelog, memory rules, learnings). Standard library only.

Run inside a throwaway container with E:\\MyWorx mounted read-only at /work:
    docker run --rm -e PYTHONDONTWRITEBYTECODE=1 -v E:\\MyWorx:/work:ro python:3.12-slim python /work/Viber/tools/<script>.py [--apply]
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

WORK = os.environ.get("WORK", "/work")
V2 = f"{WORK}/second_brain_os/second_brain"
VIBER_ENV = f"{WORK}/Viber/.env"
BASE = os.environ.get("VIBER_URL", "http://host.docker.internal:8088")
PROJECT = "sbos"

# The server's own splitter, loaded from its source so the limits and rules cannot drift.
_spec = importlib.util.spec_from_file_location("viber_atoms", f"{WORK}/Viber/src/viber/atoms.py")
atoms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(atoms)


def token() -> str:
    for line in open(VIBER_ENV, encoding="utf-8"):
        if line.startswith("VIBER_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("VIBER_TOKEN not found")


_TOKEN = None


def call(method: str, path: str, body=None, actor: str = "import-memory"):
    global _TOKEN
    _TOKEN = _TOKEN or token()
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, method=method, headers={
        "Authorization": f"Bearer {_TOKEN}", "X-Viber-Actor": actor, "Content-Type": "application/json; charset=utf-8"})
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                return json.loads(response.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{method} {path} -> {error.code}: {error.read().decode('utf-8', 'replace')[:500]}")
        except (urllib.error.URLError, ConnectionError, TimeoutError) as error:
            last = error
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{method} {path} unreachable: {last}")


def send(kind: str, source: str, records: list, apply: bool, max_records=100, max_bytes=350_000):
    """POST records in batches. Returns totals {created, skipped, invalid:[(record_index, error)]}."""
    totals = {"created": 0, "skipped": 0, "invalid": []}
    batch, size, start = [], 0, 0

    def flush(batch, start):
        if not batch:
            return
        path = f"/v1/projects/{PROJECT}/import/{kind}" + ("" if apply else "?dry_run=true")
        result = call("POST", path, {"source": source, "records": batch})
        totals["created"] += result["created"]
        totals["skipped"] += result["skipped"]
        totals["invalid"] += [(start + p["index"], p["error"]) for p in result["invalid"]]

    for index, record in enumerate(records):
        record_size = len(json.dumps(record, ensure_ascii=False).encode("utf-8"))
        if batch and (len(batch) >= max_records or size + record_size > max_bytes):
            flush(batch, start)
            batch, size, start = [], 0, index
        batch.append(record)
        size += record_size
    flush(batch, start)
    return totals


# --- text cleanup -------------------------------------------------------------------------------------------

_CP1252_HOLES = {0x81, 0x8D, 0x8F, 0x90, 0x9D}
_RUN = re.compile(r"[^\x00-\x7f]+")


def _unmojibake(run: str) -> str:
    out = bytearray()
    for ch in run:
        try:
            out += ch.encode("cp1252")
        except UnicodeEncodeError:
            if ord(ch) < 256:
                out.append(ord(ch))
            else:
                return run
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return run


def fix_text(text: str) -> str:
    """Repair UTF-8 text that was decoded as Windows-1252 once or twice (the v2 files carry such runs)."""
    text = text.replace("\u00e2\u20ac\ufffd\u009d", "\u2014")
    for _ in range(3):
        fixed = _RUN.sub(lambda m: _unmojibake(m.group(0)), text)
        if fixed == text:
            break
        text = fixed
    return text


def has_mojibake(text: str) -> bool:
    return bool(re.search(r"\u00e2\u20ac|\u00c3[\u00a2\u0082\u0083]|\ufffd|\u00e2\u2020", text))


def short_hash(text: str, length: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:length]


def read_lines(relative: str) -> list[str]:
    with open(f"{V2}/{relative}", encoding="utf-8", newline="") as handle:
        return [fix_text(line) for line in handle.read().replace("\r\n", "\n").replace("\r", "\n").split("\n")]


# --- markdown blocks ----------------------------------------------------------------------------------------

BULLET = re.compile(r"^(\s*)[-*]\s+(.*)$")
NUMBERED = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


def plain(text: str) -> str:
    """Drop bold/italic markers and collapse spaces; backticks and wording stay."""
    text = text.replace("**", "")
    return re.sub(r"\s+", " ", text).strip()


def cells(row: str) -> list[str]:
    row = row.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|"):
        row = row[:-1]
    return [c.strip() for c in row.split("|")]


def parse_blocks(lines: list[str]):
    """Split a markdown file into statements. Returns (blocks, skipped) where a block is
    {kind: bullet|numbered|paragraph|table|code, text, start, end (1-based lines), path: [heading, ...], level}
    and skipped is [(line_no, reason, text)] for every non-blank line that is not a statement: headings,
    table separators, HTML comment lines. Every other non-blank line is inside exactly one block."""
    blocks, skipped = [], []
    path: list[tuple[int, str]] = []
    current = None
    table_header = None
    in_fence = False
    in_comment = False

    def close():
        nonlocal current
        if current:
            current["text"] = plain(" ".join(current.pop("parts")))
            blocks.append(current)
        current = None

    def open_block(kind, text, number, level=0):
        nonlocal current
        close()
        current = {"kind": kind, "parts": [text], "start": number, "end": number, "path": [h for _, h in path], "level": level}

    for number, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if in_comment:
            skipped.append((number, "html-comment", stripped))
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith("<!--"):
            close()
            skipped.append((number, "html-comment", stripped))
            if "-->" not in stripped:
                in_comment = True
            continue
        if stripped.startswith("```"):
            if in_fence:
                in_fence = False
                if current:
                    current["end"] = number
                close()
            else:
                close()
                in_fence = True
                open_block("code", "", number)
                current["parts"] = []
            continue
        if in_fence:
            if stripped:
                current["parts"].append(stripped)
                current["end"] = number
            continue
        if not stripped:
            close()
            table_header = None
            continue
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            close()
            table_header = None
            skipped.append((number, "horizontal-rule", stripped))
            continue
        heading = HEADING.match(line)
        if heading:
            close()
            table_header = None
            level = len(heading.group(1))
            path = [(lv, h) for lv, h in path if lv < level] + [(level, plain(heading.group(2)))]
            skipped.append((number, "heading", stripped))
            continue
        if stripped.startswith("|"):
            if TABLE_SEP.match(stripped):
                skipped.append((number, "table-separator", stripped))
                continue
            row = cells(stripped)
            if table_header is None:
                close()
                table_header = [plain(c) for c in row]
                skipped.append((number, "table-header", stripped))
                continue
            close()
            pairs = [f"{table_header[i] if i < len(table_header) and table_header[i] else 'column ' + str(i + 1)}: {plain(c)}"
                     for i, c in enumerate(row) if plain(c)]
            open_block("table", "; ".join(pairs), number)
            current["parts"] = ["; ".join(pairs)]
            close()
            continue
        table_header = None
        bullet = BULLET.match(line)
        if bullet:
            open_block("bullet", bullet.group(2), number, level=len(bullet.group(1)))
            continue
        numbered = NUMBERED.match(line)
        if numbered:
            open_block("numbered", numbered.group(2), number, level=len(numbered.group(1)))
            continue
        if stripped.startswith(">"):
            stripped = stripped.lstrip("> ").strip()
            if not stripped:
                skipped.append((number, "empty-quote", line))
                continue
        if current and current["kind"] in ("bullet", "numbered", "paragraph"):
            current["parts"].append(stripped)
            current["end"] = number
        else:
            open_block("paragraph", stripped, number)
    close()
    return blocks, skipped


def coverage(lines, blocks, skipped):
    """Non-blank lines that no block and no skip entry accounts for."""
    covered = set()
    for block in blocks:
        covered.update(range(block["start"], block["end"] + 1))
    covered.update(n for n, _, _ in skipped)
    return [n for n, line in enumerate(lines, start=1) if line.strip() and n not in covered]
