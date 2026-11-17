#!/usr/bin/env bash
# Runs every *_test.sh beside this file against the docs-kit commands on PATH.
# Install first: pip install -e '<tool dir>[yaml]' (or run under `uv run`).
set -u
cd "$(dirname "$0")" || exit 2
for c in docs-kit docs-stale docs-stale-bundle docs-provenance docs-coverage docs-voice docs-features; do
	command -v "$c" >/dev/null || { echo "missing command: $c (install the docs-kit package first)" >&2; exit 2; }
done
status=0
for t in *_test.sh; do
	echo "# $t"
	bash "$t" || status=1
done
[ "$status" = 0 ] && echo "# all tests passed" || echo "# FAILURES"
exit $status
