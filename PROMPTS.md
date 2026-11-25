# Session Prompts

Ready-to-paste prompts for Claude Code sessions: to connect a repo to Viber, import what it already has, and work
with Viber day to day. They rest on `project-scaffold` (which holds the file formats, the API calls and the import
mapping), so each prompt only adds what is specific to one repo or one situation.

## Read this first

**Two modes, because the full lane (stories, tasks, sprints) is not built yet.**

- **Mirror**: the repo's markdown files stay the source of truth and its pipeline (`/bug`, `/spec`, the coder agent...)
  keeps writing them. Viber gets a read-only copy, plus session memory, handoffs and collision warnings. Nothing is
  frozen, moved or rewritten, and the import can be repeated (Prompt 5) to pick up what was added since. **Use this for
  `second_brain`, `sb-orchestration` and every `sb-*` repo,** because the v3 pipeline in `sb-orchestration` writes their
  `CHANGELOG.md` and `MEMORY.md`.
- **Switch-over**: Viber becomes the source of truth and the imported files are frozen. **Use this only for repos no
  pipeline maintains** (Padelers, Jarvis, azure-finOps, new repos). The `sb-*` repos move to it once the full lane exists.

**Before pasting anything, once per machine** (see `DEPLOY.md`): Viber is running; `VIBER_TOKEN` is set as a user
environment variable if you set a token (`[Environment]::SetEnvironmentVariable("VIBER_TOKEN","<token>","User")`) and Claude
Code was restarted afterwards; and you know the folder of this machine's Viber checkout. Each prompt starts with two settings
lines: edit `VIBER_DIR` to that folder (the URL defaults to `http://localhost:8088`). **Never paste the token into a prompt.**

**Order for Second Brain OS:** 1 (`second_brain`) → 2 (`sb-orchestration`) → 3 once per other repo → 6 in a separate session to
audit each import → open the dashboard and review the imported rules. Then the day-to-day prompts (7, 8) in any wired repo.

| # | Prompt | Use it in | Changes the repo? |
|---|---|---|---|
| 1 | Mirror import: `second_brain` | the `second_brain` repo | appends one section to `CLAUDE.md`, adds 3 command files, `.mcp.json`, settings |
| 2 | Mirror import: `sb-orchestration` | the `sb-orchestration` repo | same |
| 3 | Mirror import: any other repo | an `sb-*` repo, a plugin, an agent repo | same |
| 4 | Switch over: a standalone repo | a repo with no pipeline | yes: rewrites `CLAUDE.md`, freezes imported files (after you confirm) |
| 5 | Re-sync | any mirrored repo | no |
| 6 | Audit an import | a **separate** session in the same repo | no (read-only) |
| 7 | Fork kickoff | the first message of a forked session | no |
| 8 | Closeout | the end of any session | no |

None of the import prompts commits anything. Each stops at the dry-run table and waits for you to say "import".

---

## 1. Mirror import: `second_brain`

~~~text
VIBER_DIR = D:/MyWorx/Projects/Viber        <- edit: the folder of this machine's Viber checkout
VIBER_URL = http://localhost:8088

Task: mirror this repository's tracking history into Viber and wire this repo's sessions to it, in MIRROR mode. The markdown
files stay the source of truth (this repo's pipeline keeps running on them); Viber receives a copy and the read-side tools. Do
not freeze, move, rewrite, rename or delete any existing file. Do not commit.

Read VIBER_DIR/project-scaffold and follow its "Scaffold Prompt" Steps 1 to 7 exactly, in mirror mode. These answers are already
given, so do not ask for them again (ask only for anything else the steps need):
- Project key: sbos, named "Second Brain OS". Component key: second_brain, kind app, repo zeemoussa-dev/second_brain.
- Mode: mirror.
- Phase 1 import, in this order: Implementation/Architecture/ADR.md -> decisions; BUGS.md -> items; CHANGELOG.md -> changes;
  MEMORY.md -> rules; Implementation/Learnings.md -> facts; ESCALATIONS.md -> episodes.
- Do NOT import: BACKLOG.md, stories, tasks, sprints, Pipeline.md, REVIEW-QUEUE.md, Documentation/, html-prototype/. They wait for
  Viber's full lane.

Specific to this repo:
- ADR keys come in two schemes, ADR-NNN and ADR-v2.NNN. Keep each exactly as written. Supersession is written in prose
  ("Superseded by ADR-XXX"): map it to superseded_by / supersedes; where you cannot tell, keep the status as written and list it.
- This is the first repo imported into project sbos, so BUG-NNN and ESC-NNN keep their ids as written. (sb-orchestration is
  imported after this one and gets prefixed keys.)
- Memory and learnings scope: component:second_brain.
- CLAUDE.md here is long and specific. In mirror mode you only APPEND the short "Viber (mirror mode)" section; change nothing else in
  it. Leave .claude/agents and .claude/commands alone except adding recall, handoff and status commands that do not exist yet. There
  is an existing /bug command: leave it.
- Anything you cannot parse cleanly: do not guess. List it with file and line.

Stop points: (1) after Step 2 if Viber is unreachable or the token is refused; (2) after the dry-run table, wait for me to say
"import"; (3) after the import, show the verification and stop.

Final report: files created or changed; per file the counts parsed / created / skipped / invalid; what was not imported and why;
what I must do next (start a new session here, approve the MCP server, look at the dashboard); and anything unverified.
~~~

## 2. Mirror import: `sb-orchestration`

Run this **after** Prompt 1, in the `sb-orchestration` repo.

~~~text
VIBER_DIR = D:/MyWorx/Projects/Viber        <- edit: the folder of this machine's Viber checkout
VIBER_URL = http://localhost:8088

Task: mirror this repository's tracking history into Viber and wire this repo's sessions to it, in MIRROR mode. The markdown
files stay the source of truth; the pipeline that plans v3 keeps running on them. Do not freeze, move, rewrite, rename or delete
any existing file. Do not commit.

Read VIBER_DIR/project-scaffold and follow its "Scaffold Prompt" Steps 1 to 7 exactly, in mirror mode. Already answered:
- Project key: sbos (it already exists; second_brain was imported into it first). Component key: sb-orchestration, kind docs,
  repo zeemoussa-dev/sb-orchestration.
- Mode: mirror.
- Phase 1 import, in this order: ADR file (the cross-project ADRs, ids like ADR-v3.NNN) -> decisions; BUGS.md -> items;
  CHANGELOG.md -> changes; MEMORY.md -> rules; ESCALATIONS.md -> episodes; Learnings.md if present -> facts.
- Do NOT import: BACKLOG.md, PROJECTS.md, STATUS.md (Viber's component map and dashboard replace those two over time; leave the files
  as they are), Plans/, Implementation/ stories, tasks, sprints, architecture and Pipeline.md, REVIEW-QUEUE.md.

Specific to this repo:
- project sbos already holds second_brain's records, and both repos number bugs BUG-NNN. Prefix this repo's bug keys with ORCH-
  (BUG-001 becomes ORCH-BUG-001) and keep the original id as source_ref. Do the same for any other id that is only unique within
  this repo. ADR ids (ADR-v3.NNN) are unique by design: keep them as written. The collision check in Step 6 must show skipped = 0
  on the first dry run of each file; if not, stop and report which keys collide.
- A CHANGELOG entry that starts by naming a component (for example "sb-core: ...") belongs to that component if it exists
  (GET VIBER_URL/v1/projects/sbos/components); otherwise use sb-orchestration and list the entry in your report.
- MEMORY.md here holds rules for the whole of v3: use scope "project", not a component scope.
- Append only the short "Viber (mirror mode)" section to CLAUDE.md; change nothing else in it.
- Anything you cannot parse cleanly: do not guess. List it with file and line.

Stop points: (1) after Step 2 if Viber is unreachable or the token is refused; (2) after the dry-run table, wait for me to say
"import"; (3) after the import, show the verification and stop.

Final report: files created or changed; per file the counts parsed / created / skipped / invalid; every changelog entry you could not
attribute to a component; what was not imported and why; what I must do next; anything unverified.
~~~

## 3. Mirror import: any other repo

For an `sb-*` repo, a plugin or an agent repo. Fill the three values, then paste.

~~~text
VIBER_DIR = D:/MyWorx/Projects/Viber        <- edit: the folder of this machine's Viber checkout
VIBER_URL = http://localhost:8088
REPO_FOLDER = <this repo's folder name, e.g. sb-core>      (this is the Viber component key)
KIND = <service | library | plugin | app | infra | chart | docs | tool>
REPO = <owner/name, e.g. zeemoussa-dev/sb-core>
SHORT_CODE = <2 to 6 capital letters for this repo, e.g. CORE>   (only used if the repo has a BUGS.md)

Task: mirror this repository's tracking history into Viber and wire this repo's sessions to it, in MIRROR mode. The markdown files
stay the source of truth, because the v3 pipeline (in sb-orchestration) writes them. Do not freeze, move, rewrite, rename or delete
any existing file. Do not commit.

Read VIBER_DIR/project-scaffold and follow its "Scaffold Prompt" Steps 1 to 7 exactly, in mirror mode. Already answered:
- Project key: sbos (it already exists). Component key: REPO_FOLDER, kind KIND, repo REPO. Mode: mirror.
- Import only what exists, from: CHANGELOG.md -> changes; MEMORY.md -> rules; BUGS.md -> items (keys prefixed SHORT_CODE-, e.g.
  CORE-BUG-001, original id kept as source_ref); an ADR file -> decisions (keys as written); Learnings.md -> facts.
- Do NOT import anything else (README, Plans/, docs, code comments).
- Memory scope: component:REPO_FOLDER.
- Many of these repos have only a short CHANGELOG.md and MEMORY.md. A repo with nothing to import is fine: do Steps 2 to 5 and say so.
- Append only the short "Viber (mirror mode)" section to CLAUDE.md; change nothing else in it.
- Anything you cannot parse cleanly: do not guess. List it with file and line.

Stop points: (1) after Step 2 if Viber is unreachable or the token is refused; (2) after the dry-run table, wait for me to say
"import"; (3) after the import, show the verification and stop.

Final report: files created or changed; per file the counts parsed / created / skipped / invalid; what was not imported and why;
what I must do next; anything unverified.
~~~

## 4. Switch over: a standalone repo

For a repo **no pipeline maintains**. It makes Viber the source of truth and freezes the old files.

~~~text
VIBER_DIR = D:/MyWorx/Projects/Viber        <- edit: the folder of this machine's Viber checkout
VIBER_URL = http://localhost:8088
PROJECT_KEY = <Viber project, e.g. padelers; it is created if it does not exist>
PROJECT_NAME = <display name>
COMPONENT_KEY = <this repo's folder name>
KIND = <service | library | plugin | app | infra | chart | docs | tool>
REPO = <owner/name>

Task: connect this repository to Viber in SWITCH-OVER mode: Viber becomes the single source of truth for bugs, changes, decisions
and memory, and the old tracking files are imported, then frozen. Do not commit.

First check that no pipeline maintains this repo's tracking files: if Implementation/Pipeline.md exists, or .claude/commands has
pipeline commands such as /spec, /plan-tasks, /flow or /bug, STOP and tell me to use the mirror prompt instead. Freezing files a
pipeline writes would break it.

Otherwise read VIBER_DIR/project-scaffold and follow its "Scaffold Prompt" Steps 1 to 7 exactly, in switch-over mode, with the
answers above already given. Import whichever of BUGS.md, CHANGELOG.md, MEMORY.md, the ADR file, Learnings.md and ESCALATIONS.md
exist; if none exist, skip Step 6. Write all of Step 5's files, including the seven slash commands and the full CLAUDE.md
(merging with any existing one: keep everything in it that is not about the old tracking files). Freeze the imported files only
after the counts match and I confirm.

Stop points: (1) after Step 2 if Viber is unreachable or the token is refused; (2) after the dry-run table, wait for "import";
(3) after the import and verification, wait for my confirmation before freezing anything.

Final report: files created, changed or frozen; per file the counts parsed / created / skipped / invalid; what I must do next; and
anything unverified.
~~~

## 5. Re-sync a mirrored repo

Run it in a repo that was mirrored, whenever its markdown files have grown. It only adds what is new.

~~~text
VIBER_DIR = D:/MyWorx/Projects/Viber        <- edit: the folder of this machine's Viber checkout

Task: re-run this repo's mirror import into Viber and report only what is new. Change no file and do not commit.

Take the project from VIBER_PROJECT in .claude/settings.local.json, the component key and mode from the "Viber (mirror mode)"
section of CLAUDE.md, and the Viber URL from VIBER_URL in the same settings file. Read VIBER_DIR/project-scaffold Step 6 and repeat
exactly the import this repo had before (same files, same mapping, same id prefixes, same scopes), including the dry run first.

Report per file: parsed / newly created / skipped. Then stop and wait for me to say "import" before the real run, unless every dry
run shows created = 0. Stop and ask instead of importing if any file shows created > 50, or skipped is lower than the total
created by the earlier import of that file (something was removed or renumbered in the source). Never delete anything from Viber.
~~~

## 6. Audit an import

Paste it into a **separate** session in the same repo, so the check is independent of the one that did the import.

~~~text
VIBER_DIR = D:/MyWorx/Projects/Viber        <- edit: the folder of this machine's Viber checkout

Task: independently verify what was imported from this repo into Viber. This is READ-ONLY: do not edit any file, and make no POST,
PUT, PATCH or DELETE call to Viber, only GET.

Take the project from VIBER_PROJECT in .claude/settings.local.json and the Viber URL from VIBER_URL there (default
http://localhost:8088); send "Authorization: Bearer $VIBER_TOKEN" when that variable is set. Read VIBER_DIR/project-scaffold Step 6 for
the mapping, then for each kind below compare the source file with Viber:

- BUGS.md vs GET /v1/projects/<p>/items?kind=bug&limit=1000 (keep the records whose "source" starts with this repo's component key;
  GET /v1/projects/<p>/items/<key> returns one in full, body included)
- the ADR file vs GET /v1/projects/<p>/decisions (has "source") and GET /v1/projects/<p>/decisions/<key> (every field)
- CHANGELOG.md vs GET /v1/projects/<p>/changes?limit=500 (has "source", "source_ref", "body") and GET /v1/projects/<p>/views/changelog
- MEMORY.md vs GET /v1/projects/<p>/memory/rules (has "scope" and "source")
- Learnings.md vs GET /v1/projects/<p>/memory/facts

Check: (1) counts agree (source entries, Viber records for this repo); (2) five records per kind chosen at random match field by field
(id or key, title or summary, status, date, severity, text); (3) nothing is in Viber that is not in the source, and nothing in the
source is missing from Viber; (4) rules carry the right scope (component:<this repo>, or project for a hub repo); (5) three changelog
dates render with the right entries.

Report a table of every discrepancy with the source file and line and the Viber key. End with one verdict:
MATCH, MINOR DIFFERENCES (list them), or DO NOT TRUST (say why). Do not fix anything; tell me what you would change.
~~~

## 7. Fork kickoff

Paste it as the **first message of a forked session**, with the task filled in.

~~~text
You are a fork of an earlier session, and you do not know what its sibling sessions have learned since. Before you do anything:

1. Read the Viber memory at the top of this conversation: the rules, the handoffs from earlier or sibling sessions, who else is
   active and which files they are editing, the open bugs and the recent decisions.
2. Run /status.
3. Search Viber for the task below (/recall, or viber_recall with project and a few key words), so you do not redo or contradict
   earlier work.

My task for you: <TASK>

Then tell me in at most five lines: the task as you understand it, the handoffs and decisions that matter to it, and any other
active session that touches the same files. Wait for my go-ahead only if something conflicts; otherwise carry on.

While you work, follow the Viber section of this repo's CLAUDE.md for what to log and where (a repo in mirror mode keeps its
markdown files; a repo that switched over uses /quick, /bug, /remember and /decide). If another active session edits a file you are
about to change, stop and tell me. When you finish, use Prompt 8's closeout: /handoff first.
~~~

## 8. Closeout

Paste it, or type `/handoff` where that command exists, before ending any session whose work should carry on.

~~~text
Before you finish, hand off:

1. Call viber_handoff (or /handoff) with project from the Viber memory at the top of this conversation and session_id set to your tag
   (for example S1). Include a short factual summary of what you changed and the files involved; the decisions you made and why; open
   questions; next steps; and anything a sibling session should not redo. No code.
2. Update the places this repo's CLAUDE.md says to update (a mirrored repo's markdown files; a switched-over repo's records through
   /quick, /bug and /decide).
3. Give me a five-line summary and say what is unfinished or unverified. Do not commit unless I asked.
~~~

---

## If something goes wrong

- **"Viber unreachable" or 401 in Step 2:** the container is not running (`docker compose ps` in the Viber folder), or `VIBER_TOKEN` is
  not set in the environment Claude Code started in. Set it, restart Claude Code, and paste the prompt again. The import is repeatable.
- **A dry run shows `skipped` above 0 on a file never imported:** a key collides with another repo's data. Do not import. Prefix the
  repo's own ids as the prompt says, and run the dry run again.
- **A real import went wrong:** there is no delete endpoint on purpose (the history is append-only). Re-importing never duplicates, so
  fix the mapping and run again for the missing records; for records that were stored wrongly, tell me which and I will correct them in
  the database with a one-off statement, since imports are identified by their source and reference.
- **The hook never registers a session:** set `VIBER_DEBUG=1` in your environment, start a new session, and the hook prints why it
  failed (it never blocks a session).
