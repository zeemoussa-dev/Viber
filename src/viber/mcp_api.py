"""MCP over HTTP (JSON-RPC, JSON responses). Claude Code connects with:
   claude mcp add --transport http viber http://localhost:8088/mcp
The tools are thin wrappers over the same service functions the REST API uses."""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import __version__, adr, graph, service, sessions, specs
from .atoms import FACT_MAX, RULE_MAX
from .db import record_audit, transaction
from .models import ChangeIn, DecisionIn, FactIn, HandoffIn, ItemIn, RuleIn
from .security import require_token

router = APIRouter(dependencies=[Depends(require_token)])
ACTOR = "mcp"
DEFAULT_PROTOCOL_VERSION = "2025-03-26"
INSTRUCTIONS = ("Viber is the shared project memory. Search with viber_recall before re-deriving anything, "
                "log small work with viber_quick, and call viber_handoff before finishing or forking.")

PROJECT = {"type": "string", "description": "Viber project key (given in the session context)"}


def tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": {"project": PROJECT, **properties}, "required": ["project", *required]}}


TOOLS = [
    tool("viber_recall", "Search project memory (facts, accepted rules, decisions, open items, episodes). Use before re-deriving.",
         {"query": {"type": "string"}, "limit": {"type": "integer"}}, ["query"]),
    tool("viber_context", "Get the context pack for a component or session: rules, handoffs, active sessions, bugs, decisions, changes.",
         {"session_id": {"type": "string"}, "component": {"type": "string"}, "budget_tokens": {"type": "integer"}}, []),
    tool("viber_quick", "Log a small piece of work in one line: creates a done quick-lane item and a changelog entry.",
         {"title": {"type": "string"}, "component": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}},
          "kind": {"type": "string", "description": "feat, fix, docs, refactor, chore (default change)"}}, ["title"]),
    tool("viber_bug", "Log a bug found during manual testing or work. Returns its BUG-NNN key.",
         {"title": {"type": "string"}, "area": {"type": "string"}, "severity": {"type": "string"},
          "repro": {"type": "string"}, "expected": {"type": "string"}, "actual": {"type": "string"},
          "component": {"type": "string"}}, ["title"]),
    tool("viber_remember", "Store a durable fact (as fact) or propose a rule for the human to accept (as rule).",
         {"text": {"type": "string"}, "as": {"type": "string", "enum": ["fact", "rule"]}, "subject": {"type": "string"},
          "category": {"type": "string", "description": "for rules: decision, pattern or constraint"},
          "about": {"type": "array", "items": {"type": "string"}, "description": "entity names this fact is about (the memory graph)"},
          "component": {"type": "string"}}, ["text"]),
    tool("viber_decide", "Record an architectural decision (ADR) as Proposed. Humans accept it. Pass the key from viber_next_adr, or none to take the next one.",
         {"key": {"type": "string"}, "title": {"type": "string"}, "context": {"type": "string"}, "decision": {"type": "string"},
          "alternatives": {"type": "string"}, "consequences": {"type": "string"}}, ["title", "decision"]),
    tool("viber_handoff", "Leave what this session learned for the next session or a fork: summary, decisions, open questions, next steps.",
         {"session_id": {"type": "string"}, "summary": {"type": "string"}, "decisions": {"type": "array", "items": {"type": "string"}},
          "open_questions": {"type": "array", "items": {"type": "string"}}, "next_steps": {"type": "array", "items": {"type": "string"}}},
         ["session_id", "summary"]),
    tool("viber_sessions", "List the active sessions in the project, with their goals and the files they are editing.", {}, []),
    tool("viber_next_adr", "Get the next decision number (for example ADR-v3.018). It is reserved for you, so two sessions never get the same one.",
         {"prefix": {"type": "string", "description": "optional; defaults to the prefix the project already uses"}}, []),
    tool("viber_get_adr", "Read one decision by its key (ADR-v3.017) or its number alone (17). Returns its statements, one per line.",
         {"adr": {"type": "string"}}, ["adr"]),
    tool("viber_spec_add", "Add specification rows: one requirement, constraint, interface or acceptance criterion per line.",
         {"text": {"type": "string", "description": "one statement per line; each becomes a row of at most 400 characters"},
          "kind": {"type": "string", "enum": ["requirement", "constraint", "interface", "acceptance", "nfr", "question"]},
          "component": {"type": "string"}, "parent": {"type": "string", "description": "key of the spec this refines"}}, ["text"]),
    tool("viber_spec_get", "Read one spec by key, or list specs by component, kind, status or a search query.",
         {"key": {"type": "string"}, "component": {"type": "string"}, "kind": {"type": "string"}, "status": {"type": "string"},
          "query": {"type": "string"}, "limit": {"type": "integer"}}, []),
    tool("viber_spec_status", "Change a spec's status (Draft, Agreed, Built, Verified, Dropped) or its statement.",
         {"key": {"type": "string"}, "status": {"type": "string"}, "statement": {"type": "string"}}, ["key"]),
    tool("viber_link", "Record a relation in the memory graph, for example sb-fleet / depends on / sb-contracts. Entities are created by name.",
         {"subject": {"type": "string"}, "relation": {"type": "string", "description": "up to 60 characters"}, "object": {"type": "string"},
          "subject_kind": {"type": "string"}, "object_kind": {"type": "string"}}, ["subject", "relation", "object"]),
    tool("viber_graph", "Show an entity from the memory graph: its aliases, current relations and the facts about it.",
         {"entity": {"type": "string"}, "limit": {"type": "integer"}}, ["entity"]),
]


def component_scope(component_key: str | None) -> str:
    return f"component:{component_key}" if component_key else "project"


def run_recall(connection, project, arguments):
    return service.recall(connection, project, arguments["query"], min(int(arguments.get("limit", 8)), 30))["context"]


def run_context(connection, project, arguments):
    session = None
    if arguments.get("session_id"):
        session = sessions.session_by_external_id(connection, project, arguments["session_id"])
    component = None
    if arguments.get("component"):
        component = connection.execute("SELECT id, key FROM component WHERE project_id=%s AND key=%s",
                                       (project["id"], arguments["component"])).fetchone()
    elif session and session["component_id"]:
        component = connection.execute("SELECT id, key FROM component WHERE id=%s", (session["component_id"],)).fetchone()
    return sessions.build_context_pack(connection, project, session, component, int(arguments.get("budget_tokens", 1500)))["context"]


def run_quick(connection, project, arguments):
    item, _ = service.create_item(connection, project, ItemIn(
        kind="task", lane="quick", status="Done", title=arguments["title"],
        component_keys=[arguments["component"]] if arguments.get("component") else [],
        data={"files": arguments.get("files", [])}), ACTOR)
    service.create_change(connection, project, ChangeIn(
        summary=arguments["title"], occurred_on=date.today(), kind=arguments.get("kind", "change"),
        component_key=arguments.get("component")), ACTOR)
    return f"Logged {item['key']} (quick, done) and a changelog entry."


def run_bug(connection, project, arguments):
    body = "\n".join(f"{label}: {arguments[name]}" for name, label in
                     (("repro", "Repro"), ("expected", "Expected"), ("actual", "Actual")) if arguments.get(name))
    item, _ = service.create_item(connection, project, ItemIn(
        kind="bug", title=arguments["title"], body=body, area=arguments.get("area"), severity=arguments.get("severity"),
        found_on=date.today(), lane="standard",
        component_keys=[arguments["component"]] if arguments.get("component") else []), ACTOR)
    return f"Logged {item['key']} (Open)."


def run_remember(connection, project, arguments):
    scope = component_scope(arguments.get("component"))
    limit = RULE_MAX if arguments.get("as") == "rule" else FACT_MAX
    if len(arguments["text"]) > limit:
        return (f"Too long: {len(arguments['text'])} characters, the limit is {limit}. Memory holds one statement per row: "
                "split it into several short facts and call viber_remember for each.")
    if arguments.get("as") == "rule":
        result, created = service.create_rule(connection, project, RuleIn(
            text=arguments["text"], category=arguments.get("category", "constraint"), scope=scope, proposed_by=ACTOR), ACTOR)
        return "Proposed rule (a human must accept it)." if created else "That rule already exists."
    result, created = service.create_fact(connection, project, FactIn(
        text=arguments["text"], subject=arguments.get("subject"), scope=scope), ACTOR)
    about = arguments.get("about") or []
    if created and about and result.get("id"):
        graph.link_fact(connection, project, result["id"], about)
    return "Remembered." if created else "Already known."


def run_decide(connection, project, arguments):
    key = arguments.get("key") or adr.next_key(connection, project, None, ACTOR)
    service.create_decision(connection, project, DecisionIn(
        key=key, title=arguments["title"], status="Proposed", decided_on=date.today(), context=arguments.get("context", ""),
        decision=arguments["decision"], alternatives=arguments.get("alternatives", ""),
        consequences=arguments.get("consequences", "")), ACTOR)
    return f"Recorded {key} as Proposed; a human must accept it."


def run_handoff(connection, project, arguments):
    result = sessions.record_handoff(connection, project, arguments["session_id"], HandoffIn(
        summary=arguments["summary"], decisions=arguments.get("decisions", []),
        open_questions=arguments.get("open_questions", []), next_steps=arguments.get("next_steps", [])), ACTOR)
    return f"Handoff recorded for {result['tag']}. The next session or fork will see it."


def run_sessions(connection, project, arguments):
    active = sessions.active_sessions(connection, project)
    if not active:
        return "No other active sessions."
    return "\n".join(f"{s['tag']} ({s['state']}) {s['goal'] or 'no goal'}" + (f" - editing {', '.join(s['files'])}" if s["files"] else "")
                     for s in active)


def run_next_adr(connection, project, arguments):
    key = adr.next_key(connection, project, arguments.get("prefix"), ACTOR)
    return f"{key} is reserved for you. Fill it with viber_decide (key={key}); an unused reservation shows as Reserved."


def run_get_adr(connection, project, arguments):
    return adr.as_text(adr.read(connection, project, str(arguments["adr"])))


def run_spec_add(connection, project, arguments):
    rows = specs.create_from_text(connection, project, arguments["text"], kind=arguments.get("kind", "requirement"),
                                  component_key=arguments.get("component"), parent_key=arguments.get("parent"), actor=ACTOR)
    return "Added: " + ", ".join(r["key"] for r in rows) if rows else "Nothing to add."


def run_spec_get(connection, project, arguments):
    if arguments.get("key"):
        s = specs.read(connection, project, arguments["key"])
        return f"{s['key']} [{s['kind']}, {s['status']}] {s['statement']}" + (f" (children: {', '.join(s['children'])})" if s["children"] else "")
    rows = specs.list_specs(connection, project, arguments.get("component"), arguments.get("kind"), arguments.get("status"),
                            arguments.get("query"), int(arguments.get("limit", 50)))
    return "\n".join(f"{r['key']} [{r['kind']}, {r['status']}] {r['statement']}" for r in rows) or "No specs match."


def run_spec_status(connection, project, arguments):
    s = specs.update(connection, project, arguments["key"], arguments.get("statement"), arguments.get("status"), ACTOR)
    return f"{s['key']} is {s['status']}."


def run_link(connection, project, arguments):
    r = graph.link(connection, project, arguments["subject"], arguments["relation"], arguments["object"],
                   arguments.get("subject_kind"), arguments.get("object_kind"))
    return f"{r['subject']} {r['relation']} {r['object']}" + (" (new)." if r["created"] else " (already known).")


def run_graph(connection, project, arguments):
    return graph.graph_text(graph.around(connection, project, arguments["entity"], int(arguments.get("limit", 40))))


RUNNERS = {"viber_recall": run_recall, "viber_context": run_context, "viber_quick": run_quick, "viber_bug": run_bug,
           "viber_remember": run_remember, "viber_decide": run_decide, "viber_handoff": run_handoff, "viber_sessions": run_sessions,
           "viber_next_adr": run_next_adr, "viber_get_adr": run_get_adr, "viber_spec_add": run_spec_add,
           "viber_spec_get": run_spec_get, "viber_spec_status": run_spec_status, "viber_link": run_link, "viber_graph": run_graph}


def call_tool(name: str, arguments: dict) -> dict:
    runner = RUNNERS.get(name)
    if not runner:
        return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
    try:
        with transaction() as connection:
            project = service.project_row(connection, arguments.get("project", ""))
            text = runner(connection, project, arguments)
        return {"content": [{"type": "text", "text": text}], "isError": False}
    except HTTPException as error:
        return {"content": [{"type": "text", "text": f"{error.detail}"}], "isError": True}
    except KeyError as missing:
        return {"content": [{"type": "text", "text": f"missing argument {missing}"}], "isError": True}


def handle_message(message: dict) -> dict:
    method, request_id, params = message.get("method"), message.get("id"), message.get("params") or {}
    if method == "initialize":
        result = {"protocolVersion": params.get("protocolVersion", DEFAULT_PROTOCOL_VERSION), "capabilities": {"tools": {}},
                  "serverInfo": {"name": "viber", "version": __version__}, "instructions": INSTRUCTIONS}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        result = call_tool(params.get("name", ""), params.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}, status_code=400)
    messages = body if isinstance(body, list) else [body]
    responses = [await run_in_threadpool(handle_message, m) for m in messages if isinstance(m, dict) and "id" in m]
    if not responses:
        return Response(status_code=202)
    return JSONResponse(responses if isinstance(body, list) else responses[0])


@router.get("/mcp")
def mcp_stream_not_offered():
    return Response(status_code=405, headers={"Allow": "POST"})
