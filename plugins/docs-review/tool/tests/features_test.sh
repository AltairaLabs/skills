#!/usr/bin/env bash
# Tests for docs-features
set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

FAILURES=0

# repo: a git history (tag base, then three feat commits, a fix and a feat
# with no PR number), one docs page per quadrant, one manifest screenshot.
repo() {
	local d; d=$(mktemp -d)
	mkdir -p "$d/ui/shots" "$d/docs/src/content/docs/how-to" \
		"$d/docs/src/content/docs/reference" "$d/docs/src/content/docs/explanation"
	cat > "$d/docs-kit.toml" <<-'TOML'
	[features]
	register = "docs/features.yaml"
	[screenshots]
	manifest = "ui/shots/docs-manifest.ts"
	declared_in = ["ui/shots/docs-*.ts"]
	TOML
	echo "# a" > "$d/docs/src/content/docs/how-to/a.md"
	echo "# a" > "$d/docs/src/content/docs/reference/a.md"
	echo "# a" > "$d/docs/src/content/docs/explanation/a.md"
	printf "export const DOCS_SCREENSHOTS = [\n  {\n    name: 'shot-a',\n  },\n];\n" \
		> "$d/ui/shots/docs-manifest.ts"
	git -C "$d" init -q
	git -C "$d" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m "chore: base"
	git -C "$d" tag base
	for s in "feat(x): one (#11)" "feat!: two (#12)" "fix(x): not a feature (#13)" \
		"feat(y): three (#14)" "feat(z): no number"; do
		git -C "$d" -c user.name=t -c user.email=t@example.com commit -q --allow-empty -m "$s"
	done
	echo "$d"
}

# register <dir> <yaml>: write docs/features.yaml
register() { printf '%s\n' "$2" > "$1/docs/features.yaml"; }

FULL='    pages:
      tutorial: {none: "a config task"}
      how-to: how-to/a.md
      reference: reference/a.md#anchor
      explanation: explanation/a.md'

run_case() {
	local name="$1" d="$2" want="$3"; shift 3
	local out; out=$(docs-features --root "$d" --since base "$@" 2>&1); local rc=$?
	if [ "$rc" != 0 ]; then echo "FAIL - $name (exit $rc)"; echo "$out" | sed 's/^/       /'; FAILURES=1; return; fi
	if [ "$want" = EMPTY ]; then [ -z "$out" ] && { echo "ok   - $name"; return; }
	elif [ "$out" = "$want" ]; then echo "ok   - $name"; return; fi
	echo "FAIL - $name"; echo "     want:"; echo "$want" | sed 's/^/       /'
	echo "     got:"; echo "$out" | sed 's/^/       /'; FAILURES=1
}

d=$(repo); NOPR=$(git -C "$d" log -1 --format=%h --abbrev=9)
register "$d" "features:
  - id: f1
    prs: [11, 12]
$FULL"
run_case "feat commits no feature lists are unregistered; fix is not" "$d" \
"unregistered $NOPR feat(z): no number
unregistered 14 feat(y): three (#14)"

d=$(repo); NOPR=$(git -C "$d" log -1 --format=%h --abbrev=9)
register "$d" "features:
  - id: f1
    prs: [11, 12, $NOPR]
$FULL
exempt:
  - {pr: 14, reason: internal refactor}"
run_case "prs, a sha prefix and exempt all register a commit" "$d" EMPTY

d=$(repo)
register "$d" "features:
  - id: f1
    prs: [11, 12]
$FULL
exempt:
  - {pr: 14}
  - {commit: abc, reason: x}"
run_case "exempt without a reason does not register" "$d" \
"unregistered $(git -C "$d" log -1 --format=%h --abbrev=9) feat(z): no number
unregistered 14 feat(y): three (#14)
invalid exempt[0] needs-pr-or-commit-and-reason" --since HEAD~2

d=$(repo)
register "$d" 'features:
  - id: f1
    pages:
      tutorial: TODO
      how-to: how-to/missing.md
      reference: [reference/a.md, reference/gone.md]
      explanation: {none: ""}'
run_case "TODO, a missing page, a missing list member and a bare none are missing pages" "$d" \
"missing-page f1 tutorial
missing-page f1 how-to
missing-page f1 reference
missing-page f1 explanation" --since HEAD

d=$(repo)
register "$d" 'features:
  - id: f1
    pages: {}'
run_case "an absent slot is a missing page" "$d" \
"missing-page f1 tutorial
missing-page f1 how-to
missing-page f1 reference
missing-page f1 explanation" --since HEAD

d=$(repo)
register "$d" "features:
  - id: ui-none
    ui: true
$FULL
  - id: ui-bad
    ui: true
    screenshots: [shot-a, shot-b]
$FULL
  - id: ui-ok
    ui: true
    screenshots: [shot-a]
$FULL
  - id: no-ui
    screenshots: []
$FULL"
run_case "a ui feature needs screenshots that are in the manifest" "$d" \
"missing-screenshot ui-none -
missing-screenshot ui-bad shot-b" --since HEAD

d=$(repo)
printf "export const MORE_SCREENSHOTS = [\n  {\n    name: 'shot-b',\n  },\n];\n" \
	> "$d/ui/shots/docs-more.ts"
register "$d" "features:
  - id: ui-sibling
    ui: true
    screenshots: [shot-a, shot-b]
$FULL"
run_case "a screenshot declared in a sibling manifest file counts" "$d" EMPTY --since HEAD

d=$(repo)
register "$d" "features:
  - id: f1
$FULL
  - id: f1
$FULL
"
run_case "a duplicate id is invalid" "$d" "invalid f1 duplicate-id" --since HEAD

d=$(repo)
register "$d" 'features:
  - id: f1
    pages:
      tutorial: TODO'
out=$(docs-features --root "$d" --since HEAD --strict >/dev/null 2>&1); rc=$?
if [ "$rc" = 1 ]; then echo "ok   - --strict exits 1 on a finding"; else echo "FAIL - --strict exit $rc"; FAILURES=1; fi
register "$d" "features:
  - id: f1
$FULL"
out=$(docs-features --root "$d" --since HEAD --strict 2>&1); rc=$?
if [ "$rc" = 0 ] && [ -z "$out" ]; then echo "ok   - --strict exits 0 when clean"; else echo "FAIL - --strict clean exit $rc: $out"; FAILURES=1; fi

d=$(repo)
register "$d" "features:
  - id: f1
$FULL
exempt:
  - {pr: 11, reason: port of an existing route}
  - {pr: 12, reason: Moved to another service, feature: f1}
  - {pr: 13, reason: rename of a field, feature: gone}
  - {pr: 14, reason: internal refactor}
  - {pr: 15, reason: support for a new transport}"
run_case "a port, move or rename exemption must name a registered feature" "$d" \
"invalid exempt[0] port-needs-feature
invalid exempt[2] unknown-feature:gone" --since HEAD

# features.since in the config is the default range; --since overrides it.
d=$(repo)
printf '[features]\nregister = "docs/features.yaml"\nsince = "HEAD~1"\n' > "$d/docs-kit.toml"
register "$d" "features:
  - id: f1
$FULL"
out=$(docs-features --root "$d" 2>&1)
if [ "$out" = "unregistered $(git -C "$d" log -1 --format=%h --abbrev=9) feat(z): no number" ]; then
	echo "ok   - features.since sets the default range"
else echo "FAIL - features.since sets the default range"; echo "$out" | sed 's/^/       /'; FAILURES=1; fi

# With no register configured there is nothing to check.
d=$(repo); rm "$d/docs-kit.toml"
out=$(docs-features --root "$d" --strict 2>/dev/null); rc=$?
if [ "$rc" = 0 ] && [ -z "$out" ]; then echo "ok   - no register configured is a no-op"; else echo "FAIL - no register configured is a no-op ($rc)"; FAILURES=1; fi

exit $FAILURES
