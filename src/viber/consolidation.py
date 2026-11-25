"""Consolidation and reflection: turning what happened (episodes) into what is known (facts, proposed rules), and keeping
memory tidy. Part of Viber, with its own pluggable chat model; nothing depends on any other product.

Model-free, always available: duplicate detection by meaning (needs the embeddings) and superseding a fact.
Model-based, only when a chat model is configured (VIBER_LLM_PROVIDER = ollama | openai): proposing facts and rules
from new episodes, and a short reflection per component. The model only ever PROPOSES: facts it writes carry trust
'agent' and a source of 'consolidation', and every rule it suggests waits for a human to accept it. Its output is
parsed as data, checked against the same size limits as any other write, and anything malformed is dropped."""
import hashlib
import json
import os
import re
import urllib.request

from fastapi import HTTPException

from . import service
from .atoms import FACT_MAX, RULE_MAX
from .db import record_audit
from .models import FactIn, RuleIn

MAX_EPISODES = 40
DUPLICATE_THRESHOLD = 0.93


def llm_config() -> dict:
    return {"provider": os.environ.get("VIBER_LLM_PROVIDER", "none").lower(),
            "url": os.environ.get("VIBER_LLM_URL", "http://embeddings:11434").rstrip("/"),
            "model": os.environ.get("VIBER_LLM_MODEL", ""), "key": os.environ.get("VIBER_LLM_KEY", "")}


def llm_enabled() -> bool:
    c = llm_config()
    return c["provider"] in ("ollama", "openai", "fake") and (c["provider"] == "fake" or bool(c["model"]))


def _post(url: str, body: dict, key: str, timeout: float) -> dict:
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    if key:
        request.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _fake(prompt: str) -> str:
    """Test model: one fact per episode line, and a one-line reflection. Deterministic."""
    episodes = re.findall(r"^- \[[^\]]*\] (.+)$", prompt, re.M)
    if "REFLECT" in prompt:
        return json.dumps({"statements": [f"{len(episodes)} recent events touched this component."]})
    return json.dumps({"facts": [{"text": e.split(".")[0][:FACT_MAX]} for e in episodes[:5]],
                       "rules": [{"text": e[:RULE_MAX]} for e in episodes if e.lower().startswith("always ")]})


def complete(prompt: str, timeout: float = 120.0) -> str:
    c = llm_config()
    if c["provider"] == "fake":
        return _fake(prompt)
    messages = [{"role": "user", "content": prompt}]
    if c["provider"] == "ollama":
        return _post(f"{c['url']}/api/chat", {"model": c["model"], "messages": messages, "stream": False, "format": "json"}, c["key"], timeout)["message"]["content"]
    if c["provider"] == "openai":
        return _post(f"{c['url']}/v1/chat/completions", {"model": c["model"], "messages": messages,
                     "response_format": {"type": "json_object"}}, c["key"], timeout)["choices"][0]["message"]["content"]
    raise HTTPException(409, "no chat model is configured: set VIBER_LLM_PROVIDER, VIBER_LLM_MODEL (and VIBER_LLM_URL)")


def _json(reply: str) -> dict:
    try:
        data = json.loads(reply)
        return data if isinstance(data, dict) else {}
    except ValueError:
        match = re.search(r"\{.*\}", reply or "", re.S)
        try:
            return json.loads(match.group(0)) if match else {}
        except ValueError:
            return {}


# ---- model-free ---------------------------------------------------------------------------------------

def duplicates(connection, project: dict, threshold: float = DUPLICATE_THRESHOLD, limit: int = 50) -> list[dict]:
    """Pairs of live facts that mean nearly the same thing, by their vectors. The newer one usually supersedes the older."""
    from . import embeddings
    model = embeddings.config()["model"]
    return connection.execute(
        "SELECT fa.id::text AS older, fa.text AS older_text, fb.id::text AS newer, fb.text AS newer_text, "
        "round((1 - (a.embedding <=> b.embedding))::numeric, 3) AS similarity "
        "FROM memory_vector a JOIN memory_vector b ON b.project_id = a.project_id AND b.kind = 'fact' AND b.model = a.model AND b.ref <> a.ref "
        "JOIN fact fa ON fa.id::text = a.ref AND fa.valid_to IS NULL JOIN fact fb ON fb.id::text = b.ref AND fb.valid_to IS NULL "
        "WHERE a.project_id = %s AND a.kind = 'fact' AND a.model = %s AND a.embedding IS NOT NULL AND b.embedding IS NOT NULL "
        "AND (fa.created_at, fa.id) < (fb.created_at, fb.id) AND 1 - (a.embedding <=> b.embedding) >= %s ORDER BY similarity DESC LIMIT %s",
        (project["id"], model, threshold, limit)).fetchall()


def supersede(connection, project: dict, old_id: str, new_id: str, actor: str) -> dict:
    """End a fact in favour of another. The old one stays in the history, with a pointer to what replaced it."""
    rows = connection.execute("SELECT id::text AS id FROM fact WHERE project_id = %s AND id::text = ANY(%s) AND valid_to IS NULL",
                              (project["id"], [old_id, new_id])).fetchall()
    if len(rows) != 2 or old_id == new_id:
        raise HTTPException(404, "both facts must exist, differ, and still be live")
    connection.execute("UPDATE fact SET valid_to = now(), superseded_by = %s::uuid WHERE project_id = %s AND id::text = %s",
                       (new_id, project["id"], old_id))
    record_audit(connection, actor, "supersede", "fact", old_id, project["id"], {"by": new_id})
    return {"ended": old_id, "superseded_by": new_id}


# ---- done by the calling session (Claude Code is the model) -------------------------------------------
# The session reads what is new, decides what is durable, writes it with viber_remember, then marks the batch done.
# No second model is needed; the propose()/reflect() below are only for a setup that has one.

def pending_episodes(connection, project: dict, limit: int = MAX_EPISODES) -> dict:
    """The episodes since the last consolidation, for the session to read and turn into facts and proposed rules."""
    state = _state(connection, project)
    rows = connection.execute(
        "SELECT id::text AS id, kind, content, occurred_at FROM episode WHERE project_id = %s AND (%s::timestamptz IS NULL OR occurred_at > %s) "
        "ORDER BY occurred_at LIMIT %s", (project["id"], state["last_episode_at"], state["last_episode_at"], limit)).fetchall()
    return {"episodes": rows, "since": state["last_episode_at"]}


def mark_consolidated(connection, project: dict, through_episode_id: str, actor: str) -> dict:
    """Move the watermark to the given episode, so the next batch starts after it."""
    row = connection.execute("SELECT occurred_at FROM episode WHERE project_id = %s AND id::text = %s", (project["id"], through_episode_id)).fetchone()
    if not row:
        raise HTTPException(404, "no such episode")
    _state(connection, project)
    connection.execute("UPDATE consolidation_state SET last_episode_at = greatest(coalesce(last_episode_at, %s), %s), last_run_at = now() WHERE project_id = %s",
                       (row["occurred_at"], row["occurred_at"], project["id"]))
    record_audit(connection, actor, "consolidate", "project", project["key"], project["id"], {"through": through_episode_id})
    return {"through": through_episode_id}


def component_digest(connection, project: dict, component_key: str) -> dict:
    """Everything recent about one component, for the session to write a current summary of."""
    service.component_id(connection, project["id"], component_key)
    return {
        "changes": [r["summary"] for r in connection.execute(
            "SELECT c.summary FROM change c JOIN component k ON k.id = c.component_id WHERE c.project_id = %s AND k.key = %s "
            "ORDER BY c.occurred_on DESC LIMIT 15", (project["id"], component_key)).fetchall()],
        "items": [f"{r['key']} [{r['status']}] {r['title']}" for r in connection.execute(
            "SELECT i.key, i.title, i.status FROM item i JOIN item_component ic ON ic.item_id = i.id JOIN component k ON k.id = ic.component_id "
            "WHERE i.project_id = %s AND k.key = %s ORDER BY i.created_at DESC LIMIT 15", (project["id"], component_key)).fetchall()],
        "facts": [r["text"] for r in connection.execute(
            "SELECT text FROM fact WHERE project_id = %s AND scope = %s AND valid_to IS NULL AND coalesce(subject,'') NOT LIKE 'reflection:%%' "
            "ORDER BY created_at DESC LIMIT 10", (project["id"], f"component:{component_key}")).fetchall()],
        "current_reflection": [r["text"] for r in connection.execute(
            "SELECT text FROM fact WHERE project_id = %s AND subject = %s AND valid_to IS NULL", (project["id"], f"reflection:{component_key}")).fetchall()],
    }


def write_reflection(connection, project: dict, component_key: str, statements: list[str], actor: str) -> dict:
    """Store the session's summary of a component; it replaces the previous one."""
    service.component_id(connection, project["id"], component_key)
    clean = [" ".join(str(s).split()) for s in statements][:5]
    bad = [s for s in clean if not s or len(s) > FACT_MAX or _looks_secret(s)]
    if bad or not clean:
        raise HTTPException(422, f"give 1 to 5 statements of at most {FACT_MAX} characters each, with no secrets")
    subject = f"reflection:{component_key}"
    connection.execute("UPDATE fact SET valid_to = now() WHERE project_id = %s AND subject = %s AND valid_to IS NULL", (project["id"], subject))
    for text in clean:
        service.create_fact(connection, project, FactIn(text=text, subject=subject, scope=f"component:{component_key}", trust="agent",
                                                         source="reflection", source_ref=hashlib.sha1((subject + text).encode()).hexdigest()[:20]), actor)
    return {"component": component_key, "statements": len(clean)}


# ---- model-based, only when a separate chat model is configured -----------------------------------------

def _state(connection, project: dict) -> dict:
    connection.execute("INSERT INTO consolidation_state (project_id) VALUES (%s) ON CONFLICT DO NOTHING", (project["id"],))
    return connection.execute("SELECT * FROM consolidation_state WHERE project_id = %s", (project["id"],)).fetchone()


def propose(connection, project: dict, actor: str = "consolidation") -> dict:
    """Read the episodes since the last run, ask the model what is now known, store facts and propose rules."""
    if not llm_enabled():
        raise HTTPException(409, "no chat model is configured: set VIBER_LLM_PROVIDER, VIBER_LLM_MODEL (and VIBER_LLM_URL)")
    state = _state(connection, project)
    episodes = connection.execute(
        "SELECT id::text AS id, kind, content, occurred_at FROM episode WHERE project_id = %s AND (%s::timestamptz IS NULL OR occurred_at > %s) "
        "ORDER BY occurred_at LIMIT %s", (project["id"], state["last_episode_at"], state["last_episode_at"], MAX_EPISODES)).fetchall()
    if not episodes:
        return {"episodes": 0, "facts": 0, "rules": 0, "note": "nothing new to consolidate"}
    prompt = ("You keep a project's memory. From the events below, list durable facts (things that stay true, one short "
              f"statement each, at most {FACT_MAX} characters) and any rules the events imply (a hard constraint, one sentence, "
              f"at most {RULE_MAX} characters). Do not repeat what is only a passing event. Reply as JSON: "
              '{"facts":[{"text":"..."}],"rules":[{"text":"..."}]}\nEvents:\n'
              + "\n".join(f"- [{e['kind']}] {' '.join(e['content'].split())[:400]}" for e in episodes))
    data = _json(complete(prompt))
    made = {"facts": 0, "rules": 0, "dropped": 0}
    for item in (data.get("facts") or [])[:20]:
        text = " ".join(str(item.get("text", "") if isinstance(item, dict) else item).split())
        if not text or len(text) > FACT_MAX or _looks_secret(text):
            made["dropped"] += 1
            continue
        _, created = service.create_fact(connection, project, FactIn(
            text=text, trust="agent", source="consolidation", source_ref=hashlib.sha1(text.lower().encode()).hexdigest()[:20]), actor)
        made["facts"] += int(created)
    for item in (data.get("rules") or [])[:10]:
        text = " ".join(str(item.get("text", "") if isinstance(item, dict) else item).split())
        if not text or len(text) > RULE_MAX or _looks_secret(text):
            made["dropped"] += 1
            continue
        _, created = service.create_rule(connection, project, RuleIn(
            text=text, proposed_by="consolidation", source="consolidation", source_ref=hashlib.sha1(text.lower().encode()).hexdigest()[:20]), actor)
        made["rules"] += int(created)
    connection.execute("UPDATE consolidation_state SET last_episode_at = %s, last_run_at = now(), last_error = NULL WHERE project_id = %s",
                       (episodes[-1]["occurred_at"], project["id"]))
    record_audit(connection, actor, "consolidate", "project", project["key"], project["id"], made)
    return {"episodes": len(episodes), **made}


def reflect(connection, project: dict, component_key: str, actor: str = "consolidation") -> dict:
    """A short, current summary of one component from its recent work; it replaces the previous reflection."""
    if not llm_enabled():
        raise HTTPException(409, "no chat model is configured: set VIBER_LLM_PROVIDER, VIBER_LLM_MODEL (and VIBER_LLM_URL)")
    service.component_id(connection, project["id"], component_key)
    lines = [f"- [change] {r['summary']}" for r in connection.execute(
        "SELECT c.summary FROM change c JOIN component k ON k.id = c.component_id WHERE c.project_id = %s AND k.key = %s "
        "ORDER BY c.occurred_on DESC LIMIT 15", (project["id"], component_key)).fetchall()]
    lines += [f"- [{r['status']}] {r['key']} {r['title']}" for r in connection.execute(
        "SELECT i.key, i.title, i.status FROM item i JOIN item_component ic ON ic.item_id = i.id JOIN component k ON k.id = ic.component_id "
        "WHERE i.project_id = %s AND k.key = %s ORDER BY i.created_at DESC LIMIT 15", (project["id"], component_key)).fetchall()]
    lines += [f"- [fact] {r['text']}" for r in connection.execute(
        "SELECT text FROM fact WHERE project_id = %s AND scope = %s AND valid_to IS NULL AND coalesce(subject,'') NOT LIKE 'reflection:%%' "
        "ORDER BY created_at DESC LIMIT 10", (project["id"], f"component:{component_key}")).fetchall()]
    if not lines:
        return {"component": component_key, "statements": 0, "note": "nothing recorded for this component yet"}
    prompt = (f"REFLECT. State what is currently true of the component '{component_key}' in at most 5 short statements "
              f"(each at most {FACT_MAX} characters), from the records below. Reply as JSON: {{\"statements\":[\"...\"]}}\n" + "\n".join(lines))
    statements = [" ".join(str(s).split()) for s in (_json(complete(prompt)).get("statements") or [])][:5]
    statements = [s for s in statements if s and len(s) <= FACT_MAX and not _looks_secret(s)]
    if not statements:
        return {"component": component_key, "statements": 0, "note": "the model gave nothing usable"}
    subject = f"reflection:{component_key}"
    connection.execute("UPDATE fact SET valid_to = now() WHERE project_id = %s AND subject = %s AND valid_to IS NULL", (project["id"], subject))
    for text in statements:
        service.create_fact(connection, project, FactIn(text=text, subject=subject, scope=f"component:{component_key}", trust="agent",
                                                         source="reflection", source_ref=hashlib.sha1((subject + text).encode()).hexdigest()[:20]), actor)
    return {"component": component_key, "statements": len(statements)}


def _looks_secret(text: str) -> bool:
    from .embeddings import looks_like_secret
    return looks_like_secret(text)
