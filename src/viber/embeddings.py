"""Meaning search for Viber's memory, shipped with Viber: its own embedding service, vectors kept in Postgres
(pgvector), and a sync that fills in whatever is missing. Nothing here depends on any other product.

Design rules (shared with Second Brain's memory and the recall-engine ADRs):
 - the provider is pluggable: ollama, openai (any OpenAI-compatible endpoint), or none (keyword recall only, said plainly);
 - every vector records its model, and a query only ever uses vectors of the configured model;
 - a write never waits for an embedding: the sync finds what is missing or changed and fills it in, and a dead
   service costs one timeout and then a back-off, with recall falling back to keyword search;
 - text that looks like a secret is never sent out: it is marked withheld and stays keyword-searchable;
 - vectors are derived data, rebuildable from the rows at any time."""
import hashlib
import json
import math
import os
import re
import threading
import time
import urllib.request

from .db import transaction

DEFAULT_URL = "http://embeddings:11434"
DEFAULT_MODEL = "bge-m3"
BATCH = 16
RECALL_TIMEOUT_S = 3.0
SYNC_TIMEOUT_S = 30.0
RETRY_AFTER_S = 60.0
_failed_at = 0.0
_lock = threading.Lock()

SECRET_PATTERNS = [re.compile(p) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----", r"\bAKIA[0-9A-Z]{16}\b", r"\bsk-[A-Za-z0-9_-]{20,}\b", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b",
    r"\bxox[abp]-[A-Za-z0-9-]{10,}\b", r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*\S{8,}",
)]


def config() -> dict:
    provider = os.environ.get("VIBER_EMBED_PROVIDER", "ollama").lower()
    return {"provider": provider, "url": os.environ.get("VIBER_EMBED_URL", DEFAULT_URL).rstrip("/"),
            "model": os.environ.get("VIBER_EMBED_MODEL", DEFAULT_MODEL), "key": os.environ.get("VIBER_EMBED_KEY", ""),
            "min_score": float(os.environ.get("VIBER_EMBED_MIN_SCORE", "0.30"))}


def enabled() -> bool:
    return config()["provider"] not in ("", "none")


def looks_like_secret(text: str) -> bool:
    return any(p.search(text) for p in SECRET_PATTERNS)


def _post(url: str, body: dict, key: str, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _fake(text: str) -> list[float]:
    """Test provider: words hashed into 64 buckets. Deterministic, and overlapping words give similar vectors."""
    vector = [0.0] * 64
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 64] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def embed(texts: list[str], timeout: float) -> list[list[float]]:
    c = config()
    if c["provider"] == "fake":
        return [_fake(t) for t in texts]
    if c["provider"] == "ollama":
        return _post(f"{c['url']}/api/embed", {"model": c["model"], "input": texts}, c["key"], timeout)["embeddings"]
    if c["provider"] == "openai":
        data = _post(f"{c['url']}/v1/embeddings", {"model": c["model"], "input": texts}, c["key"], timeout)["data"]
        return [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
    raise RuntimeError(f"unknown embedding provider '{c['provider']}'")


def literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.7g}" for v in vector) + "]"


def _record(model: str, provider: str, error: str | None) -> None:
    with transaction() as connection:
        if error is None:
            connection.execute("INSERT INTO embedding_state (model, provider, last_ok_at, failures) VALUES (%s,%s,now(),0) "
                               "ON CONFLICT (model) DO UPDATE SET last_ok_at = now(), failures = 0, provider = EXCLUDED.provider", (model, provider))
        else:
            connection.execute("INSERT INTO embedding_state (model, provider, last_error, last_error_at, failures) VALUES (%s,%s,%s,now(),1) "
                               "ON CONFLICT (model) DO UPDATE SET last_error = EXCLUDED.last_error, last_error_at = now(), "
                               "failures = embedding_state.failures + 1, provider = EXCLUDED.provider", (model, provider, error[:300]))


PENDING_SQL = ("FROM memory_embeddable e LEFT JOIN memory_vector v ON v.project_id = e.project_id AND v.kind = e.kind "
               "AND v.ref = e.ref AND v.model = %s WHERE v.id IS NULL OR v.content_hash <> md5(e.content)")


def sync(limit: int = 64) -> dict:
    """Embed what is missing or changed, drop vectors whose source is gone. Safe to run at any time, by anyone."""
    global _failed_at
    c = config()
    if not enabled():
        return {"provider": "none", "embedded": 0, "pending": 0, "note": "no embedding provider: recall is keyword only"}
    if not _lock.acquire(blocking=False):
        return {"provider": c["provider"], "embedded": 0, "note": "a sync is already running"}
    try:
        with transaction() as connection:
            connection.execute("DELETE FROM memory_vector v WHERE v.model = %s AND NOT EXISTS (SELECT 1 FROM memory_embeddable e "
                               "WHERE e.project_id = v.project_id AND e.kind = v.kind AND e.ref = v.ref)", (c["model"],))
            rows = connection.execute(f"SELECT e.project_id, e.kind, e.ref, e.content, md5(e.content) AS h {PENDING_SQL} LIMIT %s",
                                      (c["model"], limit)).fetchall()
        embedded = withheld = 0
        todo = []
        for row in rows:
            if looks_like_secret(row["content"]):
                with transaction() as connection:
                    connection.execute(
                        "INSERT INTO memory_vector (project_id, kind, ref, model, content_hash, withheld) VALUES (%s,%s,%s,%s,%s,true) "
                        "ON CONFLICT (project_id, kind, ref, model) DO UPDATE SET content_hash = EXCLUDED.content_hash, embedding = NULL, withheld = true",
                        (row["project_id"], row["kind"], row["ref"], c["model"], row["h"]))
                withheld += 1
            else:
                todo.append(row)
        for start in range(0, len(todo), BATCH):
            chunk = todo[start:start + BATCH]
            try:
                vectors = embed([r["content"][:2000] for r in chunk], SYNC_TIMEOUT_S)
            except Exception as failure:
                _failed_at = time.monotonic()
                _record(c["model"], c["provider"], f"{type(failure).__name__}: {failure}")
                return {"provider": c["provider"], "model": c["model"], "embedded": embedded, "withheld": withheld,
                        "error": f"{type(failure).__name__}: {failure}", "note": "embedding service unavailable; recall uses keyword search"}
            with transaction() as connection:
                for row, vector in zip(chunk, vectors):
                    connection.execute(
                        "INSERT INTO memory_vector (project_id, kind, ref, model, dims, content_hash, embedding, withheld) VALUES (%s,%s,%s,%s,%s,%s,%s::vector,false) "
                        "ON CONFLICT (project_id, kind, ref, model) DO UPDATE SET dims = EXCLUDED.dims, content_hash = EXCLUDED.content_hash, "
                        "embedding = EXCLUDED.embedding, withheld = false",
                        (row["project_id"], row["kind"], row["ref"], c["model"], len(vector), row["h"], literal(vector)))
            embedded += len(chunk)
        _failed_at = 0.0
        if embedded or not rows:
            _record(c["model"], c["provider"], None)
        return {"provider": c["provider"], "model": c["model"], "embedded": embedded, "withheld": withheld}
    finally:
        _lock.release()


def vector_hits(connection, project: dict, query: str, limit: int) -> list[dict] | None:
    """Nearest rows by meaning, or None when meaning search is not available right now (the caller uses keywords only)."""
    global _failed_at
    c = config()
    if not enabled() or (_failed_at and time.monotonic() - _failed_at < RETRY_AFTER_S):
        return None
    have = connection.execute("SELECT 1 FROM memory_vector WHERE project_id = %s AND model = %s AND embedding IS NOT NULL LIMIT 1",
                              (project["id"], c["model"])).fetchone()
    if not have:
        return None
    try:
        vector = literal(embed([query[:2000]], RECALL_TIMEOUT_S)[0])
    except Exception:
        _failed_at = time.monotonic()
        return None
    return connection.execute(
        "SELECT e.kind, e.rid AS id, e.content, 1 - (v.embedding <=> %s::vector) AS score FROM memory_vector v "
        "JOIN memory_embeddable e ON e.project_id = v.project_id AND e.kind = v.kind AND e.ref = v.ref "
        "WHERE v.project_id = %s AND v.model = %s AND v.embedding IS NOT NULL AND 1 - (v.embedding <=> %s::vector) >= %s "
        "ORDER BY v.embedding <=> %s::vector LIMIT %s",
        (vector, project["id"], c["model"], vector, c["min_score"], vector, limit)).fetchall()


def health() -> dict:
    c = config()
    out = {"provider": c["provider"], "model": c["model"], "url": c["url"] if c["provider"] in ("ollama", "openai") else None,
           "mode": "hybrid (keyword + meaning)" if enabled() else "keyword only"}
    with transaction() as connection:
        out["vectors"] = connection.execute("SELECT count(*) AS n FROM memory_vector WHERE model = %s AND embedding IS NOT NULL", (c["model"],)).fetchone()["n"]
        out["withheld"] = connection.execute("SELECT count(*) AS n FROM memory_vector WHERE model = %s AND withheld", (c["model"],)).fetchone()["n"]
        out["pending"] = connection.execute(f"SELECT count(*) AS n {PENDING_SQL}", (c["model"],)).fetchone()["n"] if enabled() else 0
        out["other_models"] = [r["model"] for r in connection.execute("SELECT DISTINCT model FROM memory_vector WHERE model <> %s", (c["model"],)).fetchall()]
        state = connection.execute("SELECT last_ok_at, last_error, last_error_at, failures FROM embedding_state WHERE model = %s", (c["model"],)).fetchone()
    out.update(state or {"last_ok_at": None, "last_error": None, "last_error_at": None, "failures": 0})
    out["healthy"] = enabled() and out["failures"] == 0 and out["pending"] == 0
    return out


def start_background_sync(interval_s: float = 20.0) -> None:
    """Keep vectors current without anyone asking. A failure is recorded and retried later, never raised."""
    def loop():
        while True:
            try:
                sync()
            except Exception:
                pass
            time.sleep(interval_s)
    threading.Thread(target=loop, name="viber-embedding-sync", daemon=True).start()
