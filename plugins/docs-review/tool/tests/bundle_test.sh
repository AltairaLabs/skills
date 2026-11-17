#!/usr/bin/env bash
# Tests for docs-stale-bundle (stale-mode triage input and --apply).
set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

FAILURES=0
P=docs/src/content/docs/reference
G=(-c user.email=t@t -c user.name=t)

# repo: temp git repo with a 40-line src/x.go, verified page a.md citing it.
# Args: evidence strings for claim 1 (claim 2 always cites src/x.go:35).
repo() {
	local d; d=$(mktemp -d)
	mkdir -p "$d/src" "$d/$P" "$d/docs/provenance/reference"
	seq 1 40 | sed 's/^/line /' > "$d/src/x.go"
	git -C "$d" init -q && git -C "$d" "${G[@]}" add -A && git -C "$d" "${G[@]}" commit -q -m c1
	local c; c=$(git -C "$d" rev-parse HEAD)
	printf -- '---\ntitle: a\nverified:\n  commit: %s\n  sources:\n    - src/x.go\n---\n\nBody.\n' "$c" > "$d/$P/a.md"
	local ev; ev=$(printf '"%s",' "$@"); ev="[${ev%,}]"
	printf '{"page":"%s","commit":"%s","claims":[{"id":1,"claim":"one","verdict":"true","evidence":%s},{"id":2,"claim":"two","verdict":"true","evidence":["src/x.go:35"]}]}\n' \
		"$P/a.md" "$c" "$ev" > "$d/docs/provenance/reference/a.json"
	echo "$d"
}

# check <name> <python-expr over d (the bundle)> <bundle json>
check() {
	if python3 -c "import json,sys; d=json.loads(sys.argv[1]); c={x['id']:x for x in d['claims']}; sys.exit(0 if ($2) else 1)" "$3"; then
		echo "ok   - $1"
	else
		echo "FAIL - $1"; echo "$3" | sed 's/^/       /'; FAILURES=1
	fi
}

bundle() { docs-stale-bundle --root "$1" "$P/a.md"; }

# Insert two lines at the top: both claims only drift.
d=$(repo src/x.go:10)
{ printf 'top\ntop\n'; cat "$d/src/x.go"; } > "$d/t" && mv "$d/t" "$d/src/x.go"
out=$(bundle "$d")
check "an insertion far away is drift only" \
	"c[1]['why']=='drift only' and c[1]['moved']=={'src/x.go:10':'src/x.go:12'} and not c[1]['diffs']" "$out"

# Edit beside the cited line: claim 1 goes to triage with the hunk, still locatable.
d=$(repo src/x.go:10)
sed -i.bak '12s/.*/changed/' "$d/src/x.go" && rm -f "$d/src/x.go.bak"
out=$(bundle "$d")
check "an edit beside the cited line carries its hunk" \
	"not c[1]['check'] and len(c[1]['diffs'])==1 and c[1]['moved']=={'src/x.go:10':'src/x.go:10'} and any('+changed' in x for x in d['diffs'][c[1]['diffs'][0]])" "$out"
check "a claim far from every hunk is left out" "2 not in c" "$out"

# Edit the cited line itself: its new location is unknown.
d=$(repo src/x.go:10)
sed -i.bak '10s/.*/changed/' "$d/src/x.go" && rm -f "$d/src/x.go.bak"
out=$(bundle "$d")
check "an edit to the cited line has no new location" "c[1]['moved']=={'src/x.go:10':None}" "$out"

# Apply: unaffected without a location stays check; with one it is cleared.
b="$d/bundle.json"; echo "$out" > "$b"
echo '{"results":[{"id":1,"triage":"unaffected"}]}' > "$d/t1.json"
res=$(docs-stale-bundle --apply "$b" "$d/t1.json" "$d/s1.json")
check "unaffected without a new location stays check" "d['check']==[1] and d['cleared']==0" "{\"claims\":[],$(echo "$res" | sed 's/^{//')"
echo '{"results":[{"id":1,"triage":"unaffected","evidence":["src/x.go:11"]}]}' > "$d/t2.json"
docs-stale-bundle --apply "$b" "$d/t2.json" "$d/s2.json" >/dev/null
check "unaffected with a location is cleared with its verdict" \
	"d['results']==[{'id':1,'verdict':'true','evidence':'src/x.go:11'}]" "$(python3 -c 'import json,sys;d=json.load(open(sys.argv[1]));d["claims"]=[];print(json.dumps(d))' "$d/s2.json")"

# Whole-file citation over MAX_LINES of change is forced to check, hunks dropped.
d=$(repo src/x.go)
seq 1 400 | sed 's/^/new /' >> "$d/src/x.go"
out=$(bundle "$d")
check "an oversized whole-file change skips triage" "c[1]['check'] and not c[1]['diffs']" "$out"

# --out writes one indented file per page, named by its path.
d=$(repo src/x.go:10)
sed -i.bak '12s/.*/changed/' "$d/src/x.go" && rm -f "$d/src/x.go.bak"
docs-stale-bundle --root "$d" --out "$d/b" "$P/a.md"
if [ -f "$d/b/reference__a.json" ] && [ "$(wc -l < "$d/b/reference__a.json")" -gt 10 ]; then
	echo "ok   - --out writes an indented file per page"
else
	echo "FAIL - --out writes an indented file per page"; FAILURES=1
fi

# A deleted file forces check.
d=$(repo src/x.go:10)
rm "$d/src/x.go"
out=$(bundle "$d")
check "a deleted source forces check" "c[1]['check'] and 'gone' in c[1]['why']" "$out"

# --apply takes the triage prompt's output as written: a JSON array of pages.
d=$(repo src/x.go:10)
sed -i.bak '10s/.*/changed/' "$d/src/x.go" && rm -f "$d/src/x.go.bak"
bundle "$d" > "$d/bundle.json"
printf '[{"page":"other.md","results":[]},{"page":"%s","results":[{"id":1,"triage":"unaffected","evidence":["src/x.go:11"]}],"surface":[]}]' "$P/a.md" > "$d/t.json"
res=$(docs-stale-bundle --apply "$d/bundle.json" "$d/t.json" "$d/s.json")
check "--apply reads a triage array" "d['cleared']==1 and d['check']==[]" "{\"claims\":[],$(echo "$res" | sed 's/^{//')"

# An owned surface file's added lines are bundled for triage.
d=$(repo src/x.go:10)
mkdir -p "$d/api"; seq 1 10 | sed 's/^/field /' > "$d/api/foo.go"
printf '[surface]\npatterns = ["api/*.go"]\n' > "$d/docs-kit.toml"
git -C "$d" "${G[@]}" add -A && git -C "$d" "${G[@]}" commit -q -m api; c=$(git -C "$d" rev-parse HEAD)
printf -- '---\ntitle: a\nverified:\n  commit: %s\n  sources:\n    - api/foo.go\n---\n' "$c" > "$d/$P/a.md"
printf '{"page":"%s","commit":"%s","claims":[{"id":1,"claim":"x","verdict":"true","evidence":["api/foo.go:2"]}]}\n' "$P/a.md" "$c" > "$d/docs/provenance/reference/a.json"
echo "field new" >> "$d/api/foo.go"
out=$(bundle "$d")
check "added lines in an owned surface file are bundled" "d['surface']==['api/foo.go#0'] and '+field new' in ''.join(d['diffs']['api/foo.go#0'])" "$out"

exit $FAILURES
