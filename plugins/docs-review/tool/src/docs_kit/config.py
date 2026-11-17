"""docs-kit configuration: one TOML file at the repository root.

Every command reads `<root>/docs-kit.toml` (or the file `--config` names). A
missing file means every key takes its default, so a repository with the
conventional layout needs only the keys where it differs.

List-valued keys (surface patterns, ignore lists, voice lists) accept either an
inline TOML array or a string naming a repo-relative file with one entry per
line; `#` comments and blank lines are skipped. The file form keeps long,
commented lists out of the config.
"""
import copy
import os
import re
import subprocess
import sys
import tomllib

CONFIG_NAME = "docs-kit.toml"

DEFAULTS = {
    # Where the published pages live (*.md, *.mdx), repo-relative.
    "docs_dir": "docs/src/content/docs",
    # Where per-page claim sidecars live: <provenance_dir>/<page path>.json.
    "provenance_dir": "docs/provenance",
    # The style guide the review enforces; read by the skill, not the tools.
    "style_guide": "docs/STYLE.md",
    "review": {
        # Product name the review prompts use ({product}).
        "product": "",
        # Repo-specific review notes the skill reads before starting: quadrant
        # layout, where claims are verified, generated pages, commit rules.
        "notes": "",
        # Branch PRs merge into; provenance commits are taken from origin/<it>.
        "base_branch": "main",
    },
    "surface": {
        # Public-surface globs (`**` recurses), or a file of them. A page that
        # owns a surface file is stale when lines are added to it; a surface
        # file no page cites is `uncovered`.
        "patterns": [],
        # Basename globs that are never surface (test files).
        "exclude": ["*_test.go"],
        # Files that deliberately have no page (`<file>`), and elements that
        # deliberately have no mention (`<file> <element-glob>`), or a file.
        "ignore": [],
    },
    "evidence": {
        # Extensions recognised as evidence paths in verification output, on
        # top of the built-in list.
        "extra_extensions": [],
    },
    "coverage": {
        # Element-level coverage: contract files whose individual elements
        # each need a mention. Globs. Needs PyYAML (the `yaml` extra).
        "elements": {
            "openapi": [],   # OpenAPI specs: each path template
            "values": [],    # Helm-style values files: top- and second-level keys
            "asyncapi": [],  # AsyncAPI specs: each components.messages entry
            "proto": [],     # .proto files: each rpc
            "crd": [],       # CustomResourceDefinition YAML: each spec field per kind
        },
    },
    "voice": {
        # rule<TAB>ERE lines matched case-insensitively against prose, a table
        # {rule = "ERE"}, or a file. Empty: the rules bundled with docs-kit.
        "banned": "",
        # Directories under docs_dir whose findings fail; elsewhere they warn.
        "enforced": [],
        # "<page under docs_dir><TAB><rule>[,<rule>...]" or "*" for all
        # rules, a table {page = "rules"}, or a file.
        "exempt": [],
        # When non-empty, only these files may sit directly in docs_dir; any
        # other root page is a `root-page` error.
        "root_pages": [],
    },
    "screenshots": {
        # The screenshot manifest. When it exists, every `screenshot:<name>`
        # image must have an entry and alt text, and every entry must be used.
        "manifest": "",
        # Globs of every file declaring entries (`name: '<name>',`), when the
        # manifest is split across siblings. Default: the manifest alone.
        "declared_in": [],
        # Command that captures every screenshot; run by the skill.
        "capture": "",
    },
    "features": {
        # Feature register (YAML): features, their PRs and a page per
        # quadrant. Empty: feature mode is off. Needs PyYAML.
        "register": "",
        # First ref whose feat commits must be registered. Empty: all history.
        "since": "",
    },
    "commands": {
        # Shell commands the skill runs at batch close; empty ones are skipped.
        "mermaid": "",
        "build": "",
        "check_links": "",
    },
}


class Config:
    """Resolved configuration. `root` is absolute; paths in it are repo-relative."""

    def __init__(self, root, data, path):
        self.root = root
        self.data = data
        self.path = path

    def __getitem__(self, key):
        return self.data[key]

    def get(self, dotted):
        cur = self.data
        for part in dotted.split("."):
            cur = cur[part]
        return cur

    @property
    def docs(self):
        return self.data["docs_dir"].rstrip("/")

    @property
    def provenance(self):
        return self.data["provenance_dir"].rstrip("/")

    def abs(self, rel):
        return os.path.join(self.root, rel)

    def entries(self, dotted):
        """A list-valued key: inline entries, or the lines of the file it names.
        A table becomes `key<TAB>value` entries."""
        return entries(self.root, self.get(dotted))


def entries(root, value):
    if isinstance(value, dict):
        return [f"{k}\t{v}" for k, v in value.items()]
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if not value:
        return []
    path = os.path.join(root, value)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f
                if ln.strip() and not ln.lstrip().startswith("#")]


def _merge(base, over, where=""):
    for k, v in over.items():
        if k not in base:
            sys.exit(f"docs-kit: unknown config key {where}{k}")
        if isinstance(base[k], dict):
            if not isinstance(v, dict):
                sys.exit(f"docs-kit: config key {where}{k} must be a table")
            _merge(base[k], v, f"{where}{k}.")
        else:
            base[k] = v


def git_toplevel(start):
    r = subprocess.run(["git", "-C", start, "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else os.path.abspath(start)


def load(root=None, config=None):
    """Resolve the config for `root` (default: the git toplevel of the cwd)."""
    root = os.path.abspath(root) if root else git_toplevel(os.getcwd())
    path = config or os.path.join(root, CONFIG_NAME)
    data = copy.deepcopy(DEFAULTS)
    found = None
    if os.path.exists(path):
        with open(path, "rb") as f:
            try:
                _merge(data, tomllib.load(f))
            except tomllib.TOMLDecodeError as e:
                sys.exit(f"docs-kit: {path}: {e}")
        found = os.path.abspath(path)
    elif config:
        sys.exit(f"docs-kit: no config file at {config}")
    return Config(root, data, found)


def common_args(argv, extra=()):
    """Parse --root/--config plus the flags in `extra` ({flag: takes_value}).
    Returns (root, config, flags, positionals)."""
    root = config = None
    flags, pos = {}, []
    spec = dict(extra)
    args = list(argv)
    while args:
        a = args.pop(0)
        if a in ("--root", "--config"):
            if not args:
                sys.exit(f"{a} needs a value")
            v = args.pop(0)
            if a == "--root":
                root = v
            else:
                config = v
        elif a in spec:
            if spec[a]:
                if not args:
                    sys.exit(f"{a} needs a value")
                flags[a] = args.pop(0)
            else:
                flags[a] = True
        elif a.startswith("--"):
            sys.exit(f"unknown argument: {a}")
        else:
            pos.append(a)
    return root, config, flags, pos


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t")
    return f'"{s}"'


def _toml_key(k):
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else _toml_value(k)


def dump(data):
    """Render resolved config as TOML."""
    lines = []

    def emit(table, name):
        scalars = [(k, v) for k, v in table.items() if not isinstance(v, dict)]
        subs = [(k, v) for k, v in table.items() if isinstance(v, dict)]
        if name and (scalars or not subs):
            lines.extend(["", f"[{name}]"])
        for k, v in scalars:
            lines.append(f"{_toml_key(k)} = {_toml_value(v)}")
        for k, v in subs:
            emit(v, f"{name}.{_toml_key(k)}" if name else _toml_key(k))

    emit(data, "")
    return "\n".join(lines).lstrip("\n") + "\n"
