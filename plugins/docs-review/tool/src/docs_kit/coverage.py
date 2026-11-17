"""Report public surface that no docs page covers. No model involved.

  uncovered <file>
  uncovered-element <file> <element>

The first form lists surface files (surface.patterns, minus surface.exclude
and the single-path lines of surface.ignore) that no page cites in its
`verified.sources`, so new functionality with no page shows up as soon as it
lands.

A cited file can still hold elements no page mentions (one page citing an
OpenAPI spec covers none of its paths by itself), so when coverage.elements
names contract files the second form lists each element no page's text names:

  OpenAPI path   the path template appears in a page, parameter names ignored
                 ({name} matches {id}), with or without its /api/vN base
  values key     top-level and second-level keys of a values file; `a.b`
                 appears, or one page names both `a` and `b` (backticked or as
                 a YAML key)
  proto rpc      the rpc name appears as a word
  AsyncAPI msg   the message name, or its wire `type`, appears
  CRD field      spec.<field> per kind; a page that names the kind names the
                 field (backticked, as spec.<field>, or as a YAML key)

A `<file> <element-glob>` line in surface.ignore suppresses elements that
deliberately have no page. Element coverage needs PyYAML (the `yaml` extra).

Usage: docs-coverage [--root <repo>] [--config <file>]
Always exits 0, unless element coverage is configured and PyYAML is missing (2).
"""
import fnmatch
import glob
import os
import re
import sys

from . import config as conf
from . import freshness as df

BACKTICK = re.compile(r"`([^`\n]+)`")
YAML_KEY = re.compile(r"^\s*-?\s*([A-Za-z_][\w-]*):", re.M)
PARAM = re.compile(r"\{[^}/]*\}")
END = r"(?![\w/{-])"
API_BASE = re.compile(r"^/api/v\d+(?=/)")


class Page:
    def __init__(self, text):
        self.text = text
        self.ticks = set()
        for t in BACKTICK.findall(text):
            t = t.strip()
            self.ticks.add(t)
            # `spec.foo.bar` and `foo: x` name foo too
            self.ticks.add(t.split(":")[0].strip())
        self.keys = set(YAML_KEY.findall(text))
        self.top_keys = set(re.findall(r"^([A-Za-z_][\w-]*):", text, re.M))

    def names(self, word):
        if word in self.ticks or word in self.keys:
            return True
        return any(t.startswith(word + ".") or t.endswith("." + word) or ("." + word + ".") in t
                   for t in self.ticks)


def expand(cfg, patterns):
    out = []
    for pat in patterns:
        for p in sorted(glob.glob(pat, root_dir=cfg.root, recursive=True)):
            if os.path.isfile(cfg.abs(p)) and p not in out:
                out.append(p)
    return out


def load_yaml(yaml, cfg, rel):
    with open(cfg.abs(rel), encoding="utf-8") as fh:
        try:
            return yaml.safe_load(fh)
        except yaml.YAMLError:
            return None


def openapi_elements(yaml, cfg, files, corpus_norm):
    for rel in files:
        doc = load_yaml(yaml, cfg, rel)
        if not isinstance(doc, dict):
            continue
        for path in (doc.get("paths") or {}):
            norm = PARAM.sub("{}", path)
            # the template must end where the page's does: /a/{} is not
            # covered by a page that names only /a/{}/b
            if re.search(re.escape(norm) + END, corpus_norm):
                continue
            # pages write a service's routes relative to its /api/vN base;
            # that short form must also start where the page's does
            short = API_BASE.sub("", norm)
            if short != norm and re.search(r"(?<![\w}/-])" + re.escape(short) + END, corpus_norm):
                continue
            yield rel, path


def values_elements(yaml, cfg, files, pages, corpus):
    for rel in files:
        doc = load_yaml(yaml, cfg, rel)
        if not isinstance(doc, dict):
            continue
        for top, sub in doc.items():
            top = str(top)
            if not any(top in p.ticks or top in p.top_keys or any(t.startswith(top + ".") for t in p.ticks)
                       for p in pages):
                yield rel, top
            if not isinstance(sub, dict):
                continue
            for key in sub:
                key = str(key)
                dotted = f"{top}.{key}"
                if re.search(re.escape(dotted) + r"\b", corpus):
                    continue
                if any((top in p.ticks or top in p.top_keys) and p.names(key) for p in pages):
                    continue
                yield rel, dotted


def proto_elements(cfg, files, corpus):
    for rel in files:
        with open(cfg.abs(rel), encoding="utf-8") as fh:
            for name in re.findall(r"^\s*rpc\s+(\w+)", fh.read(), re.M):
                if not re.search(r"\b" + name + r"\b", corpus):
                    yield rel, name


def asyncapi_elements(yaml, cfg, files, pages, corpus):
    for rel in files:
        doc = load_yaml(yaml, cfg, rel)
        if not isinstance(doc, dict):
            continue
        for name, msg in ((doc.get("components") or {}).get("messages") or {}).items():
            if re.search(r"\b" + re.escape(name) + r"\b", corpus):
                continue
            wire = (((msg or {}).get("payload") or {}).get("properties") or {}).get("type", {}).get("const")
            if wire and (any(wire in p.ticks for p in pages) or f'"{wire}"' in corpus):
                continue
            yield rel, name


def crd_elements(yaml, cfg, files, pages):
    for rel in files:
        doc = load_yaml(yaml, cfg, rel)
        if not isinstance(doc, dict):
            continue
        kind = (doc.get("spec") or {}).get("names", {}).get("kind")
        if not kind:
            continue
        fields = []
        for v in doc["spec"].get("versions", []):
            props = (v.get("schema", {}).get("openAPIV3Schema", {}).get("properties", {})
                     .get("spec", {}).get("properties", {}))
            fields += [f for f in props if f not in fields]
        owners = [p for p in pages if re.search(r"\b" + re.escape(kind) + r"\b", p.text)]
        for f in fields:
            if not any(p.names(f) or f"spec.{f}" in p.text for p in owners):
                yield rel, f"{kind}.spec.{f}"


def element_findings(cfg):
    el = cfg.get("coverage.elements")
    files = {k: expand(cfg, v) for k, v in el.items()}
    if not any(el.values()):
        return []
    try:
        import yaml
    except ImportError:
        sys.stderr.write("docs-coverage: coverage.elements is configured but PyYAML is not "
                         "installed; install docs-kit with the `yaml` extra "
                         "(uvx --with pyyaml ...)\n")
        sys.exit(2)
    pages = []
    for page in df.pages(cfg):
        with open(cfg.abs(page), encoding="utf-8", errors="replace") as fh:
            pages.append(Page(fh.read()))
    corpus = "\n".join(p.text for p in pages)
    corpus_norm = PARAM.sub("{}", corpus)
    found = []
    found += openapi_elements(yaml, cfg, files["openapi"], corpus_norm)
    found += values_elements(yaml, cfg, files["values"], pages, corpus)
    found += proto_elements(cfg, files["proto"], corpus)
    found += asyncapi_elements(yaml, cfg, files["asyncapi"], pages, corpus)
    found += crd_elements(yaml, cfg, files["crd"], pages)
    rules = df.ignores(cfg)[1]
    return [f"uncovered-element {rel} {element}" for rel, element in found
            if not any(rel == f and fnmatch.fnmatchcase(element, g) for f, g in rules)]


def main(argv=None):
    root, config, flags, pos = conf.common_args(sys.argv[1:] if argv is None else argv)
    if pos:
        sys.exit(f"unknown argument: {pos[0]}")
    cfg = conf.load(root, config)
    cited = set()
    for page in df.pages(cfg):
        cited.update(df.frontmatter(cfg.abs(page))[1])
    for f in df.surface(cfg):
        if f not in cited:
            print(f"uncovered {f}")
    for line in element_findings(cfg):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
