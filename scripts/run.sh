#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ ! -x "$ROOT_DIR/.venv/bin/faultlens" ]; then
  echo "error: faultlens is not installed yet." >&2
  echo "Run ./scripts/bootstrap.sh first." >&2
  exit 1
fi

exec "$ROOT_DIR/.venv/bin/faultlens" "$@"
