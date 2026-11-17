"""Report user-facing features whose docs are incomplete. No model involved.

The register (features.register, YAML) lists every feature with the PRs that
built it and the page that covers it in each Diátaxis quadrant. This checks
the register against the git log and the docs tree:

  unregistered <pr> <subject>      a feat commit since features.since that no
                                   feature lists and the exempt list does not
                                   name (<pr> is the short sha when the subject
                                   carries no (#N))
  missing-page <feature> <quadrant>  the slot is TODO, empty, or names a page
                                   that does not exist
  missing-screenshot <feature> <name>  a ui feature with no screenshots
                                   (<name> is "-"), or a name with no entry in
                                   the screenshot manifest
  invalid <where> <what>           the register itself is malformed, or an
                                   exempt entry whose reason is a port, move
                                   or rename names no registered `feature`

A slot is a page path relative to docs_dir (an #anchor is allowed), a list of
such paths, or {none: "<reason>"}. Needs PyYAML (the `yaml` extra).

Usage: docs-features [--root <repo>] [--config <file>] [--since <ref>] [--strict]
Exits 0, unless --strict and something was reported.
"""
import glob
import os
import re
import subprocess
import sys

from . import config as conf

QUADRANTS = ("tutorial", "how-to", "reference", "explanation")
FEAT = re.compile(r"^feat(\([^)]*\))?!?:")
PR_SUFFIX = re.compile(r"\(#(\d+)\)\s*$")
PORT_REASON = re.compile(r"\b(port|ported|porting|move|moved|moves|rename|renamed)\b", re.I)
MANIFEST_NAME = re.compile(r"^\s*name:\s*'([^']+)',", re.M)


def feat_commits(root, since):
    rng = f"{since}..HEAD" if since else "HEAD"
    out = subprocess.run(
        ["git", "-C", root, "log", "--no-merges", "--format=%H%x09%s", rng],
        capture_output=True, text=True)
    if out.returncode != 0:
        print(f"docs-features: cannot read git log since {since}: {out.stderr.strip()}", file=sys.stderr)
        return []
    commits = []
    for line in out.stdout.splitlines():
        sha, _, subject = line.partition("\t")
        if FEAT.match(subject):
            m = PR_SUFFIX.search(subject)
            commits.append((sha, int(m.group(1)) if m else None, subject))
    return commits


def manifest_names(cfg):
    manifest = cfg.get("screenshots.manifest")
    globs = cfg.get("screenshots.declared_in") or ([manifest] if manifest else [])
    names = set()
    for g in globs:
        for path in sorted(glob.glob(g, root_dir=cfg.root, recursive=True)):
            with open(cfg.abs(path), encoding="utf-8") as fh:
                names |= set(MANIFEST_NAME.findall(fh.read()))
    return names


def slot_problem(cfg, slot):
    """None when the slot is satisfied, else a short reason."""
    if isinstance(slot, dict):
        reason = slot.get("none")
        return None if isinstance(reason, str) and reason.strip() else "none without a reason"
    paths = slot if isinstance(slot, list) else [slot]
    if not paths or any(not isinstance(p, str) or not p.strip() or p.strip() == "TODO" for p in paths):
        return "todo"
    base = cfg.abs(cfg.docs)
    for p in paths:
        if not os.path.isfile(os.path.join(base, p.split("#", 1)[0])):
            return "no such page"
    return None


def exempt_feature_problems(i, entry, reason, ids):
    """A port, move or rename carries an existing capability somewhere new.
    The commit is exempt, but the capability is not: the entry must name the
    registered feature it carries, so an exemption cannot hide a capability
    that was never registered. Any named feature must exist."""
    feature = entry.get("feature")
    if feature is None:
        return [f"invalid exempt[{i}] port-needs-feature"] if PORT_REASON.search(reason) else []
    if str(feature) not in ids:
        return [f"invalid exempt[{i}] unknown-feature:{feature}"]
    return []


def check(cfg, since, yaml):
    out = []
    rel = cfg.get("features.register")
    try:
        with open(cfg.abs(rel), encoding="utf-8") as fh:
            reg = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError) as e:
        return [f"invalid {rel} {type(e).__name__}"]

    features = reg.get("features") or []
    registered, ids = set(), set()
    shots = manifest_names(cfg)
    for i, f in enumerate(features):
        if not isinstance(f, dict) or not f.get("id"):
            out.append(f"invalid features[{i}] no-id")
            continue
        fid = f["id"]
        if fid in ids:
            out.append(f"invalid {fid} duplicate-id")
        ids.add(fid)
        for pr in f.get("prs") or []:
            registered.add(str(pr))
        pages = f.get("pages") or {}
        for q in QUADRANTS:
            if slot_problem(cfg, pages.get(q)):
                out.append(f"missing-page {fid} {q}")
        for q in pages:
            if q not in QUADRANTS:
                out.append(f"invalid {fid} unknown-quadrant:{q}")
        names = f.get("screenshots") or []
        if f.get("ui") and not names:
            out.append(f"missing-screenshot {fid} -")
        for n in names:
            if n not in shots:
                out.append(f"missing-screenshot {fid} {n}")

    for i, e in enumerate(reg.get("exempt") or []):
        key = (e or {}).get("pr") or (e or {}).get("commit")
        reason = str((e or {}).get("reason") or "").strip()
        if not key or not reason:
            out.append(f"invalid exempt[{i}] needs-pr-or-commit-and-reason")
            continue
        registered.add(str(key))
        out.extend(exempt_feature_problems(i, e, reason, ids))

    unreg = []
    for sha, pr, subject in feat_commits(cfg.root, since):
        if pr is not None and str(pr) in registered:
            continue
        if any(len(k) >= 7 and sha.startswith(k) for k in registered):
            continue
        unreg.append(f"unregistered {pr if pr is not None else sha[:9]} {subject}")
    return unreg + out


def main(argv=None):
    root, config, flags, pos = conf.common_args(
        sys.argv[1:] if argv is None else argv, {"--since": True, "--strict": False})
    if pos:
        print(f"unknown argument: {pos[0]}", file=sys.stderr)
        return 2
    cfg = conf.load(root, config)
    if not cfg.get("features.register"):
        print("docs-features: features.register is not set; nothing to check", file=sys.stderr)
        return 0
    try:
        import yaml
    except ImportError:
        print("docs-features: needs PyYAML; install docs-kit with the `yaml` extra "
              "(uvx --with pyyaml ...)", file=sys.stderr)
        return 2
    since = flags.get("--since", cfg.get("features.since"))
    lines = check(cfg, since, yaml)
    for line in lines:
        print(line)
    return 1 if "--strict" in flags and lines else 0


if __name__ == "__main__":
    sys.exit(main())
