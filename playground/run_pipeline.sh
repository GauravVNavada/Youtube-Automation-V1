#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export MODULARSHORTS_DATA_DIR="${MODULARSHORTS_DATA_DIR:-$ROOT_DIR/playground/data/pipeline}"
export MODULARSHORTS_RUNS_DIR="${MODULARSHORTS_RUNS_DIR:-$ROOT_DIR/playground/data/pipeline/runs}"

cd "$ROOT_DIR/final_pipeline"
exec python3 main.py "$@"
