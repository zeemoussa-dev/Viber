"""Import the v3 repositories' MEMORY.md, CHANGELOG.md, CLAUDE.md and the sb-orchestration ledgers into Viber.

Run in a throwaway container (E:\\MyWorx mounted read-only):
  docker run --rm -v E:\\MyWorx:/work:ro python:3.12-slim python /work/Viber/tools/import_v3repos.py [--apply] [--report]

Default is a dry run (nothing written). --apply writes (idempotent by source + source_ref). Standard library only.
Writes only rows tagged with source 'v3repos:*'; never edits or deletes existing rows (it may create components).
"""
import hashlib, json, os, re, sys, urllib.request, urllib.error
from collections import Counter, defaultdict

ROOT = "/work/sbos-v3"
VIBER_DIR = "/work/Viber"
BASE = os.environ.get("VIBER_URL", "http://host.docker.internal:8088")
PROJECT = "sbos"
APPLY = "--apply" in sys.argv
REPORT = "--report" in sys.argv
ACTOR = "import-v3repos"
SKIP_DIRS = {"backups", "sbctl-backups", "sbctl-demo-backups", "wt"}
# worktrees of sb-console: their files are imported under the parent's component, deduplicated against it
WORKTREE_OF = {"sb-console-billing": "sb-console", "sb-console-tenants-auth": "sb-console"}
BOILER_MEMORY = re.compile(r"^Repository created empty; code is copied from v2", re.I)

# ---------------------------------------------------------------- splitter (copy of viber.atoms)
_BULLET = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+")
_SENT = re.compile(r"(?<=[.;:!?])\s+")


def _statements(text):
    blocks, cur = [], ""
    for raw in (text or "").splitlines():
        s = raw.strip()
        if not s:
            if cur:
                blocks.append(cur)
            cur = ""
        elif _BULLET.match(raw):
            if cur:
                blocks.append(cur)
            cur = _BULLET.sub("", raw).strip()
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        blocks.append(cur)
    return blocks


def _wrap(sentence, limit):
    if len(sentence) <= limit:
        return [sentence]
    pieces, cur = [], ""
    for w in sentence.split():
        if cur and len(cur) + 1 + len(w) > limit:
            pieces.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        pieces.append(cur)
    return pieces


def split_atoms(text, limit):
    atoms = []
    for line in _statements(text):
        if len(line) <= limit:
            atoms.append(line)
            continue
        cur = ""
        for sent in _SENT.split(line):
            for piece in _wrap(sent, limit):
                if cur and len(cur) + 1 + len(piece) > limit:
                    atoms.append(cur)
                    cur = piece
                else:
                    cur = f"{cur} {piece}".strip()
        if cur:
            atoms.append(cur)
    return atoms


# ---------------------------------------------------------------- API
def token():
    for line in open(f"{VIBER_DIR}/.env", encoding="utf-8"):
        if line.startswith("VIBER_TOKEN="):
            return line.split("=", 1)[1].strip()
    return ""


TOKEN = token()


def api(method, path, body=None):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {TOKEN}", "X-Viber-Actor": ACTOR,
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code} {e.read()[:300]!r}")


def h(text, n=10):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


# ---------------------------------------------------------------- parsing
def items_of(text):
    """Top-level list items (col 0 bullet or number) and plain paragraphs, with their section. Indented lines and
    nested bullets continue the item. Yields (section, item_text). Skips headings, tables, the title and fences."""
    out, section, cur, fence = [], "", None, False

    def flush():
        nonlocal cur
        if cur is not None and cur.strip():
            out.append((section, cur.strip()))
        cur = None

    for raw in text.split("\n"):
        if raw.strip().startswith("```"):
            fence = not fence
            if cur is not None:
                cur += " " + raw.strip()
            continue
        if fence:
            if cur is not None:
                cur += " " + raw.strip()
            continue
        if re.match(r"^#{1,6}\s", raw):
            flush()
            if raw.startswith("# ") and not section:
                section = ""
            else:
                section = raw.lstrip("#").strip()
            continue
        if not raw.strip():
            flush()
            continue
        if raw.lstrip().startswith("|") or raw.strip().startswith("<!--"):
            flush()
            continue
        if re.match(r"^(?:[-*\u2022]|\d+[.)])\s+", raw):
            flush()
            cur = _BULLET.sub("", raw).strip()
        elif raw.startswith((" ", "\t")):
            if cur is None:
                cur = raw.strip()
            else:
                piece = _BULLET.sub("", raw).strip() if _BULLET.match(raw) else raw.strip()
                cur += ("; " if _BULLET.match(raw) else " ") + piece
        else:
            if cur is not None and not cur.endswith(":") and False:
                pass
            flush()
            cur = raw.strip()
    flush()
    return out


def table_rows(text):
    rows = []
    for raw in text.split("\n"):
        s = raw.strip()
        if s.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", s):
            rows.append([c.strip() for c in s.strip("|").split("|")])
    return rows


def parse_changelog(text):
    """Entries: every level-1/2 heading except the file title. Returns (entries, preamble_nonblank_lines)."""
    entries, cur, pre = [], None, 0
    for raw in text.split("\n"):
        m = re.match(r"^(#{1,2})\s+(.*)$", raw)
        if m:
            title = m.group(2).strip()
            if m.group(1) == "#" and title.lower() == "changelog":
                continue
            cur = {"heading": title, "lines": []}
            entries.append(cur)
        elif cur is not None:
            cur["lines"].append(raw)
        elif raw.strip():
            pre += 1
    return entries, pre


# ---------------------------------------------------------------- planning
plan = []          # dicts: kind, record, file(label), repo, entry_id
file_stats = defaultdict(lambda: Counter())     # (type, repo) -> counts
notes = []         # not imported, with reasons
seen_content = {}  # dedupe across worktrees: (component, kind, key) -> repo


def add(kind, rec, ftype, repo, entry):
    plan.append({"kind": kind, "rec": rec, "ftype": ftype, "repo": repo, "entry": entry})


def fact_rows(text, scope, subject, source, ref, trust="work", valid_from=None):
    out = []
    for n, a in enumerate(split_atoms(text, 500), 1):
        r = {"text": a, "scope": scope, "subject": subject, "trust": trust, "source": source, "source_ref": f"{ref}#{n}"}
        if valid_from:
            r["valid_from"] = valid_from
        out.append(("facts", r))
    return out


def rule_rows(text, category, scope, subject, source, ref):
    """First statement (<=400) is the proposed rule; the rest (if any) become facts. Lossless."""
    atoms = split_atoms(text, 400)
    out = []
    for n, a in enumerate(atoms, 1):
        if n == 1:
            out.append(("rules", {"text": a, "category": category, "scope": scope, "status": "proposed",
                                  "proposed_by": ACTOR, "source": source, "source_ref": f"{ref}#{n}"}))
        else:
            out.append(("facts", {"text": a, "scope": scope, "subject": subject, "trust": "work",
                                  "source": source, "source_ref": f"{ref}#{n}"}))
    return out


def load_repos():
    repos = []
    for name in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, name)
        if name in SKIP_DIRS or not os.path.isdir(d):
            continue
        if os.path.exists(os.path.join(d, ".git")):
            repos.append(name)
    return repos


def comp_of(repo):
    return WORKTREE_OF.get(repo, repo)


def plan_memory(repo, text):
    comp, scope, src = comp_of(repo), f"component:{comp_of(repo)}", "v3repos:MEMORY.md"
    st = file_stats[("MEMORY.md", repo)]
    st["files"] += 1
    real = 0
    for section, item in items_of(text):
        if not section and item.startswith("Framework memory for"):
            st["boilerplate_prose"] += 1   # "Framework memory for X: true on every install ..." intro line
            continue
        section = section or "Notes"      # some repos keep bullets with no section heading
        m = re.match(r"^\[(\d{4}-\d{2}-\d{2})\]\s*(.*)$", item, re.S)
        date, body = (m.group(1), m.group(2)) if m else (None, item)
        if BOILER_MEMORY.match(body):
            st["boilerplate"] += 1
            continue
        st["entries"] += 1
        ident = ("MEMORY", comp, h(body, 16))
        if ident in seen_content:
            st["duplicate_of_" + seen_content[ident]] += 1
            continue
        seen_content[ident] = repo
        real += 1
        ref = f"{repo}/MEMORY.md:{section}:{h(body)}"
        sec = section.lower()
        if sec.startswith("constraint"):
            rows = rule_rows(body, "constraint", scope, comp, src, ref)
        elif sec.startswith("pattern"):
            rows = rule_rows(body, "pattern", scope, comp, src, ref)
        else:  # Decisions and anything else: descriptive facts, dated
            vf = f"{date}T00:00:00Z" if date else None
            rows = fact_rows(body, scope, comp, src, ref, valid_from=vf)
        for k, r in rows:
            add(k, r, "MEMORY.md", repo, ref)
    st["imported_entries"] += real
    if st["entries"] == 0:
        notes.append(f"{repo}/MEMORY.md: pure scaffold (no entry beyond the template)")


def plan_changelog(repo, text):
    comp, src = comp_of(repo), "v3repos:CHANGELOG.md"
    st = file_stats[("CHANGELOG.md", repo)]
    st["files"] += 1
    entries, pre = parse_changelog(text)
    if pre:
        st["preamble_lines"] += pre
    seen_heading = Counter()
    for e in entries:
        body = "\n".join(e["lines"]).strip()
        heading = e["heading"]
        st["entries"] += 1
        dm = re.search(r"\d{4}-\d{2}-\d{2}", heading)
        if not dm:
            st["invalid"] += 1
            notes.append(f"{repo}/CHANGELOG.md: heading without a date: {heading[:80]!r}")
            continue
        vm = re.search(r"\((\d+\.\d+\.\d+[^)]*)\)", heading) or re.match(r"^v?(\d+\.\d+\.\d+\S*)", heading)
        version = vm.group(1) if vm else None
        seen_heading[heading] += 1
        ident = ("CHANGELOG", comp, heading, h(body, 16))
        if ident in seen_content:
            st["duplicate_of_" + seen_content[ident]] += 1
            continue
        seen_content[ident] = repo
        first = ""
        for _, it in items_of(body)[:1]:
            first = it
        summary = heading
        if not vm and first:
            summary = f"{heading} \u2014 {first}"
        summary = summary[:400]
        rec = {"summary": summary, "occurred_on": dm.group(0), "kind": "change", "body": first[:450],
               "details": body, "component_key": comp, "source": src,
               "source_ref": f"{repo}:{heading}:{seen_heading[heading]}"}
        if version:
            rec["version"] = version
        st["imported_entries"] += 1
        add("changes", rec, "CHANGELOG.md", repo, rec["source_ref"])


TEMPLATE_BULLETS = set()


def claude_template(repos):
    c = Counter()
    for r in repos:
        p = os.path.join(ROOT, r, "CLAUDE.md")
        if os.path.exists(p):
            for sec, it in items_of(read(p)):
                if sec in ("Boundaries", "Rules"):
                    c[it] += 1
    return {t for t, n in c.items() if n >= 5}


def plan_claude(repo, text, path_label=None, comp=None, ftype="CLAUDE.md", src="v3repos:CLAUDE.md"):
    comp = comp or comp_of(repo)
    scope = f"component:{comp}"
    st = file_stats[(ftype, repo)]
    st["files"] += 1
    for section, item in items_of(text):
        if item in TEMPLATE_BULLETS:
            st["boilerplate"] += 1
            continue
        if not section:
            st["entries"] += 1   # the title/description line, or intro prose
            ident = ("CLAUDE-intro", comp, h(item, 16))
            if ident in seen_content:
                st["duplicate_of_" + seen_content[ident]] += 1
                continue
            seen_content[ident] = repo
            ref =f"{repo}/{ftype}:intro:{h(item)}"
            for k, r in fact_rows(item, scope, comp, src, ref):
                add(k, r, ftype, repo, ref)
            st["imported_entries"] += 1
            continue
        st["entries"] += 1
        ident = ("CLAUDE", comp, h(item, 16))
        if ident in seen_content:
            st["duplicate_of_" + seen_content[ident]] += 1
            continue
        seen_content[ident] = repo
        ref = f"{repo}/{ftype}:{section}:{h(item)}"
        cat = "constraint" if section == "Boundaries" else "preference"
        for k, r in rule_rows(item, cat, scope, comp, src, ref):
            add(k, r, ftype, repo, ref)
        st["imported_entries"] += 1


def plan_ledger(name, text, subject_scope="project"):
    """STATUS.md and the (currently empty) ledgers: one statement per item, as facts (scope project, trust work)."""
    src = f"v3repos:{name}"
    st = file_stats[(name, "sb-orchestration")]
    st["files"] += 1
    for section, item in items_of(text):
        if not section and name != "STATUS.md":
            st["boilerplate_prose"] += 1   # the one-line description under the title
            continue
        st["entries"] += 1
        ref = f"sb-orchestration/{name}:{section}:{h(item)}"
        text_ = f"{item}"
        for k, r in fact_rows(text_, "project", section or name, src, ref):
            add(k, r, name, "sb-orchestration", ref)
        st["imported_entries"] += 1
    for cols in table_rows(text)[1:]:
        st["entries"] += 1
        line = " | ".join(c.strip("`") for c in cols)
        ref = f"sb-orchestration/{name}:row:{h(line)}"
        for k, r in fact_rows(line, "project", name, src, ref):
            add(k, r, name, "sb-orchestration", ref)
        st["imported_entries"] += 1
    if name != "STATUS.md" and st["entries"] == 0:
        notes.append(f"sb-orchestration/{name}: empty ledger (title and description only)")


def plan_projects(text, known):
    src = "v3repos:PROJECTS.md"
    st = file_stats[("PROJECTS.md", "sb-orchestration")]
    st["files"] += 1
    for section, item in items_of(text):
        st["entries"] += 1
        ref = f"sb-orchestration/PROJECTS.md:{section}:{h(item)}"
        for k, r in fact_rows(item, "project", "v3 projects", src, ref):
            add(k, r, "PROJECTS.md", "sb-orchestration", ref)
        st["imported_entries"] += 1
    new_components = []
    rows = [r for r in table_rows(text)][1:]
    for cols in rows:
        if len(cols) < 3:
            continue
        key = cols[0].strip("`")
        st["entries"] += 1
        st["imported_entries"] += 1
        ref = f"sb-orchestration/PROJECTS.md:row:{key}"
        for k, r in fact_rows(f"{key} ({cols[1]}): {cols[2]}", "project", key, src, ref):
            add(k, r, "PROJECTS.md", "sb-orchestration", ref)
        if key not in known:
            new_components.append({"key": key, "kind": "service", "repo": key})
    return new_components


# ---------------------------------------------------------------- main
def main():
    repos = load_repos()
    TEMPLATE_BULLETS.update(claude_template(repos))
    existing = {c["key"] for c in api("GET", f"/v1/projects/{PROJECT}/components")}
    need = []
    for r in repos:
        if comp_of(r) not in existing and comp_of(r) not in [n["key"] for n in need]:
            need.append({"key": comp_of(r), "kind": "service", "repo": comp_of(r)})
    known = existing | {n["key"] for n in need}

    for r in repos:
        d = os.path.join(ROOT, r)
        for fname, fn in (("MEMORY.md", plan_memory), ("CHANGELOG.md", plan_changelog), ("CLAUDE.md", plan_claude)):
            p = os.path.join(d, fname)
            if os.path.exists(p):
                fn(r, read(p))
            else:
                notes.append(f"{r}/{fname}: missing")
    orch = os.path.join(ROOT, "sb-orchestration")
    for name in ("BACKLOG.md", "BUGS.md", "ESCALATIONS.md", "REVIEW-QUEUE.md", "STATUS.md"):
        plan_ledger(name, read(os.path.join(orch, name)))
    need += [n for n in plan_projects(read(os.path.join(orch, "PROJECTS.md")), known) if n["key"] not in known]
    # Viber is its own product with its own Viber project: nothing about it is imported here (a re-run must never copy it
    # back into this project).
    # README.md files: left alone
    notes.append("README.md (all repos): not imported by instruction (prose belongs to its repo)")
    impl = os.path.join(orch, "Implementation")
    for dp, _, fs in os.walk(impl):
        for f in fs:
            p = os.path.join(dp, f)
            notes.append(f"sb-orchestration/Implementation/{os.path.relpath(p, impl).replace(os.sep, '/')}: "
                         f"{os.path.getsize(p)} bytes, " + ("ADR.md already imported (ADR-v3.NNN)" if f == "ADR.md"
                                                          else "template with placeholders, no real content; not imported"))

    # ---- components
    print(f"mode: {'APPLY' if APPLY else 'DRY RUN'}  repos={len(repos)}  planned rows={len(plan)}")
    for comp in need:
        print("component needed:", comp["key"])
        if APPLY:
            api("POST", f"/v1/projects/{PROJECT}/components", comp)

    # ---- import per source and kind, in batches
    results = defaultdict(lambda: Counter())
    invalid_all = []
    groups = defaultdict(list)
    for p in plan:
        groups[(p["rec"]["source"], p["kind"])].append(p)
    for (source, kind), items in groups.items():
        for i in range(0, len(items), 100):
            chunk = items[i:i + 100]
            for dry in ([True, False] if APPLY else [True]):
                if dry is False and results_invalid(invalid_all, source, kind):
                    pass
                res = api("POST", f"/v1/projects/{PROJECT}/import/{kind}?dry_run={'true' if dry else 'false'}",
                          {"source": source, "records": [c["rec"] for c in chunk]})
                if dry:
                    for bad in res["invalid"]:
                        c = chunk[bad["index"]]
                        invalid_all.append((c["ftype"], c["repo"], c["entry"], bad["error"]))
                        file_stats[(c["ftype"], c["repo"])]["invalid_rows"] += 1
                if dry == (not APPLY):
                    for c in chunk:
                        pass
                    results[(source, kind)]["created"] += res["created"]
                    results[(source, kind)]["skipped"] += res["skipped"]
                    results[(source, kind)]["invalid"] += len(res["invalid"])
    # ---- coverage table
    print("\nCOVERAGE (per file type; entries found, entries imported, boilerplate, duplicates, invalid, rows planned)")
    rows_by = Counter((p["ftype"], p["repo"]) for p in plan)
    agg = defaultdict(Counter)
    for (ft, repo), st in sorted(file_stats.items()):
        agg[ft].update(st)
        agg[ft]["rows"] += rows_by[(ft, repo)]
    for ft, c in agg.items():
        dup = sum(v for k, v in c.items() if k.startswith("duplicate_of_"))
        print(f"{ft:18} files={c['files']:3} entries={c['entries']:4} imported={c['imported_entries']:4} "
              f"boilerplate={c['boilerplate']:4} dup={dup:3} invalid_entries={c['invalid']} invalid_rows={c['invalid_rows']} rows={c['rows']}")
    print("\nAPI RESULT (" + ("apply" if APPLY else "dry run") + "): source/kind created skipped invalid")
    for k, c in sorted(results.items()):
        print(" ", k, dict(c))
    if REPORT:
        print("\nPER REPO")
        for (ft, repo), st in sorted(file_stats.items()):
            print(f"  {ft:16} {repo:32} {dict(st)}")
        print("\nTEMPLATE BULLETS (CLAUDE.md boilerplate):", len(TEMPLATE_BULLETS))
    print("\nNOT IMPORTED / NOTES")
    for n in notes:
        print(" -", n)
    for i in invalid_all:
        print(" - INVALID", i)
    json.dump({"planned_rows": len(plan)}, open("/tmp/v3repos_plan.json", "w"))


def results_invalid(*a):
    return False


if __name__ == "__main__":
    main()
