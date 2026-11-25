"""Check that every SEC-NNN row of SECURITY.md is in Viber (imported earlier by import-sbos.ps1). Read-only."""
import re
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0] if "/" in __file__ else ".")
from v2_common import *  # noqa: F401,F403

text = fix_mojibake(read_text("SECURITY.md"))
ids = re.findall(r"^\|\s*(SEC-\d+)\s*\|", text, re.M)
rows = {r["key"]: r for r in list_items()}
missing = [i for i in ids if i not in rows]
say(f"SECURITY.md SEC rows {len(ids)} (unique {len(set(ids))}); in Viber {len(ids) - len(missing)}; missing {missing or 'none'}")
mirror = set(re.findall(r"^\| (BUG-\d+) \|", read_text("BACKLOG.md"), re.M))
bugs = set(re.findall(r"^### (BUG-\d+)", read_text("BUGS.md"), re.M))
say("BUGS.md bugs absent from the BACKLOG.md Bugs mirror:", sorted(bugs - mirror))
