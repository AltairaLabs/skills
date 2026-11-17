"""Record a docs page's verification provenance from /docs-review output.

Writes the page's `verified` frontmatter (commit + the repo files its claims
were verified against) and the claim-level sidecar
<provenance_dir>/<page>.json that `/docs-review --stale` uses to re-verify
only the claims whose evidence changed. docs-stale reads the frontmatter.

Usage:
  docs-provenance [--config <file>] [--merge] <page.md> <stage2.json> <stage3.json> <commit>

<page.md> is repo-relative; the command runs from the repo root whatever the
caller's working directory. <commit> may be any ref; it is resolved to a sha,
which must be on origin's default branch: a branch commit is gone once the PR
is squash-merged, and the page then has no baseline (docs-stale's
`unknown-commit`). A missing <stage2.json> is fine (claim text is then kept
from the sidecar).

--merge  update an existing sidecar: claims whose ids appear in stage3 are
         replaced, every other claim is kept, and the page's sources are
         rebuilt from all of them. Stale mode uses this after re-verifying
         only the claims whose evidence changed.
"""
import json
import os
import re
import subprocess
import sys

from . import config as conf
from . import freshness as df


def resolve(ref):
    try:
        return subprocess.run(["git", "rev-parse", "--verify", ref + "^{commit}"],
                              check=True, capture_output=True, text=True).stdout.strip()
    except subprocess.CalledProcessError:
        sys.exit(f"cannot resolve commit {ref!r}")


def require_on_default_branch(sha, base_branch):
    """Exit unless sha is reachable from origin's default branch. Every candidate
    ref that exists is tried, so a stale origin/HEAD does not hide origin/main."""
    cands = ["origin/HEAD"] + [f"origin/{b}" for b in dict.fromkeys((base_branch, "main", "master"))]
    refs = [r for r in cands
            if subprocess.run(["git", "rev-parse", "--verify", "-q", r],
                              capture_output=True).returncode == 0]
    if not refs:
        sys.exit(f"cannot find origin's default branch ({', '.join(cands)})")
    for ref in refs:
        r = subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return
        if r.returncode != 1:  # not a "no": missing history, e.g. a shallow clone
            sys.exit(f"cannot tell whether {sha} is on {ref}: {r.stderr.strip()}")
    sys.exit(f"commit {sha} is not on {' or '.join(refs)}. A branch commit is discarded when "
             f"the PR is squash-merged, leaving the page with no baseline. Pass origin/{base_branch} "
             "as it was when the claims were checked (fetch it first if the commit is newer).")


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main(argv=None):
    _, config, flags, args = conf.common_args(
        sys.argv[1:] if argv is None else argv, {"--merge": False})
    merge = "--merge" in flags
    if len(args) != 4:
        sys.exit(__doc__)
    cwd = os.getcwd()
    page, stage2, stage3, commit = args
    stage2, stage3 = (os.path.join(cwd, p) for p in (stage2, stage3))
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                          text=True, check=True).stdout.strip()
    cfg = conf.load(root, os.path.join(cwd, config) if config else None)
    os.chdir(root)
    docs = cfg.docs
    if not page.startswith(docs + "/"):
        sys.exit(f"page must be repo-relative under {docs}/")
    commit = resolve(commit)
    require_on_default_branch(commit, cfg.get("review.base_branch"))

    results = load_json(stage3).get("results", [])
    texts = {}
    if os.path.exists(stage2):
        texts = {c.get("id"): c.get("text", "") for c in load_json(stage2).get("claims", [])}

    sidecar = df.sidecar_path(cfg, page)
    claims = {}
    if merge and os.path.exists(sidecar):
        old = load_json(sidecar)
        claims = {c["id"]: c for c in old.get("claims", [])}
        # Kept claims' line numbers are relative to the old commit; move them
        # to the new one so the stale check compares like with like.
        old_commit = old.get("commit")
        if old_commit and old_commit != commit:
            if not df.has_commit(".", old_commit):
                # Diffing from it would find no hunks and keep every line as is.
                sys.exit(f"{sidecar}: recorded commit {old_commit} is not in this clone, so kept "
                         "claims' lines cannot be moved. Re-record the page without --merge.")
            cache = {}
            for c in claims.values():
                moved = []
                for ev in c.get("evidence", []):
                    p, a, b = df.split_ev(ev)
                    if a is None:
                        moved.append(p)
                        continue
                    if p not in cache:
                        cache[p] = df.hunks(".", old_commit, commit, p)
                    a2, b2 = df.translate(cache[p], a), df.translate(cache[p], b)
                    if a2 is None or b2 is None:
                        moved.append(p)  # the cited lines changed: fall back to file level
                    else:
                        moved.append(f"{p}:{a2}" + (f"-{b2}" if b2 != a2 else ""))
                c["evidence"] = sorted(set(moved))

    for r in results:
        ev = r.get("evidence", "")
        ev = " ".join(ev) if isinstance(ev, list) else str(ev)
        cid = r.get("id")
        old = claims.get(cid, {})
        claims[cid] = {
            "id": cid,
            "claim": texts.get(cid) or old.get("claim", ""),
            "verdict": r.get("verdict"),
            "evidence": df.parse_evidence(cfg, ev),
        }

    side = [claims[k] for k in sorted(claims, key=lambda x: (str(type(x)), x))]
    sources = sorted({df.split_ev(e)[0] for c in side for e in c["evidence"]})
    if not sources:
        sys.exit(f"{page}: no repo evidence paths; nothing recorded")

    os.makedirs(os.path.dirname(sidecar), exist_ok=True)
    with open(sidecar, "w", encoding="utf-8") as f:
        json.dump({"page": page, "commit": commit, "claims": side}, f, indent=1)
        f.write("\n")

    with open(page, encoding="utf-8") as f:
        text = f.read()
    if not text.startswith("---\n"):
        sys.exit(f"{page}: no frontmatter")
    end = text.index("\n---", 3)
    fm = re.sub(r"\nverified:\n(?:  .*\n?)*", "\n", text[:end]).rstrip("\n")
    block = "\nverified:\n  commit: " + commit + "\n  sources:\n" + "".join(
        f"    - {p}\n" for p in sources)
    with open(page, "w", encoding="utf-8") as f:
        f.write(fm + block.rstrip("\n") + text[end:])
    print(f"{page}: {len(sources)} sources, {len(side)} claims")
    return 0


if __name__ == "__main__":
    sys.exit(main())
