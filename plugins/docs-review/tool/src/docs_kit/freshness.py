"""Shared helpers for docs provenance, staleness and coverage.

A reviewed page records `verified.commit` and `verified.sources` in its
frontmatter, and a sidecar <provenance_dir>/<page>.json maps each claim to its
evidence as `path` or `path:line` strings. Line numbers are relative to the
sidecar's commit.
"""
import fnmatch
import glob
import json
import os
import re
import subprocess

EXTENSIONS = ("go", "tsx", "ts", "jsx", "js", "mjs", "yaml", "yml", "proto", "json", "tpl",
              "sh", "sql", "py", "envsh", "conf", "template")
WINDOW = 3  # lines of slack around a cited line


def evidence_re(extra=()):
    exts = "|".join(re.escape(e.lstrip(".")) for e in (*EXTENSIONS, *extra))
    return re.compile(
        r"((?:[A-Za-z0-9_.\[\]-]+/)*[A-Za-z0-9_.\[\]-]+\.(?:" + exts + r")\b"
        r"|(?:[A-Za-z0-9_.\[\]-]+/)*(?:Makefile|Dockerfile(?:\.[A-Za-z0-9_-]+)?|Tiltfile))"
        r"(?::(\d+)(?:-(\d+))?)?")


def git(root, *args, check=True):
    return subprocess.run(["git", "-C", root, *args], capture_output=True, text=True,
                          check=check).stdout


def has_commit(root, sha):
    return subprocess.run(["git", "-C", root, "cat-file", "-e", sha + "^{commit}"],
                          capture_output=True).returncode == 0


def sidecar_path(cfg, page):
    return cfg.provenance + "/" + page[len(cfg.docs) + 1:].rsplit(".", 1)[0] + ".json"


def frontmatter(path):
    """Return (commit, [sources]) from a page's `verified` block."""
    commit, sources, inv, insrc = "", [], False, False
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    if not lines or lines[0].strip() != "---":
        return "", []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if line.startswith("verified:"):
            inv, insrc = True, False
            continue
        if inv and line and not line.startswith(" "):
            inv = insrc = False
        if inv and line.startswith("  commit:"):
            commit = line.split(":", 1)[1].strip().strip("\"'")
        elif inv and line.startswith("  sources:"):
            insrc = True
        elif inv and insrc and line.startswith("    - "):
            s = line[6:].split("#", 1)[0].strip().strip("\"'")
            if s:
                sources.append(s)
        elif inv and insrc and line.startswith("  ") and not line.startswith("    "):
            insrc = False
    return commit, sources


def parse_evidence(cfg, text, exists=os.path.isfile):
    """Return sorted unique evidence strings (`path` or `path:line[-end]`).
    Paths under the docs tree's top directory are never evidence."""
    rx = evidence_re(cfg.get("evidence.extra_extensions"))
    docs_top = cfg.docs.split("/", 1)[0] + "/"
    out = set()
    for m in rx.finditer(text or ""):
        p = m.group(1)
        p = p[2:] if p.startswith("./") else p
        if p.startswith(docs_top) or not exists(p):
            continue
        if m.group(2):
            out.add(f"{p}:{m.group(2)}" + (f"-{m.group(3)}" if m.group(3) else ""))
        else:
            out.add(p)
    return sorted(out)


def split_ev(ev):
    """'path:10-12' -> ('path', 10, 12); 'path' -> ('path', None, None)."""
    m = re.match(r"^(.*?):(\d+)(?:-(\d+))?$", ev)
    if not m:
        return ev, None, None
    a = int(m.group(2))
    return m.group(1), a, int(m.group(3) or a)


def hunks(root, old, new, path):
    """Hunks of `git diff -U0 old [new] -- path` as (old_start, old_count, new_start, new_count).
    new=None diffs against the working tree."""
    args = ["diff", "-U0", old] + ([new] if new else []) + ["--", path]
    out = git(root, *args, check=False)
    res = []
    for m in re.finditer(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", out, re.M):
        res.append((int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1)))
    return res


def touches(hs, a, b):
    """Does any hunk's old side overlap lines a..b (with WINDOW slack)?"""
    for os_, oc, _, _ in hs:
        lo, hi = os_, os_ + max(oc, 1) - 1
        if oc == 0:  # pure insertion after line os_
            lo, hi = os_, os_ + 1
        if lo <= b + WINDOW and hi >= a - WINDOW:
            return True
    return False


def translate(hs, line):
    """Map an old line number through hunks; None if the line was changed."""
    delta = 0
    for os_, oc, ns, nc in hs:
        if oc and os_ <= line < os_ + oc:
            return None
        if (oc and line >= os_ + oc) or (not oc and line > os_):
            delta += nc - oc
    return line + delta


def ignores(cfg):
    """(ignored files, [(file, element-glob)]) from surface.ignore."""
    files, elements = set(), []
    for line in cfg.entries("surface.ignore"):
        parts = line.split()
        if len(parts) == 1:
            files.add(parts[0])
        elif len(parts) >= 2:
            elements.append((parts[0], parts[1]))
    return files, elements


def surface(cfg):
    """Repo-relative public-surface files: the surface.patterns globs, minus
    surface.exclude basenames and ignored files. Sorted."""
    out = set()
    excl = cfg.get("surface.exclude")
    for pat in cfg.entries("surface.patterns"):
        for p in glob.glob(pat.strip(), root_dir=cfg.root, recursive=True):
            if not os.path.isfile(cfg.abs(p)):
                continue
            if any(fnmatch.fnmatchcase(os.path.basename(p), x) for x in excl):
                continue
            out.add(p)
    return sorted(out - ignores(cfg)[0])


def pages(cfg):
    """Repo-relative docs pages (*.md, *.mdx), sorted."""
    res = []
    for d, _, files in os.walk(cfg.abs(cfg.docs)):
        for f in files:
            if f.endswith((".md", ".mdx")):
                res.append(os.path.relpath(os.path.join(d, f), cfg.root))
    return sorted(res)


def load_sidecar(cfg, page):
    p = cfg.abs(sidecar_path(cfg, page))
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)
