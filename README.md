# AltairaLabs skills

A [Claude Code plugin marketplace](https://docs.claude.com/en/docs/claude-code/plugin-marketplaces).
Each plugin lives under `plugins/<name>/` and can carry skills, prompts, and a
command-line tool that CI runs on its own.

| Plugin | What it does |
|---|---|
| [`docs-review`](plugins/docs-review/) | Reviews docs pages against a style guide and the code, records what each page was verified against, and keeps pages true as the code changes. Ships the `docs-kit` checks for CI. |

## Install a plugin

In Claude Code:

```text
/plugin marketplace add AltairaLabs/skills
/plugin install docs-review@altairalabs
```

`/plugin marketplace update altairalabs` picks up new releases. A plugin's
skills are namespaced by the plugin, so the docs-review skill runs as
`/docs-review:docs-review`.

## Pin a plugin's tool in CI

A plugin that ships a tool keeps it in `plugins/<name>/tool/`, as a Python
package with console scripts. Releases are tagged per plugin as
`<plugin>/v<major>.<minor>.<patch>`, so CI pins one plugin's release without
following the others:

```bash
uvx --from "git+https://github.com/AltairaLabs/skills@docs-review/v1.0.0#subdirectory=plugins/docs-review/tool" docs-stale
```

On GitHub Actions:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0
- uses: astral-sh/setup-uv@v6
- run: uvx --from "git+https://github.com/AltairaLabs/skills@docs-review/v1.0.0#subdirectory=plugins/docs-review/tool" docs-voice
```

Each repository configures the tool with its own config file (for
docs-review, `docs-kit.toml` at the repository root), so the same release runs
everywhere.

## Layout

```text
.claude-plugin/marketplace.json   the plugin list
plugins/<name>/
  .claude-plugin/plugin.json      plugin manifest
  skills/<skill>/SKILL.md         skills, with their prompts beside them
  tool/                           optional: pyproject.toml, src/, tests/
  README.md
```

## Add a plugin or release one

1. Add `plugins/<name>/` with its manifest, and list it in
   `.claude-plugin/marketplace.json`.
2. A tool's tests go in `plugins/<name>/tool/tests/run.sh`; CI runs every one
   on pull requests and pushes.
3. To release, bump the version in the plugin's `plugin.json`, its
   marketplace entry and (if it has one) its tool's `pyproject.toml`, merge,
   then tag the merge commit `<name>/v<version>` and push the tag.

## License

Apache-2.0. See [LICENSE](LICENSE).
