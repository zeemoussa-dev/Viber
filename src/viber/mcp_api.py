"""MCP over HTTP (JSON-RPC, JSON responses). Claude Code connects with:
   claude mcp add --transport http viber http://localhost:8088/mcp
The tools are thin wrappers over the same service functions the REST API uses."""
import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import __version__, adr, backup, consolidation, fornow, graph, prompts, refs, service, sessions, specs, views
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
         {"session_id": {"type": "string", "description": "Your session tag, e.g. S1"}, "component": {"type": "string"},
          "budget_tokens": {"type": "integer"}}, []),
    tool("viber_quick", "Log a small piece of work in one line: creates a done quick-lane item and a changelog entry.",
         {"title": {"type": "string"}, "component": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}},
          "kind": {"type": "string", "description": "feat, fix, docs, refactor, chore (default change)"}}, ["title"]),
    tool("viber_bug", "Log a bug found during manual testing or work. Returns its BUG-NNN key.",
         {"title": {"type": "string"}, "area": {"type": "string"}, "severity": {"type": "string"},
          "repro": {"type": "string"}, "expected": {"type": "string"}, "actual": {"type": "string"},
          "component": {"type": "string"}}, ["title"]),
    tool("viber_for_now", "List what is true only for now (temporary instructions and states), with when each ends and who recorded it.", {}, []),
    tool("viber_end_for_now", "End a temporary fact early. One the operator set can only be ended by the operator.", {"id": {"type": "string"}}, ["id"]),
    tool("viber_remember", "Store a durable fact (as fact) or propose a rule for the human to accept (as rule). Something true only for a while "
                           "('run unattended tonight', 'don't touch billing until Friday') is NOT a rule: store it as a fact with lasts or until, "
                           "and it disappears by itself.",
         {"lasts": {"type": "string", "description": "temporary fact: how long, such as 90m, 12h, 2d or 1w"},
          "until": {"type": "string", "description": "temporary fact: when it ends, ISO time with offset, such as 2026-11-27T08:00+04:00"},
          "text": {"type": "string"}, "as": {"type": "string", "enum": ["fact", "rule"]}, "subject": {"type": "string"},
          "category": {"type": "string", "description": "for rules: decision, pattern or constraint"},
          "about": {"type": "array", "items": {"type": "string"}, "description": "entity names this fact is about (the memory graph)"},
          "component": {"type": "string"}}, ["text"]),
    tool("viber_decide", "Record an architectural decision (ADR) as Proposed. Humans accept it. Pass the key from viber_next_adr, or none to take the next one.",
         {"key": {"type": "string"}, "title": {"type": "string"}, "context": {"type": "string"}, "decision": {"type": "string"},
          "alternatives": {"type": "string"}, "consequences": {"type": "string"}}, ["title", "decision"]),
    tool("viber_handoff", "Leave what this session learned for the next session or a fork: summary, decisions, open questions, next steps.",
         {"session_id": {"type": "string", "description": "Your session tag from the context, e.g. S1"}, "summary": {"type": "string"}, "decisions": {"type": "array", "items": {"type": "string"}},
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
    tool("viber_plan", "Create a plan, or show one. A plan is a row: its content is the specs, bugs, tasks and decisions linked to it.",
         {"key": {"type": "string", "description": "show this plan; omit with a title to create one"}, "title": {"type": "string"},
          "goal": {"type": "string", "description": "one line, at most 300 characters"}}, []),
    tool("viber_plan_add", "Add things to a plan, in order. Each member is type:key, for example spec:REQ-004, item:BUG-012, decision:ADR-v3.017.",
         {"plan": {"type": "string"}, "members": {"type": "array", "items": {"type": "string"}}}, ["plan", "members"]),
    tool("viber_ref", "Link two things with a dated relation (contains, applies_to, supersedes, about, found_in, fixed_in, implements, verifies, refines, blocks, depends_on, replaces, mentions). "
                      "A decision applies_to a component or version (component@semver) with an optional version range. Types: plan, spec, item, decision, component, version, fact, release, entity.",
         {"from": {"type": "string", "description": "type:key"}, "relation": {"type": "string"}, "to": {"type": "string", "description": "type:key"},
          "version_range": {"type": "string"}, "note": {"type": "string"}, "end": {"type": "boolean", "description": "end this link instead of adding it"}},
         ["from", "relation", "to"]),
    tool("viber_refs", "Show everything linked to one thing, both directions (for example decision:ADR-v3.017 or component:sb-fleet).",
         {"thing": {"type": "string", "description": "type:key"}, "ended": {"type": "boolean"}}, ["thing"]),
    tool("viber_retire", "Mark something obsolete without deleting it (decision, spec, fact or plan). Its applies_to and about links end.",
         {"thing": {"type": "string", "description": "type:key"}, "reason": {"type": "string"}}, ["thing"]),
    tool("viber_backup_status", "Is Viber's own database backed up and checked? The last good backup, its age and size, and any problem.", {}, []),
    tool("viber_item", "Create a piece of work: a story, task, chore, spike, idea or bug, with details, optionally in a plan and under a parent item. "
                       "Use gate 'flagged' with a reason when a human must decide.",
         {"kind": {"type": "string", "enum": ["story", "task", "chore", "spike", "idea", "bug"]}, "title": {"type": "string"},
          "details": {"type": "string", "description": "any length; stored one statement per row"}, "component": {"type": "string"},
          "lane": {"type": "string", "enum": ["quick", "standard", "full"]}, "status": {"type": "string"},
          "plan": {"type": "string", "description": "plan key to add it to"}, "parent": {"type": "string", "description": "item key it refines"},
          "gate": {"type": "string", "enum": ["clear", "flagged"]}, "gate_reason": {"type": "string"},
          "severity": {"type": "string"}, "area": {"type": "string"}}, ["kind", "title"]),
    tool("viber_item_status", "Move a piece of work along (Open, Ready, In Progress, In Review, Blocked, Done, Closed, Fixed, Won't Fix) or flag or clear it for a human.",
         {"key": {"type": "string"}, "status": {"type": "string"}, "gate": {"type": "string", "enum": ["clear", "flagged"]}, "gate_reason": {"type": "string"}}, ["key"]),
    tool("viber_view", "A generated markdown view of the project: status, adr, rules, specs, plans, backlog, claude (the project's CLAUDE.md) or changelog.",
         {"name": {"type": "string"}}, ["name"]),
    tool("viber_prompt", "Read one of the project's prompts (start, resume, component, bug, decide, plan, consolidate, finish), or list them when no key is given.",
         {"key": {"type": "string"}, "component": {"type": "string"}}, []),
    tool("viber_stale", "List decisions, specs and facts still linked to a component that is deprecated or archived, for review.", {}, []),
    tool("viber_episodes_pending", "Consolidation, step 1: the episodes since the last consolidation. Read them, keep what is durable, and store it with "
                                   "viber_remember (as fact, or as rule for a human to accept). Then call viber_consolidated.", {}, []),
    tool("viber_consolidated", "Consolidation, step 2: mark the episodes up to this one as handled, so the next batch starts after it.",
         {"through_episode_id": {"type": "string", "description": "id of the last episode you handled"}}, ["through_episode_id"]),
    tool("viber_component_digest", "Reflection, step 1: recent changes, work and facts about one component, plus its current summary.",
         {"component": {"type": "string"}}, ["component"]),
    tool("viber_reflection", "Reflection, step 2: store a current summary of a component (1 to 5 short statements); it replaces the previous summary.",
         {"component": {"type": "string"}, "statements": {"type": "array", "items": {"type": "string"}}}, ["component", "statements"]),
    tool("viber_consolidate", "Only if a separate chat model is configured (VIBER_LLM_*): have it do the consolidation. Normally use viber_episodes_pending.", {}, []),
    tool("viber_reflect", "Only if a separate chat model is configured: have it write a component summary. Normally use viber_component_digest.",
         {"component": {"type": "string"}}, ["component"]),
    tool("viber_duplicates", "List live facts that mean nearly the same thing, so the older one can be superseded.", {}, []),
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
        kind="bug", title=arguments["title"][:400], body="", details=body, area=arguments.get("area"), severity=arguments.get("severity"),
        found_on=date.today(), lane="standard",
        component_keys=[arguments["component"]] if arguments.get("component") else []), ACTOR)
    return f"Logged {item['key']} (Open)."


def run_remember(connection, project, arguments):
    scope = component_scope(arguments.get("component"))
    end = fornow.parse_expiry(arguments.get("lasts"), arguments.get("until"))
    if end is not None:
        if arguments.get("as") == "rule":
            return "A rule is permanent. Something true only for a while is a temporary fact: leave out as='rule'."
        # Whatever a session says, it records as a session: only the dashboard speaks for the operator.
        made = fornow.add(connection, project, arguments["text"], end, by_operator=False, scope=scope, actor=ACTOR)
        return (f"Noted until {fornow.stamp(end)} ({fornow.left(end)}); it ends by itself. id {made['id']}"
                + ("" if made["created"] else " (already there: its end is moved)"))
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


def _typed(value: str) -> tuple[str, str]:
    kind, separator, key = (value or "").partition(":")
    if not separator or not key:
        raise HTTPException(422, f"'{value}' should be type:key, for example spec:REQ-004")
    return kind.strip().lower(), key.strip()


def run_plan(connection, project, arguments):
    if arguments.get("key") and not arguments.get("title"):
        return refs.plan_text(refs.plan_view(connection, project, arguments["key"]))
    if not arguments.get("title"):
        plans = refs.list_plans(connection, project)
        return "\n".join(f"{p['key']} [{p['status']}] {p['title']} ({p['members']} items)" for p in plans) or "No plans yet."
    result = refs.create_plan(connection, project, arguments.get("key"), arguments["title"], arguments.get("goal", ""), actor=ACTOR)
    return f"Plan {result['key']} created." if result["created"] else f"Plan {result['key']} already exists."


def run_plan_add(connection, project, arguments):
    result = refs.add_to_plan(connection, project, arguments["plan"], [_typed(m) for m in arguments["members"]], ACTOR)
    return f"Added to {result['plan']}: {', '.join(result['added'])}."


def run_ref(connection, project, arguments):
    (from_type, from_key), (to_type, to_key) = _typed(arguments["from"]), _typed(arguments["to"])
    if arguments.get("end"):
        return f"Ended {refs.end(connection, project, from_type, from_key, arguments['relation'], to_type, to_key, ACTOR)['ended']} link(s)."
    r = refs.add(connection, project, from_type, from_key, arguments["relation"], to_type, to_key,
                 arguments.get("version_range"), None, arguments.get("note"), actor=ACTOR)
    return f"{r['from']} {r['relation']} {r['to']}" + (" (new)." if r["created"] else " (already linked).")


def run_refs(connection, project, arguments):
    kind, key = _typed(arguments["thing"])
    return refs.show_text(refs.show(connection, project, kind, key, bool(arguments.get("ended"))))


def run_retire(connection, project, arguments):
    kind, key = _typed(arguments["thing"])
    r = refs.retire(connection, project, kind, key, arguments.get("reason"), ACTOR)
    return f"{r['retired']} is obsolete; {r['links_ended']} link(s) ended. Nothing was deleted."


def run_stale(connection, project, arguments):
    rows = refs.stale(connection, project)
    return "\n".join(f"{r['type']}:{r['key']} {r['relation']} {r['component']} ({r['lifecycle']})" for r in rows) or "Nothing is tied to a deprecated or archived component."


def run_for_now(connection, project, arguments):
    rows = fornow.live(connection, project)
    return "\n".join(fornow.line(f) for f in rows) or "Nothing temporary is in force."


def run_end_for_now(connection, project, arguments):
    fornow.end_now(connection, project, arguments["id"], may_end_operators=False, actor=ACTOR)
    return "Ended."


def run_backup_status(connection, project, arguments):
    h = backup.health()
    if not h["last_good"]:
        return "There is NO checked backup of Viber's database. Ask the operator to make one (System page > Back up now)."
    last = h["runs"][0]
    lines = [f"Last good backup {h['last_good_age_hours']} h ago, {round(h['last_good']['bytes'] / 1e6, 1)} MB, checked by a restore. {h['good_backups']} kept in {h['folder']}.",
             f"Schedule: every {h['schedule_hours']} h." if h["schedule_hours"] > 0 else "No schedule: backups run only when asked."]
    if not h["healthy"]:
        lines.append("PROBLEM: the backups are not healthy" + (f" (missing files: {', '.join(h['files_missing'])})" if h["files_missing"] else " (the last good one is older than the schedule allows)") + ".")
    if last["status"] == "failed":
        lines.append(f"The latest attempt failed: {last['error'] or last['verify_note']}")
    return "\n".join(lines)


def run_item(connection, project, arguments):
    kind = arguments["kind"]
    item, created = service.create_item(connection, project, ItemIn(
        kind=kind, title=arguments["title"][:400], details=arguments.get("details", ""), lane=arguments.get("lane", "standard"),
        status=arguments.get("status", "Open"), gate=arguments.get("gate", "clear"), gate_reason=arguments.get("gate_reason"),
        severity=arguments.get("severity"), area=arguments.get("area"), found_on=date.today(),
        component_keys=[arguments["component"]] if arguments.get("component") else []), ACTOR)
    notes = []
    if arguments.get("plan"):
        refs.add_to_plan(connection, project, arguments["plan"], [("item", item["key"])], ACTOR)
        notes.append(f"in plan {arguments['plan']}")
    if arguments.get("parent"):
        refs.add(connection, project, "item", item["key"], "refines", "item", arguments["parent"], actor=ACTOR)
        notes.append(f"refines {arguments['parent']}")
    return f"Created {item['key']} ({kind})" + (": " + ", ".join(notes) if notes else "") + "."


def run_item_status(connection, project, arguments):
    if not any(arguments.get(f) for f in ("status", "gate")):
        return "Nothing to change: give a status or a gate."
    row = connection.execute(
        "UPDATE item SET status = COALESCE(%s, status), gate = COALESCE(%s, gate), gate_reason = CASE WHEN %s::text = 'clear' THEN NULL ELSE COALESCE(%s, gate_reason) END, "
        "updated_at = now() WHERE project_id = %s AND key = %s RETURNING key, status, gate",
        (arguments.get("status"), arguments.get("gate"), arguments.get("gate"), arguments.get("gate_reason"), project["id"], arguments["key"])).fetchone()
    if not row:
        raise HTTPException(404, f"item '{arguments['key']}' not found")
    record_audit(connection, ACTOR, "status", "item", row["key"], project["id"], {"status": row["status"], "gate": row["gate"]})
    return f"{row['key']} is {row['status']}" + (" and flagged for a human." if row["gate"] == "flagged" else ".")


def run_view(connection, project, arguments):
    name = arguments["name"]
    if name == "changelog":
        return service.render_changelog(connection, project)
    return views.render(connection, project, name)


def run_prompt(connection, project, arguments):
    if arguments.get("key"):
        return prompts.render(connection, project, arguments["key"], arguments.get("component"))
    rows = prompts.list_prompts(connection, project)
    return "\n".join(f"{r['key']}: {r['title']} - {r['purpose']}" for r in rows) or "No prompts yet; seed them with POST .../prompts/seed."


def run_episodes_pending(connection, project, arguments):
    batch = consolidation.pending_episodes(connection, project)
    if not batch["episodes"]:
        return "Nothing new to consolidate."
    lines = [f"{len(batch['episodes'])} episode(s) since {batch['since'] or 'the start'}. Keep only what stays true; one short statement each."]
    lines += [f"- [{e['id']}] ({e['kind']}) {' '.join(e['content'].split())[:400]}" for e in batch["episodes"]]
    lines.append(f"When done, call viber_consolidated with through_episode_id={batch['episodes'][-1]['id']}.")
    return "\n".join(lines)


def run_consolidated(connection, project, arguments):
    return f"Marked through episode {consolidation.mark_consolidated(connection, project, arguments['through_episode_id'], ACTOR)['through']}."


def run_component_digest(connection, project, arguments):
    d = consolidation.component_digest(connection, project, arguments["component"])
    out = [f"Recent about {arguments['component']}:"]
    for label, key in (("Changes", "changes"), ("Work", "items"), ("Facts", "facts"), ("Current summary", "current_reflection")):
        if d[key]:
            out += [f"{label}:"] + [f"- {x}" for x in d[key]]
    return "\n".join(out) if len(out) > 1 else f"Nothing recorded for {arguments['component']} yet."


def run_reflection(connection, project, arguments):
    r = consolidation.write_reflection(connection, project, arguments["component"], arguments["statements"], ACTOR)
    return f"{r['component']}: {r['statements']} statement(s) stored; the previous summary is ended."


def run_consolidate(connection, project, arguments):
    r = consolidation.propose(connection, project, ACTOR)
    return f"{r['episodes']} episode(s) read: {r.get('facts', 0)} fact(s) stored, {r.get('rules', 0)} rule(s) proposed, {r.get('dropped', 0)} dropped." + (f" {r['note']}" if r.get("note") else "")


def run_reflect(connection, project, arguments):
    r = consolidation.reflect(connection, project, arguments["component"], ACTOR)
    return f"{r['component']}: {r['statements']} statement(s) written." + (f" {r['note']}" if r.get("note") else "")


def run_duplicates(connection, project, arguments):
    rows = consolidation.duplicates(connection, project)
    return "\n".join(f"{r['similarity']} older {r['older']}: {r['older_text'][:80]} | newer {r['newer']}: {r['newer_text'][:80]}" for r in rows) or "No near-duplicate facts."


RUNNERS = {"viber_for_now": run_for_now, "viber_end_for_now": run_end_for_now, "viber_backup_status": run_backup_status, "viber_item": run_item, "viber_item_status": run_item_status, "viber_view": run_view, "viber_prompt": run_prompt, "viber_episodes_pending": run_episodes_pending, "viber_consolidated": run_consolidated,
           "viber_component_digest": run_component_digest, "viber_reflection": run_reflection, "viber_consolidate": run_consolidate, "viber_reflect": run_reflect, "viber_duplicates": run_duplicates, "viber_plan": run_plan, "viber_plan_add": run_plan_add, "viber_ref": run_ref, "viber_refs": run_refs,
           "viber_retire": run_retire, "viber_stale": run_stale, "viber_recall": run_recall, "viber_context": run_context, "viber_quick": run_quick, "viber_bug": run_bug,
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
