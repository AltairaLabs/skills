#!/usr/bin/env bash
# Tests for docs-voice.
set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

FAILURES=0

# fixture <enforced-dirs...>: a root using the bundled banned list, with the
# given enforced dirs in a list file.
fixture() {
	local d; d=$(mktemp -d)
	mkdir -p "$d/lists" "$d/docs/src/content/docs/reference" "$d/docs/src/content/docs/how-to"
	printf '[voice]\nenforced = "lists/enforced.txt"\nexempt = "lists/exempt.txt"\n' > "$d/docs-kit.toml"
	: > "$d/lists/enforced.txt"
	for e in "$@"; do echo "$e" >> "$d/lists/enforced.txt"; done
	echo "$d"
}

# run_case name want-exit dir [grep-pattern-that-must-appear]
run_case() {
	local name="$1" want="$2" dir="$3" pat="${4:-}" out got=0
	out=$(docs-voice --root "$dir" 2>&1) || got=$?
	if [ "$got" != "$want" ]; then
		echo "FAIL - $name (want exit $want, got $got)"; echo "$out" | sed 's/^/       /'; FAILURES=1; return
	fi
	if [ -n "$pat" ] && ! grep -qE -- "$pat" <<<"$out"; then
		echo "FAIL - $name (output lacks /$pat/)"; echo "$out" | sed 's/^/       /'; FAILURES=1; return
	fi
	echo "ok   - $name"
}

P=docs/src/content/docs

d=$(fixture reference/)
printf -- '---\ntitle: X\n---\n\nThe controller deliberately skips it.\n' > "$d/$P/reference/a.md"
run_case "faux-candour in enforced dir fails" 1 "$d" '^error docs/src/content/docs/reference/a.md:5: faux-candour'

d=$(fixture)
printf 'The controller deliberately skips it.\n' > "$d/$P/reference/a.md"
run_case "same finding outside enforced dirs only warns" 0 "$d" '^warn .*faux-candour'

d=$(fixture reference/)
printf 'Run it:\n\n```bash\nmytool simply --deliberately\n```\n\nUse `just` here.\n' > "$d/$P/reference/a.md"
run_case "code blocks and inline code are exempt" 0 "$d"

d=$(fixture reference/)
printf -- '---\ntitle: X\ndescription: Simply the best CRD.\n---\n\nFine.\n' > "$d/$P/reference/a.md"
run_case "frontmatter prose is checked" 1 "$d" 'a.md:3: filler'

d=$(fixture reference/)
printf 'One — two — three.\n\nOne — ok.\n' > "$d/$P/reference/a.md"
run_case "two em-dashes in one paragraph flagged" 1 "$d" 'a.md:1: em-dash'

d=$(fixture reference/)
printf 'A — b.\n\nC — d.\n' > "$d/$P/reference/a.md"
run_case "one em-dash per paragraph is fine" 0 "$d"

d=$(fixture reference/)
printf '```\n┌──────┐\n│ box  │──▶ x\n└──────┘\n```\n' > "$d/$P/reference/a.md"
run_case "ascii box diagram flagged" 1 "$d" 'ascii-diagram'

d=$(fixture reference/)
printf '```\ndocs/\n├── a.md\n└── b.md\n```\n' > "$d/$P/reference/a.md"
run_case "directory tree is not a diagram" 0 "$d"

d=$(fixture reference/)
printf '```mermaid\ngraph TD\n  A --> B\n```\n' > "$d/$P/reference/a.md"
run_case "mermaid block is fine" 0 "$d"

d=$(fixture reference/)
printf '```bash\necho hi\n\nText deliberately after.\n' > "$d/$P/reference/a.md"
run_case "unterminated fence reported" 1 "$d" 'unterminated-fence'

d=$(fixture reference/)
printf 'Fixed in #123.\n' > "$d/$P/reference/a.md"
run_case "issue reference flagged" 1 "$d" 'issue-ref'

d=$(fixture reference/)
printf 'Tracked in [the issue](https://github.com/example/project/issues/42).\n' > "$d/$P/reference/a.md"
run_case "issue link flagged" 1 "$d" 'issue-ref'

d=$(fixture reference/)
printf 'Use `&#8212;` or a heading anchor like [x](#field-spec).\n' > "$d/$P/reference/a.md"
run_case "anchors and entities are not issue refs" 0 "$d"

d=$(fixture reference/)
printf 'bad\t(unclosed\n' > "$d/lists/banned.txt"
printf '[voice]\nbanned = "lists/banned.txt"\n' > "$d/docs-kit.toml"
printf 'Fine.\n' > "$d/$P/reference/a.md"
run_case "a rule that cannot compile fails loudly" 2 "$d" 'does not compile'

d=$(fixture reference/)
printf -- '- **a** — one\n- **b** — two\n\n| x — y |\n| z — w |\n\n1. a — b\n2. c — d\n' > "$d/$P/reference/a.md"
run_case "one em-dash per list item or table row is fine" 0 "$d"

d=$(fixture reference/)
printf -- '- a — b — c\n' > "$d/$P/reference/a.md"
run_case "two em-dashes in one list item flagged" 1 "$d" 'a.md:1: em-dash'

d=$(fixture reference/)
printf 'A seamless, best-in-class runtime.\n' > "$d/$P/reference/a.md"
run_case "positioning flagged" 1 "$d" 'a.md:1: positioning'

d=$(fixture reference/)
printf 'See docs/local-backlog/voice.md for the plan.\n' > "$d/$P/reference/a.md"
run_case "internal reference flagged" 1 "$d" 'a.md:1: internal'

d=$(fixture reference/)
printf 'It used to fail (#1234). Simply retry.\n' > "$d/$P/reference/a.md"
printf '# exemptions\nreference/a.md\thistory,issue-ref\n' > "$d/lists/exempt.txt"
run_case "exempt rules are dropped for that page" 1 "$d" 'a.md:1: filler'
out=$(docs-voice --root "$d" 2>&1)
if grep -qE 'history|issue-ref' <<<"$out"; then echo "FAIL - exempt rules stay dropped"; FAILURES=1; else echo "ok   - exempt rules stay dropped"; fi

d=$(fixture reference/)
printf 'Simply retry.\n' > "$d/$P/reference/a.md"; printf 'Simply retry.\n' > "$d/$P/reference/b.md"
printf 'reference/a.md\t*\n' > "$d/lists/exempt.txt"
run_case "a * exemption covers every rule on that page only" 1 "$d" 'b.md:1: filler'

# Inline config: enforced as an array, exempt and banned as tables.
d=$(fixture)
cat > "$d/docs-kit.toml" <<'TOML'
[voice]
enforced = ["how-to"]
[voice.exempt]
"how-to/b.md" = "*"
[voice.banned]
hedge = "(^|[^a-z])perhaps([^a-z]|$)"
TOML
printf 'Perhaps retry. Simply retry.\n' > "$d/$P/how-to/a.md"; printf 'Perhaps.\n' > "$d/$P/how-to/b.md"
run_case "inline enforced, exempt and banned" 1 "$d" '^error docs/src/content/docs/how-to/a.md:1: hedge'
out=$(docs-voice --root "$d" 2>&1)
if grep -qE 'filler|b\.md' <<<"$out"; then echo "FAIL - an inline banned table replaces the bundled list"; FAILURES=1; else echo "ok   - an inline banned table replaces the bundled list"; fi

# Root pages: only allowed when voice.root_pages lists them.
d=$(fixture)
printf 'Hi.\n' > "$d/$P/stray.md"; printf 'Hi.\n' > "$d/$P/overview.mdx"
run_case "root pages are allowed when root_pages is unset" 0 "$d"
printf 'root_pages = ["overview.mdx"]\n' >> "$d/docs-kit.toml"
run_case "stray page at docs root flagged" 1 "$d" 'root-page: .*stray.md'
out=$(docs-voice --root "$d" 2>&1)
if grep -q 'overview.mdx' <<<"$out"; then echo "FAIL - listed root page passes"; FAILURES=1; else echo "ok   - listed root page passes"; fi

# Screenshot rules. fixture_ss writes a manifest naming one screenshot and
# declares sibling manifests by glob.
fixture_ss() {
	local d; d=$(fixture "$@")
	mkdir -p "$d/ui/shots"
	printf "export const DOCS_SCREENSHOTS = [\n  {\n    name: 'items-list',\n    route: '/items',\n  },\n];\n" \
		> "$d/ui/shots/docs-manifest.ts"
	printf '[screenshots]\nmanifest = "ui/shots/docs-manifest.ts"\ndeclared_in = ["ui/shots/docs-*.ts"]\n' >> "$d/docs-kit.toml"
	echo "$d"
}

d=$(fixture_ss)
printf '![The item list](screenshot:items-list)\n' > "$d/$P/how-to/a.md"
run_case "referenced screenshot with manifest entry passes" 0 "$d"

d=$(fixture_ss)
printf '![Topology](screenshot:topology)\n![The item list](screenshot:items-list)\n' > "$d/$P/how-to/a.md"
run_case "screenshot with no manifest entry fails" 1 "$d" 'a.md:1: screenshot-unknown: topology has no entry in docs-manifest.ts or a docs-\*.ts sibling'

d=$(fixture_ss)
printf 'No images.\n' > "$d/$P/how-to/a.md"
run_case "manifest entry no page uses fails" 1 "$d" '^error ui/shots/docs-manifest.ts:1: screenshot-orphan: items-list'

d=$(fixture_ss)
printf '![](screenshot:items-list)\n' > "$d/$P/how-to/a.md"
run_case "screenshot without alt text fails" 1 "$d" 'screenshot-alt'

d=$(fixture_ss)
printf "export const MORE_SCREENSHOTS = [\n  {\n    name: 'runs-list',\n    route: '/runs',\n  },\n];\n" \
	> "$d/ui/shots/docs-more.ts"
printf '![The item list](screenshot:items-list)\n![The runs list](screenshot:runs-list)\n' > "$d/$P/how-to/a.md"
run_case "screenshot declared in a sibling manifest passes" 0 "$d"

d=$(fixture_ss)
printf "export const MORE_SCREENSHOTS = [\n  {\n    name: 'runs-list',\n    route: '/runs',\n  },\n];\n" \
	> "$d/ui/shots/docs-more.ts"
printf '![The item list](screenshot:items-list)\n' > "$d/$P/how-to/a.md"
run_case "sibling manifest entry no page uses fails" 1 "$d" 'screenshot-orphan: runs-list'

d=$(fixture)
printf '![Topology](screenshot:topology)\n' > "$d/$P/how-to/a.md"
run_case "no manifest configured: screenshot rules are off" 0 "$d"

d=$(mktemp -d)
run_case "no docs tree is a usage error" 2 "$d" 'no docs tree'

exit $FAILURES
