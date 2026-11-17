"""Bundle a stale page's selected claims with the code changes that selected them.

Stale mode's triage input. docs-stale says a page MAY be wrong: an edit landed
near a line it cites, or in a file it cites whole. Most of those edits leave
every claim true, so before a claim is re-verified a cheap model reads it next
to the hunks that touched it and sorts it into `unaffected` (only its evidence
moves) or `check`. This builds that model's input, so the model reads a few
hundred lines instead of whole files.

Usage: docs-stale-bundle [--root <repo>] [--config <file>] [--out <dir>] <page.md>...
       docs-stale-bundle --apply <bundle.json> <triage.json> <stage3-out.json>

Prints one JSON object per page, one per line; with --out, writes each to
<dir>/<page path under docs_dir with / as __>.json indented, one hunk line per
line, so a reader that pages by line can read a large bundle in parts:
  {"page", "commit",
   "claims": [{"id", "claim", "verdict", "evidence",
               "moved": {old_ev: new_ev | null},  # null: the cited lines changed
               "diffs": [key, ...],               # the hunks that selected it
               "check": bool, "why"}],            # true: triage may not clear it
   "surface": [key, ...],   # added lines in a public-surface file this page owns
   "diffs": {key: ["<file>", "<hunk line with old/new line numbers>", ...]}}

A claim is forced to `check` when its hunks exceed MAX_LINES (too much to
judge cheaply), when its file is gone, or when it cites the file with no
line and the page has no sidecar. Line selection matches docs-stale.

--apply turns a triage result (the skill's prompts/triage.md) into stage-3
input for `docs-provenance --merge`: every drift-only and `unaffected` claim
keeps its verdict with its evidence moved. It prints the claim ids still to
verify and the surface keys to document, as JSON. A claim whose cited lines
changed and whose triage gave no new location stays `check`.
"""
import json
import os
import re
import sys

from . import config as conf
from . import freshness as df

MAX_LINES = 250  # hunk lines one claim may carry before it skips triage
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def rendered_hunks(root, commit, path):
    """[(old_start, old_count, text, added)] from `git diff -U3 <commit> -- path`, each
    line prefixed with its old and new line numbers."""
    out = df.git(root, "diff", "-U3", commit, "--", path, check=False)
    hunks, cur, o, n = [], None, 0, 0
    for line in out.split("\n"):
        m = HUNK_RE.match(line)
        if m:
            o, n = int(m.group(1)), int(m.group(3))
            cur = [o, int(m.group(2) or 1), [line], 0]
            hunks.append(cur)
            continue
        if cur is None or not line or line.startswith("\\"):
            continue
        tag = line[0]
        if tag == "-":
            cur[2].append(f"{o:>5}      -{line[1:]}")
            o += 1
        elif tag == "+":
            cur[2].append(f"      {n:>5} +{line[1:]}")
            n, cur[3] = n + 1, cur[3] + 1
        else:
            cur[2].append(f"{o:>5} {n:>5}  {line[1:]}")
            o, n = o + 1, n + 1
    return [(a, c, "\n".join(t), added) for a, c, t, added in hunks]


def overlaps(start, count, a, b):
    lo, hi = start, start + max(count, 1) - 1
    return lo <= b + df.WINDOW and hi >= a - df.WINDOW


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def surface_owners(cfg):
    """Public-surface file -> the page with the most claims citing it."""
    surface = set(df.surface(cfg))
    counts = {}
    for d, _, files in os.walk(cfg.abs(cfg.provenance)):
        for f in sorted(files):
            if not f.endswith(".json"):
                continue
            side = load_json(os.path.join(d, f))
            for c in side.get("claims", []):
                for ev in c.get("evidence", []):
                    p = df.split_ev(ev)[0]
                    if p in surface:
                        n = counts.setdefault(p, {})
                        n[side.get("page")] = n.get(side.get("page"), 0) + 1
    return {p: max(c, key=c.get) for p, c in counts.items()}


def bundle(cfg, page, owners):
    root = cfg.root
    commit, sources = df.frontmatter(cfg.abs(page))
    side = df.load_sidecar(cfg, page) or {}
    claims = side.get("claims", [])
    diffs, out_claims, surface = {}, [], []

    cache = {}

    def file_hunks(src):
        if src not in cache:
            cache[src] = (df.hunks(root, commit, None, src), rendered_hunks(root, commit, src))
        return cache[src]

    def key(src, i, text):
        k = f"{src}#{i}"
        diffs.setdefault(k, [src] + text.split("\n"))
        return k

    for c in claims:
        keys, moved, why, check = [], {}, [], False
        for ev in c.get("evidence", []):
            src, a, b = df.split_ev(ev)
            if not os.path.exists(os.path.join(root, src)):
                moved[ev], check = None, True
                why.append(f"{src} is gone")
                continue
            hs, rh = file_hunks(src)
            if not hs:
                continue
            if a is None:
                keys += [key(src, i, t) for i, (_, _, t, _) in enumerate(rh)]
                why.append(f"{src} cited without a line")
                continue
            if not df.touches(hs, a, b):
                a2, b2 = df.translate(hs, a), df.translate(hs, b)
                if (a2, b2) != (a, b):
                    moved[ev] = f"{src}:{a2}" + (f"-{b2}" if b2 != a2 else "")
                continue
            keys += [key(src, i, t) for i, (s, n, t, _) in enumerate(rh) if overlaps(s, n, a, b)]
            a2, b2 = df.translate(hs, a), df.translate(hs, b)
            moved[ev] = None if a2 is None or b2 is None else \
                f"{src}:{a2}" + (f"-{b2}" if b2 != a2 else "")
            why.append(f"{src} lines {a}" + (f"-{b}" if b != a else "") + " touched")
        if not keys and not check:
            if moved:
                out_claims.append({"id": c["id"], "claim": c.get("claim", ""),
                                   "verdict": c.get("verdict"), "evidence": c.get("evidence", []),
                                   "moved": moved, "diffs": [], "check": False, "why": "drift only"})
            continue
        keys = list(dict.fromkeys(keys))
        size = sum(len(diffs[k]) - 1 for k in keys)
        if size > MAX_LINES:
            check = True
            why.append(f"{size} changed lines, over {MAX_LINES}")
        out_claims.append({"id": c["id"], "claim": c.get("claim", ""), "verdict": c.get("verdict"),
                           "evidence": c.get("evidence", []), "moved": moved,
                           "diffs": [] if check else keys, "check": check, "why": "; ".join(why)})

    for src in sources:
        if owners.get(src) == page and os.path.exists(os.path.join(root, src)):
            surface += [key(src, i, t) for i, (_, _, t, added) in
                        enumerate(file_hunks(src)[1]) if added]

    used = {k for c in out_claims for k in c["diffs"]} | set(surface)
    return {"page": page, "commit": commit, "claims": out_claims, "surface": surface,
            "diffs": {k: v for k, v in diffs.items() if k in used}}


def apply(bundle_path, triage_path, out_path):
    b, tri = load_json(bundle_path), load_json(triage_path)
    if isinstance(tri, list):  # the triage prompt returns one object per page
        tri = next((t for t in tri if t.get("page") == b["page"]), {})
    verdicts = {r["id"]: r for r in tri.get("results", [])}
    results, check = [], []
    for c in b["claims"]:
        t = verdicts.get(c["id"], {})
        cleared = not c["check"] and (c["why"] == "drift only" or t.get("triage") == "unaffected")
        given = list(t.get("evidence") or [])
        ev = []
        for e in c["evidence"]:
            new = c["moved"].get(e, e)
            if new is None:
                if not given:
                    cleared = False
                    break
                continue
            ev.append(new)
        if not cleared:
            check.append(c["id"])
            continue
        results.append({"id": c["id"], "verdict": c["verdict"], "evidence": " ".join(ev + given)})
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"results": results}, f, indent=1)
    document = [s["key"] for s in tri.get("surface", []) if s.get("triage") == "document"]
    print(json.dumps({"page": b["page"], "cleared": len(results), "check": check,
                      "document": document}))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--apply"]:
        if len(argv) != 4:
            sys.exit(__doc__)
        apply(*argv[1:])
        return 0
    root, config, flags, pages = conf.common_args(argv, {"--out": True})
    if not pages:
        sys.exit(__doc__)
    cfg = conf.load(root, config)
    out = flags.get("--out")
    owners = surface_owners(cfg)
    for p in pages:
        b = bundle(cfg, p, owners)
        if out is None:
            print(json.dumps(b))
            continue
        slug = p[len(cfg.docs) + 1:].rsplit(".", 1)[0].replace("/", "__")
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, slug + ".json"), "w", encoding="utf-8") as f:
            json.dump(b, f, indent=1)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
