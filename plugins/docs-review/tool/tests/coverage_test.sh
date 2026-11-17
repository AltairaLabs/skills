#!/usr/bin/env bash
# Tests for docs-coverage.
set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

FAILURES=0

# tree: two surface files under api/; reference/a.md cites only one of them.
tree() {
	local d; d=$(mktemp -d)
	mkdir -p "$d/api/sub" "$d/docs/src/content/docs/reference" "$d/lists"
	printf '# public surface\napi/*.go\n' > "$d/lists/surface.txt"
	printf '[surface]\npatterns = "lists/surface.txt"\nignore = "lists/ignore.txt"\n' > "$d/docs-kit.toml"
	echo "package v1" > "$d/api/covered.go"
	echo "package v1" > "$d/api/newkind.go"
	printf -- '---\ntitle: A\nverified:\n  commit: abc\n  sources:\n    - api/covered.go\n---\n' \
		> "$d/docs/src/content/docs/reference/a.md"
	echo "$d"
}

run_case() {
	local name="$1" d="$2" want="$3"
	local out; out=$(docs-coverage --root "$d" 2>&1); local rc=$?
	if [ "$rc" != 0 ]; then echo "FAIL - $name (exit $rc)"; echo "$out" | sed 's/^/       /'; FAILURES=1; return; fi
	if [ "$want" = EMPTY ]; then [ -z "$out" ] && { echo "ok   - $name"; return; }
	elif [ "$out" = "$want" ]; then echo "ok   - $name"; return; fi
	echo "FAIL - $name (want: $want)"; echo "$out" | sed 's/^/       /'; FAILURES=1
}

d=$(tree)
run_case "uncited surface file is uncovered" "$d" "uncovered api/newkind.go"

d=$(tree); printf '# intentionally undocumented\napi/newkind.go\n' > "$d/lists/ignore.txt"
run_case "ignored file is not reported" "$d" EMPTY

d=$(tree); printf '# a comment only\n\n' > "$d/lists/ignore.txt"
run_case "comment lines ignore nothing" "$d" "uncovered api/newkind.go"

d=$(tree); echo "package v1" > "$d/api/newkind_test.go"
run_case "test files are not surface" "$d" "uncovered api/newkind.go"

d=$(tree); echo "package v1" > "$d/api/sub/deep.go"; echo 'api/**/*.go' >> "$d/lists/surface.txt"
run_case "recursive globs reach nested files" "$d" "$(printf 'uncovered api/newkind.go\nuncovered api/sub/deep.go')"

d=$(tree); rm "$d/lists/surface.txt"
run_case "no surface list reports nothing" "$d" EMPTY

d=$(tree); rm "$d/docs-kit.toml"
run_case "no config reports nothing" "$d" EMPTY

d=$(tree); printf '[surface]\npatterns = ["api/*_types.go", "api/*.go"]\nexclude = ["covered*"]\n' > "$d/docs-kit.toml"
run_case "inline patterns and a custom exclude" "$d" "uncovered api/newkind.go"

# etree: element-level surface. An OpenAPI spec, a values file and a CRD, all
# cited by one page, so no file is uncovered and only elements report.
etree() {
	local d; d=$(tree); rm "$d/api/newkind.go"
	mkdir -p "$d/api/openapi" "$d/charts/app" "$d/config/crd/bases" "$d/api/proto" "$d/api/events"
	cat >> "$d/docs-kit.toml" <<-'EOF2'
	[coverage.elements]
	openapi = ["api/openapi/*.yaml"]
	values = ["charts/app/values.yaml"]
	crd = ["config/crd/bases/*.yaml"]
	proto = ["api/proto/**/*.proto"]
	asyncapi = ["api/events/asyncapi.yaml"]
	EOF2
	cat > "$d/api/openapi/openapi.yaml" <<-'EOF2'
	paths:
	  /api/v1/projects/{name}/items: {}
	  /api/v1/projects/{name}/items/{item}/scale: {}
	  /api/v1/sessions/{sessionID}: {}
	  /api/v1/hidden: {}
	EOF2
	cat > "$d/charts/app/values.yaml" <<-'EOF2'
	operator:
	  logLevel: info
	  replicas: 1
	tests:
	  image: x
	EOF2
	cat > "$d/config/crd/bases/widgets.yaml" <<-'EOF2'
	spec:
	  names: {kind: Widget}
	  versions:
	    - schema:
	        openAPIV3Schema:
	          properties:
	            spec:
	              properties: {size: {}, colour: {}}
	EOF2
	cat > "$d/api/proto/svc.proto" <<-'EOF2'
	service Runner {
	  rpc Start(Req) returns (Resp);
	  rpc Drain(Req) returns (Resp);
	}
	EOF2
	cat > "$d/api/events/asyncapi.yaml" <<-'EOF2'
	components:
	  messages:
	    ChunkMessage:
	      payload:
	        properties:
	          type: {const: chunk}
	    DoneMessage:
	      payload:
	        properties:
	          type: {const: done}
	EOF2
	cat > "$d/docs/src/content/docs/reference/b.md" <<-'EOF2'
	---
	title: B
	verified:
	  commit: abc
	  sources:
	    - api/openapi/openapi.yaml
	    - charts/app/values.yaml
	---
	`GET /api/v1/projects/{project}/items/{item}/scale` and `GET /sessions/{id}`.
	Set `operator.logLevel`. A Widget takes `size`. Call `Start`. A `chunk` arrives.
	EOF2
	echo "$d"
}

ALL="uncovered-element api/openapi/openapi.yaml /api/v1/projects/{name}/items
uncovered-element api/openapi/openapi.yaml /api/v1/hidden
uncovered-element charts/app/values.yaml operator.replicas
uncovered-element charts/app/values.yaml tests
uncovered-element charts/app/values.yaml tests.image
uncovered-element api/proto/svc.proto Drain
uncovered-element api/events/asyncapi.yaml DoneMessage
uncovered-element config/crd/bases/widgets.yaml Widget.spec.colour"

d=$(etree)
run_case "uncovered elements of each kind" "$d" "$ALL"

d=$(etree); printf 'charts/app/values.yaml tests\ncharts/app/values.yaml tests.*\napi/openapi/openapi.yaml /api/v1/hid*\n' \
	> "$d/lists/ignore.txt"
run_case "element ignores take a file and a glob" "$d" \
"uncovered-element api/openapi/openapi.yaml /api/v1/projects/{name}/items
uncovered-element charts/app/values.yaml operator.replicas
uncovered-element api/proto/svc.proto Drain
uncovered-element api/events/asyncapi.yaml DoneMessage
uncovered-element config/crd/bases/widgets.yaml Widget.spec.colour"

d=$(etree); printf 'A page that never names the kind: `colour`.\n' > "$d/docs/src/content/docs/reference/c.md"
run_case "a CRD field counts only on a page that names its kind" "$d" "$ALL"

# Element coverage without PyYAML fails loudly rather than reporting nothing.
d=$(etree)
py="$(dirname "$(command -v docs-coverage)")/python"
out=$("$py" -c '
import sys, builtins
real = builtins.__import__
def imp(name, *a, **k):
    if name == "yaml":
        raise ImportError("no yaml")
    return real(name, *a, **k)
builtins.__import__ = imp
from docs_kit.coverage import main
sys.exit(main(["--root", sys.argv[1]]))' "$d" 2>&1); rc=$?
if [ "$rc" = 2 ] && grep -q "PyYAML" <<<"$out"; then echo "ok   - missing PyYAML is an error"; else
	echo "FAIL - missing PyYAML is an error (exit $rc)"; echo "$out" | sed 's/^/       /'; FAILURES=1; fi

exit $FAILURES
