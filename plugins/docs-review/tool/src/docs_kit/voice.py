"""Check reader-facing prose against the mechanical rules of a docs style guide.

Every page under docs_dir is read outside code (fenced blocks and inline code
are exempt), plus the frontmatter `title` and `description`. Findings:

  <level> <page>:<line>: <rule>: <text>

<level> is `error` for pages under a directory in voice.enforced, `warn`
elsewhere. Rules:
  <banned rule>       voice.banned (rule<TAB>ERE, matched on lowercased prose;
                      default: the list bundled with docs-kit)
  ascii-diagram       box-drawing characters outside a mermaid block
  em-dash             more than one em-dash in a paragraph, list item or row
  unterminated-fence  a code fence that never closes
  root-page           (always error) a page directly in docs_dir that
                      voice.root_pages does not list; only when it is set
  screenshot-unknown  (always error) `![..](screenshot:<name>)` with no entry
  screenshot-alt      (always error) a screenshot with empty alt text
  screenshot-orphan   (always error) a manifest entry no page uses
The screenshot rules run when screenshots.manifest exists. voice.exempt drops
given rules for given pages.

Usage: docs-voice [--root <repo>] [--config <file>]
Exits 1 when any finding is an error, 2 on a usage or rule error.
"""
import fnmatch
import glob
import os
import re
import sys
from importlib import resources

from . import config as conf

BOX = re.compile(r"┌|┐|┘|▶|◀|▼|▲")
FENCE = re.compile(r"^[ \t]*(```|~~~)")
LIST_START = re.compile(r"^[ \t]*([-*+][ \t]|[0-9]+\.[ \t]|\|)")
INLINE_CODE = re.compile(r"`[^`]*`")
FM_KEY = re.compile(r"^[A-Za-z_]+:[ \t]*")
SHOT_REF = re.compile(r"!\[[^]]*\]\(screenshot:[a-z0-9-]+\)")
# An entry's own `name: '<name>',` line. Stricter than a bare `name:` match,
# so names inside an entry's fixture data are not mistaken for entries.
MANIFEST_NAME = re.compile(r"^[ \t]*name: '([a-z0-9-]+)',[ \t]*$", re.M)


def banned_rules(cfg):
    value = cfg.get("voice.banned")
    if value:
        lines = cfg.entries("voice.banned")
    else:
        text = resources.files("docs_kit").joinpath("data/voice-banned.txt").read_text("utf-8")
        lines = [ln for ln in text.split("\n") if ln.strip() and not ln.startswith("#")]
    rules = []
    for ln in lines:
        if "\t" not in ln:
            continue
        name, pat = ln.split("\t", 1)
        try:
            rules.append((name, re.compile(pat)))
        except re.error as e:
            print(f"docs-voice: rule {name!r} does not compile: {e}", file=sys.stderr)
            sys.exit(2)
    return rules


def check_page(rel, text, rules):
    """Findings `<rel>:<line>: <rule>: <text>` in the order they occur."""
    out = []
    st = {"para": 0, "pstart": 0}

    def emit(n, rule, line):
        out.append(f"{rel}:{n}: {rule}: {line[:120]}")

    def flush():
        if st["para"] > 1:
            out.append(f"{rel}:{st['pstart']}: em-dash: {st['para']} em-dashes in one paragraph")
        st["para"] = 0

    def prose(n, t, line):
        t = INLINE_CODE.sub("", t)
        low = t.lower()
        for name, rx in rules:
            if rx.search(low):
                emit(n, name, line)
        if BOX.search(t):
            emit(n, "ascii-diagram", line)
        if st["para"] == 0:
            st["pstart"] = n
        st["para"] += t.count("—")

    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    fm = infence = False
    fstart, lang = 0, ""
    for n, line in enumerate(lines, 1):
        if n == 1 and re.match(r"^---[ \t]*$", line):
            fm = True
            continue
        if fm and re.match(r"^---[ \t]*$", line):
            fm = False
            continue
        if fm:
            if re.match(r"^(title|description):", line):
                prose(n, FM_KEY.sub("", line, count=1), line)
            continue
        if FENCE.match(line):
            flush()
            if not infence:
                infence, fstart = True, n
                lang = re.sub(r"^[ \t]*(```|~~~)[ \t]*", "", line, count=1)
            else:
                infence = False
            continue
        if infence:
            if not lang.startswith("mermaid") and BOX.search(line):
                emit(n, "ascii-diagram", line)
            continue
        if re.match(r"^[ \t]*$", line):
            flush()
            continue
        if LIST_START.match(line):
            flush()
        prose(n, line, line)
    flush()
    if infence:
        out.append(f"{rel}:{fstart}: unterminated-fence: fence opened here is never closed")
    return out


def screenshot_findings(cfg, docs_files):
    manifest = cfg.get("screenshots.manifest")
    if not manifest or not os.path.isfile(cfg.abs(manifest)):
        return []
    globs = cfg.get("screenshots.declared_in") or [manifest]
    declared = set()
    for g in globs:
        for p in glob.glob(g, root_dir=cfg.root, recursive=True):
            with open(cfg.abs(p), encoding="utf-8") as fh:
                declared |= set(MANIFEST_NAME.findall(fh.read()))
    where = os.path.basename(manifest)
    if cfg.get("screenshots.declared_in"):
        where += " or a " + " / ".join(os.path.basename(g) for g in globs) + " sibling"
    out, used = [], set()
    for rel, text in docs_files:
        for n, line in enumerate(text.split("\n"), 1):
            for m in SHOT_REF.finditer(line):
                img = m.group(0)
                name = img[img.index("screenshot:") + 11:-1]
                used.add(name)
                if name not in declared:
                    out.append(f"{rel}:{n}: screenshot-unknown: {name} has no entry in {where}")
                if img.startswith("![]"):
                    out.append(f"{rel}:{n}: screenshot-alt: {name} has no alt text")
    for name in sorted(declared - used):
        out.append(f"{manifest}:1: screenshot-orphan: {name} is captured but no page uses it")
    return out


def main(argv=None):
    root, config, flags, pos = conf.common_args(sys.argv[1:] if argv is None else argv)
    if pos:
        print(f"unknown argument: {pos[0]}", file=sys.stderr)
        return 2
    cfg = conf.load(root, config)
    docs_rel = cfg.docs
    docs = cfg.abs(docs_rel)
    if not os.path.isdir(docs):
        print(f"no docs tree at {docs}", file=sys.stderr)
        return 2
    rules = banned_rules(cfg)

    findings = []
    allowed = cfg.get("voice.root_pages")
    if allowed:
        for f in sorted(os.listdir(docs)):
            if f.endswith((".md", ".mdx")) and os.path.isfile(os.path.join(docs, f)) and f not in allowed:
                findings.append(f"{docs_rel}/{f}:1: root-page: {f} belongs in a quadrant directory")

    docs_files = []
    for d, dirs, files in os.walk(docs):
        dirs.sort()
        for f in sorted(files):
            if not f.endswith((".md", ".mdx")):
                continue
            path = os.path.join(d, f)
            rel = os.path.relpath(path, cfg.root)
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            docs_files.append((rel, text))
            findings += check_page(rel, text, rules)
    findings += screenshot_findings(cfg, docs_files)

    enforced = [f"{docs_rel}/{e.strip().rstrip('/')}/" for e in cfg.entries("voice.enforced")]
    exempt = []
    for ln in cfg.entries("voice.exempt"):
        page, _, rules_s = ln.partition("\t")
        page, rules_s = page.strip(), rules_s.strip()
        for r in rules_s.split(","):
            exempt.append(f"{docs_rel}/{page}:*: {r.strip()}:*")
        if rules_s == "*":
            exempt.append(f"{docs_rel}/{page}:*")

    always = ("root-page", "screenshot-unknown", "screenshot-alt", "screenshot-orphan")
    status = 0
    for line in findings:
        if any(fnmatch.fnmatchcase(line, x) for x in exempt):
            continue
        level = "error" if any(line.startswith(e) for e in enforced) else "warn"
        rule = line.split(": ", 2)[1] if line.count(": ") >= 2 else ""
        if rule in always:
            level = "error"
        if level == "error":
            status = 1
        print(f"{level} {line}")
    return status


if __name__ == "__main__":
    sys.exit(main())
