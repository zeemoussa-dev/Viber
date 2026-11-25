import os, re, sys
ROOT = "/work/sbos-v3"
for r in sorted(os.listdir(ROOT)):
    p = os.path.join(ROOT, r, "CHANGELOG.md")
    if not os.path.isfile(p):
        continue
    lines = open(p, encoding="utf-8").read().split("\n")
    hs = [l for l in lines if l.startswith("#")]
    odd = [l for l in hs if not re.match(r"^## \d{4}-\d{2}-\d{2}", l)]
    print(r, len(hs), "odd:", [o[:90] for o in odd][:6])
    if r in sys.argv[1:]:
        print("\n".join(lines[:int(os.environ.get("N", "30"))]))
