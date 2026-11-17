---
name: docs-review
description: Review and rewrite a repository's docs pages against its style guide and its code — Diátaxis quadrant, verified facts, voice, diagrams, screenshots — and record what each page was verified against. Use when asked to review, fix, tidy or rewrite docs pages, to run a docs batch, before a release, to refresh stale pages (--stale), or to close feature-coverage gaps (--features).
---

# docs-review

Brings published pages into line with the repository's style guide and with
its code. Prose review finds typos; this finds **claims that are false**:
options that were renamed, flags that never existed, limitations fixed months
ago, and internal notes published to strangers.

Invoked as `/docs-review <page-or-directory>`, `/docs-review --stale [path]`
for upkeep, or `/docs-review --features` for feature coverage.

## Before anything else: the configuration

Every path, list and command below comes from the repository's `docs-kit.toml`,
never from memory. The mechanical checks are the `docs-kit` tool, which ships
in this plugin next to this skill (`../../tool` from this skill's directory).
Run it as:

```bash
uvx --with pyyaml --from <this skill's directory>/../../tool docs-kit <command> [args]
```

`<command>` is one of `config`, `stale`, `stale-bundle`, `provenance`,
`coverage`, `voice`, `features`. Below, `docs-kit <command>` means that full
invocation. If the repository already puts `docs-kit` on `PATH`, use that.

1. Run `docs-kit config` from the repository root. It prints the resolved
   configuration: `docs_dir`, `provenance_dir`, `style_guide`, the review
   product and notes file, the surface and voice lists, the screenshot
   manifest and capture command, the feature register and the batch-close
   commands. Use those values wherever this file names them in `<angle>`
   form, such as `<docs_dir>` or `<commands.build>`. An empty value means that
   part of the procedure does not apply to this repository; skip it.
2. Read `<style_guide>` in full. It is the authority; this file is the
   procedure.
3. Read `<review.notes>` if it is set. It is the repository's own part of this
   procedure: the quadrant layout, where claims are verified (`{sources}` in
   the prompts), which pages are generated or fetched, how commands are
   checked, and the commit convention. Where it disagrees with this file, it
   wins.

The prompts in `prompts/` (relative to this skill's directory) take
`{product}` (`review.product`), `{repo}` (the repository root), `{quadrant}`
(from the page's directory, per the notes) and `{sources}` (from the notes).
Fill them in before dispatching.

## Setup

1. Work in a worktree on a branch `docs/review-<dir>`, never on
   `<review.base_branch>` in the main checkout.
2. Establish the publication surface for the target. Every page is one of:
   - **Authored**: edit directly.
   - **Generated from repo sources**: edit the *source*, not the output.
   - **Fetched from another repository**: cannot be fixed here. An edit
     survives until the next build, then silently reverts. Fix it in the
     owning repo.

   Confirm before editing:

   ```bash
   git check-ignore -v <path>   # ignored ⇒ generated or fetched, not authored
   git ls-files <dir> | wc -l   # 0 tracked files ⇒ same conclusion
   ```
3. List the target pages (`*.md`, `*.mdx` under `<docs_dir>`). Record each
   page's word count and its quadrant.
4. Stage 0, mechanical findings, kept per page:
   - `docs-kit voice`
   - `<commands.mermaid>`
   - every CLI command and flag the pages use, against the binary's `--help`
     (see "Checking commands" below).

## Per-page pipeline

Run pages through stages 1–4 independently: start page B's stage 1 as soon as
it is dispatched, without waiting for page A's stage 4. Dispatch each stage as
an Agent call with the `model` shown, passing the prompt file's contents (with
its placeholders filled in) plus the inputs listed. Write each stage's JSON
output to `<scratchpad>/docs-review/<slug>/<stage>.json`.

| Stage | Model | Prompt | Inputs |
|---|---|---|---|
| 1 classify | haiku | `prompts/classify.md` | page path, page text, the page's quadrant, the style guide's quadrant, diagram and (when screenshots are configured) screenshot sections |
| 2 extract | haiku | `prompts/extract.md` | page path, page text |
| 3 verify | sonnet | `prompts/verify.md` | stage 2 JSON, repo path, the verify sources |
| 4 rewrite | sonnet | `prompts/rewrite.md` | page path, the style guide in full, stage 0 findings, stage 1 JSON, stage 3 JSON, the screenshot manifest path if configured |

Stages 1 and 2 can run in parallel for the same page. Stage 3 needs stage 2,
and stage 4 needs stages 1 and 3.

Rules you enforce between stages:
- Read every stage 1 action other than `keep` before stage 4 runs. Override
  any that strips a how-to of the config its steps need, moves a block to a
  page that does not exist, or contradicts the quadrant rules; record the
  override in the stage 1 JSON's `why`.
- If a move targets another page in the batch, run that page's stage 4
  first, then the mover's: two agents must not edit one file at once.
- Spot-check every `dead` verdict in the code before stage 4 removes the
  field from the docs, and report the field as a bug if it looks like a
  wiring gap rather than a field to delete.
- Stage 4 must not change a fact that stage 3 marked `true`. It must use
  stage 3's `correct` value for `false` claims, and it must leave
  `unverified` claims as written.
- A block that stage 1 moves to another page is applied by stage 4 to both
  pages. If the target page does not exist, stage 4 creates it in the right
  quadrant directory, with frontmatter `title` and `description`.
- A generated page is rewritten at its source, then regenerated. Never edit
  the output.
- New screenshot names from stage 4 are added to `<screenshots.manifest>` by
  stage 4 itself.

## Batch close

1. If any screenshot manifest entry was added or changed: run
   `<screenshots.capture>`, then open every new or changed image and look at
   it. A capture can pass while photographing an error page or the wrong crop.
2. Run `docs-kit voice`, `<commands.mermaid>` and `<commands.build>`. Fix
   failures by re-running stage 4 for the page concerned, with the failure
   appended to its inputs.
3. Stage 5: dispatch one Agent with `model: opus` and `prompts/review.md`,
   passing `git diff <review.base_branch>...HEAD` for the changed pages (plus
   any generated-page sources changed) and every page's stage 3 JSON. It
   returns `approve` or a list of `{page, reason}`. Re-run stage 4 for each
   returned page with the reason appended. If Opus returns the same page a
   second time, run that page's third stage 4 with `model: opus`, and record
   the escalation. A reviewer's factual claim is a claim like any other:
   verify it in the code before acting on it.
4. Record provenance for every page that went through stage 3:
   `docs-kit provenance <page> <slug>/stage2.json <slug>/stage3.json <commit>`,
   where `<commit>` is `origin/<review.base_branch>` as it was when the batch
   started (the code the claims were checked against). The tool refuses a
   commit that is not on that branch: a branch commit disappears when the PR
   is squash-merged. This writes the page's `verified` frontmatter and its
   sidecar under `<provenance_dir>`. Commit both. Generated pages get no
   record: the frontmatter would be overwritten at the next build.
5. Add the batch's directory to `voice.enforced` (the file or the array the
   config names), and confirm `docs-kit voice` exits 0.
6. If `<commands.check_links>` is set, run it after the build. It is slow,
   because it checks external URLs.
7. Write the batch report to the PR body:
   - fact corrections (old → new, file:line);
   - blocks moved (from → to);
   - pages created;
   - diagrams added or converted;
   - screenshots added;
   - dead fields or options, as one list for a single removal issue;
   - unverified claims;
   - code bugs found (not fixed);
   - model escalations;
   - words before → after per page, and the total.
8. Commit following the notes' commit convention, push, open the PR. File one
   issue for the dead-field list if it is non-empty.

## Stale mode (`/docs-review --stale [path]`)

Use this for upkeep. A full review costs 100–250k tokens per page; most of
it re-verifies claims that are still true. Stale mode re-checks only what the
code changed.

1. `docs-kit stale` lists pages whose `verified.sources` changed (`stale`,
   `missing`, `unknown-commit`). `docs-kit coverage` lists public-surface files
   no page cites (`uncovered`) and, when element coverage is configured,
   surface elements no page names (`uncovered-element <file> <element>`: an
   OpenAPI path, a values key, a proto rpc, an AsyncAPI message, a CRD `spec`
   field). Restrict to `[path]` if given. A scheduled freshness report, if the
   repository runs one, has the same lists.
2. Bundle the stale pages:
   `docs-kit stale-bundle --out <scratchpad>/bundles <page>...`
   (one indented file per page, readable in parts). Each page's bundle holds
   the claims the change selected, with the hunks that selected them and
   each citation's new line. A claim whose evidence only moved is
   `drift only`; a claim whose file is gone, or whose hunks are too large to
   judge cheaply, is forced to `check`. A `missing` source was deleted or
   renamed: find its successor with `git log --follow --diff-filter=R`. An
   `unknown-commit` page has no usable baseline, so give it the full pipeline.
3. Triage. One Haiku agent per group of up to 8 bundles runs
   `prompts/triage.md`, which sorts each remaining claim into `unaffected` or
   `check` and each owned surface hunk into `none` or `document`. Most stale
   flags are edits beside a cited line that change nothing it says; this is
   where they stop. Then per page:
   `docs-kit stale-bundle --apply <bundle.json> <triage.json> <cleared-stage3.json>`
   writes the drift-only and `unaffected` claims, verdicts kept and evidence
   moved, and prints the `check` ids and `document` keys. The triage file may
   be the agent's whole JSON array; `--apply` picks the page's entry. Record
   the cleared claims at once with `docs-kit provenance --merge` (step 6). A
   page with nothing to check and nothing to document is done.
4. One Sonnet agent per group of up to 4 pages left with work. For each page
   it runs `prompts/verify.md` on the `check` claims only, and
   `prompts/surface-diff.md` on the `document` hunks plus the page sections
   that document those files. No driver agents, and no Haiku classify/extract
   unless the page text changed outside a review.
5. The same agent rewrites only the affected sections: false claims take
   `correct`, dead ones are removed, and added surface is written in the
   page's existing structure. No whole-page voice pass (CI runs the voice
   check).
6. Re-record provenance with
   `docs-kit provenance --merge <page> <stage2.json> <stage3.json> <sha of origin/<review.base_branch>>`.
   The stage 3 input holds only the re-verified claims, using the sidecar's
   claim ids. `--merge` replaces those and keeps every other claim, so no
   watched source is lost.
7. `uncovered` surface: document it on the page that owns the topic, or
   create a page from the quadrant skeleton in the style guide, and give that
   page the full pipeline (it has nothing to trust yet). `uncovered-element`:
   add the element to the reference page that owns its file, in that page's
   existing structure, and verify the new claims with `prompts/verify.md` like
   any other. When no page owns the file, treat it as `uncovered`. A file
   that is internal on purpose gets a line in `surface.ignore`; an element
   gets a `<file> <element-glob>` line there. Either way, with a comment
   saying why.
8. Opus reviews only new pages and pages with 5 or more fact changes.
9. Run the batch-close checks, then open one PR titled
   `docs: refresh stale pages (<date>)`.

Expected cost: a page whose source gained one field is a diff hunk, a few
claims and one section rewrite. That is a few thousand tokens. A page whose
flags were all edits beside its citations costs one Haiku read of its hunks
and no Sonnet at all.

## Feature mode (`/docs-review --features`)

Only when `features.register` is set. The register lists the user-facing
features and the page that covers each in every Diátaxis quadrant. Stale mode
keeps existing pages true; feature mode makes sure every feature has its
pages at all.

1. Run `docs-kit features`. It reports:
   - `unregistered <pr> <subject>`: a `feat` commit no feature lists. Read the
     PR. Add its number to the feature it extends, or add a feature, or, when
     nothing a reader configures, calls or sees changed, add it to `exempt`
     with the reason.
   - `missing-page <feature> <quadrant>`: the slot is `TODO` or names a page
     that does not exist.
   - `missing-screenshot <feature> <name>`: a `ui: true` feature with no
     screenshots (`-`), or a name with no manifest entry.
   - `invalid <where> <what>`: the register itself is malformed.
2. Before writing a page for a `missing-page`, search for one that already
   documents the feature in that quadrant. A passing mention in a table is
   reference coverage at most, never a how-to or an explanation. If one
   exists, point the slot at it and stop. If the quadrant has nothing to say
   for this feature (a tutorial for a single configuration task), write
   `{none: "<reason>"}`.
3. Otherwise create the page in the quadrant's directory from the skeleton in
   the style guide, filled from the feature's PRs (`gh pr view <n>`, the diff)
   and the code on `<review.base_branch>`. Give it the full per-page pipeline
   (stages 1–4), since it has nothing to trust yet. A how-to links the
   reference and explanation pages rather than repeating them.
4. For `missing-screenshot`: add an entry to `<screenshots.manifest>` for each
   UI state the new pages show (the style guide says which quadrants carry
   them), reference it from the page as `![alt](screenshot:<name>)`, and list
   the name under the feature's `screenshots`.
5. Update the register with the new paths, then confirm `docs-kit features`
   no longer reports the feature.
6. Run the batch close, including the Opus review (stage 5) of every new page,
   and open one PR titled `docs: feature coverage (<features>)`.

## Checking commands

The highest-yield stage 0 check, and entirely mechanical. Docs claim flags
exist; the binary is the authority.

```bash
# Real flags
<cli> <subcommand> --help | grep -oE '\-\-[a-z-]+' | sort -u > <scratchpad>/real.txt

# Flags the docs use
grep -rhoE '<cli> <subcommand> [^|]*' <docs_dir> 2>/dev/null \
  | grep -oE '\-\-[a-z-]+' | sort -u > <scratchpad>/doc.txt

comm -13 <scratchpad>/real.txt <scratchpad>/doc.txt     # documented but non-existent
```

Confirm each hit really fails, rather than being a root-level or renamed flag:
`<cli> <subcommand> --suspect-flag 2>&1 | grep -oE "unknown flag.*"`.

Check the **binary name itself**. Docs outlive renames: a quickstart that
names a binary nothing builds cannot be followed past its first command.

Do the same for any identifier with a registry behind it (plugin types,
provider names, check types). Parse the YAML rather than grepping `type:`,
which also matches unrelated fields.

## Issue references

No issue links in documentation at all, open ones included. When removing
one, check its state first
(`gh issue view <n> --repo <owner/repo> --json state,stateReason,title`) and
**verify the limitation before restating it**: closed-as-completed does not
mean shipped. An issue can close months before its fix reaches a release, so
both "it's coming" and "it works" can be wrong.

## Traps

Each of these has produced a wrong conclusion in a real review:

- **`find -maxdepth 2`** missed files nested three deep, leading to "these
  don't exist", and real files were overwritten before the mistake surfaced.
  Check `git status` after any bulk write: `M` where you expected `A` means
  you clobbered something.
- **`grep -h`** strips filenames, so a following `grep -v <path>` filters
  nothing. Stale generated pages then read as live source hits.
- **Assuming a missing file is a bug.** A file absent from the repository can
  be written at run time (an `init` command that scaffolds new projects).
  Verify by running it and listing the output before calling the page wrong.
- **Double-counting logs.** Two layers can emit the same log line with the
  same fields, so raw counts are twice the real number. Count behaviour by
  running it, and know which layer logs what.
- **Fixing before reproducing.** Every correction is confirmed first: by
  running the command, checking the issue state, or counting real output.

## Reporting

Separate what you verified from what you inferred, and say which claims you
could not check. A finding is "this command errors, here is the output", not
"this looks outdated".
