# docs-review

A Claude Code plugin that reviews a repository's docs pages against its style
guide and its code, records what each page was verified against, and keeps
pages true as the code changes. It has two halves:

- **The skill** (`skills/docs-review/`): the review procedure and its stage
  prompts. A model classifies each page by Diátaxis quadrant, extracts every
  checkable claim, verifies each claim in the code, rewrites the page, and a
  final reviewer approves the batch.
- **The tool** (`tool/`): `docs-kit`, a Python package with the mechanical
  checks the skill and CI run. No model is involved in any of them.

| Command | What it reports |
|---|---|
| `docs-stale` | pages whose verified facts may have changed: `stale`, `missing`, `unknown-commit`, `unverified` |
| `docs-stale-bundle` | stale-mode triage input (the claims a change selected, with their hunks), and `--apply` to turn a triage result into stage-3 input |
| `docs-provenance` | records a page's `verified` frontmatter and claim sidecar from a review's output |
| `docs-coverage` | public surface no page covers: `uncovered`, `uncovered-element` |
| `docs-voice` | style-guide voice rules: `error`/`warn` findings |
| `docs-features` | feature register vs. docs and git log: `unregistered`, `missing-page`, `missing-screenshot`, `invalid` |
| `docs-kit <command>` | every command above under one name, plus `docs-kit config` |

## Install the skill

```text
/plugin marketplace add AltairaLabs/skills
/plugin install docs-review@altairalabs
```

Then `/docs-review:docs-review <page-or-directory>`, `... --stale` or
`... --features`. The skill runs the tool from the plugin's own copy with
`uvx`, so [uv](https://docs.astral.sh/uv/) must be installed.

## Configure a repository

Each repository keeps one `docs-kit.toml` at its root, plus its own lists.
Every key has a default, so the file holds only what differs. Run
`docs-kit config` to see the resolved configuration.

List-valued keys take either an inline array or a string naming a
repo-relative file with one entry per line (`#` comments and blank lines are
skipped). `voice.banned` and `voice.exempt` also take a table.

| Key | Default | Meaning |
|---|---|---|
| `docs_dir` | `docs/src/content/docs` | the published pages (`*.md`, `*.mdx`) |
| `provenance_dir` | `docs/provenance` | claim sidecars: `<provenance_dir>/<page path>.json` |
| `style_guide` | `docs/STYLE.md` | the style guide the skill enforces |
| `review.product` | `""` | product name in the prompts (`{product}`) |
| `review.notes` | `""` | the repository's part of the procedure: quadrant layout, verify sources, generated pages, commit convention |
| `review.base_branch` | `main` | provenance commits must be on `origin/<base_branch>` |
| `surface.patterns` | `[]` | public-surface globs (`**` recurses), or a file of them |
| `surface.exclude` | `["*_test.go"]` | basename globs that are never surface |
| `surface.ignore` | `[]` | `<file>` with no page on purpose, or `<file> <element-glob>` |
| `evidence.extra_extensions` | `[]` | evidence-path extensions beyond the built-in list |
| `coverage.elements.openapi` | `[]` | OpenAPI spec globs: each path needs a mention |
| `coverage.elements.values` | `[]` | values-file globs: top- and second-level keys |
| `coverage.elements.asyncapi` | `[]` | AsyncAPI spec globs: each message |
| `coverage.elements.proto` | `[]` | `.proto` globs: each rpc |
| `coverage.elements.crd` | `[]` | CRD YAML globs: each `spec` field per kind |
| `voice.banned` | bundled list | `rule<TAB>ERE` lines, a `{rule = "ERE"}` table, or a file |
| `voice.enforced` | `[]` | directories under `docs_dir` whose findings fail |
| `voice.exempt` | `[]` | `<page><TAB><rule>[,<rule>]` or `*`, a `{page = "rules"}` table, or a file |
| `voice.root_pages` | `[]` | when set, the only pages allowed directly in `docs_dir` |
| `screenshots.manifest` | `""` | screenshot manifest; when it exists, `screenshot:<name>` images are checked |
| `screenshots.declared_in` | `[]` | globs of every file declaring `name: '<name>',` entries (default: the manifest) |
| `screenshots.capture` | `""` | command that captures every screenshot |
| `features.register` | `""` | feature register (YAML); empty turns feature mode off |
| `features.since` | `""` | first ref whose `feat` commits must be registered; empty: all history |
| `commands.mermaid` | `""` | diagram check run at stage 0 and batch close |
| `commands.build` | `""` | docs build run at batch close |
| `commands.check_links` | `""` | link check run at batch close |

Element coverage and the feature register read YAML, so they need PyYAML:
install with the `yaml` extra, or add `--with pyyaml` to `uvx`.

A minimal file for a repository whose public surface is a Go package and a
JSON schema:

```toml
[review]
product = "Example"
notes = "docs/REVIEW.md"

[surface]
patterns = ["pkg/api/*.go", "schemas/*.json"]
ignore = "scripts/docs-coverage-ignore.txt"

[voice]
enforced = ["reference", "how-to"]

[commands]
mermaid = "npm --prefix docs run check:mermaid"
build = "npm --prefix docs run build"
```

## Data formats

These stay stable across releases, so recorded provenance stays valid.

A reviewed page's frontmatter:

```yaml
verified:
  commit: <40-char sha on the base branch>
  sources:
    - <repo-relative path>
```

Its sidecar, `<provenance_dir>/<page path without extension>.json`:

```json
{"page": "<page>", "commit": "<sha>",
 "claims": [{"id": 1, "claim": "<text>", "verdict": "true", "evidence": ["path:12", "path:30-34"]}]}
```

## Use it in CI

Pin a release tag and run the command with `uvx`; nothing is installed into
the repository:

```bash
uvx --from "git+https://github.com/AltairaLabs/skills@docs-review/v1.0.1#subdirectory=plugins/docs-review/tool" docs-stale --base HEAD^1
uvx --from "git+https://github.com/AltairaLabs/skills@docs-review/v1.0.1#subdirectory=plugins/docs-review/tool" docs-voice
uvx --with pyyaml --from "git+https://github.com/AltairaLabs/skills@docs-review/v1.0.1#subdirectory=plugins/docs-review/tool" docs-coverage
```

On GitHub Actions, `astral-sh/setup-uv` provides `uvx`. A full staleness
sweep diffs against each page's recorded commit, so check out with
`fetch-depth: 0`. `docs-stale --base HEAD^1` also works in a shallow checkout
(`fetch-depth: 2`): a page whose recorded commit was not fetched is checked at
file level, stale when the change touches any file it cites, and is not
reported as `unknown-commit`.

Every command takes `--root <repo>` (default: the git toplevel of the current
directory) and `--config <file>` (default: `<root>/docs-kit.toml`). The output
lines are a contract that workflows grep; they do not change within a major
version.

## Develop

```bash
uv venv && uv pip install -e 'tool[yaml]'
env PATH="$PWD/.venv/bin:$PATH" bash tool/tests/run.sh
```

## Changelog

- **1.0.1**: `docs-stale --base` no longer reports `unknown-commit` for a page
  whose verified commit is missing from a shallow checkout. It falls back to
  file level: the page is stale when the change touches a file it cites.
- **1.0.0**: first release.
