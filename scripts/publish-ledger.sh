#!/usr/bin/env bash
# Scores the demo universe on real prices and filings and appends the scores to
# the forecast ledger. It audits the ledger first, so a broken chain stops the
# run before it adds an entry.
# TIINGO_API_KEY is required. SEC_USER_AGENT comes from mise.toml.
# Extra arguments go to `eq run`, for example `--end 2026-10-10`.
set -euo pipefail

ledger_dir=${LEDGER_DIR:-ledger}
db=${LEDGER_DB:-data/real.sqlite}
cache=${LEDGER_CACHE:-data/cache}
universe=${LEDGER_UNIVERSE:-universes/demo30.txt}
factors_source=${LEDGER_FACTORS_SOURCE:-french}
staging_dir=$(mktemp -d -t us-stock-score-ledger.XXXXXX)
trap 'rm -rf "$staging_dir"' EXIT

uv sync --all-packages --locked
if [ -d "$ledger_dir" ]; then
  uv run eq ledger upgrade --ledger "$ledger_dir"
  uv run eq audit "$ledger_dir"
fi
uv run eq factors --source "$factors_source" --db "$db" --cache "$cache"
uv run eq run --universe "$universe" \
  --db "$db" --cache "$cache" --out "$staging_dir/scores.json" "$@"
uv run eq ledger publish \
  --scores "$staging_dir/scores.json" --ledger "$ledger_dir" --cache "$cache"
