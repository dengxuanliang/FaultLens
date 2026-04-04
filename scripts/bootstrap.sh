#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_DIR="$ROOT_DIR/.venv"

choose_python() {
  if [ -n "${PYTHON_BIN:-}" ]; then
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
      echo "error: required interpreter '$PYTHON_BIN' was not found." >&2
      echo "Install Python 3.11+ or re-run with PYTHON_BIN=/path/to/python3.11 ./scripts/bootstrap.sh" >&2
      exit 1
    fi
    printf '%s\n' "$PYTHON_BIN"
    return 0
  fi

  for candidate in python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done

  echo "error: no compatible Python interpreter was found." >&2
  echo "Install Python 3.11+ or re-run with PYTHON_BIN=/path/to/python3.11 ./scripts/bootstrap.sh" >&2
  exit 1
}

PYTHON_BIN="$(choose_python)"

if ! "$PYTHON_BIN" - <<'PY'
import sys

if sys.version_info[:2] < (3, 11):
    raise SystemExit(1)
PY
then
  echo "error: '$PYTHON_BIN' must be Python 3.11 or newer." >&2
  echo "Re-run with PYTHON_BIN=/path/to/python3.11 ./scripts/bootstrap.sh" >&2
  exit 1
fi

echo "Using Python: $("$PYTHON_BIN" --version 2>&1)"

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel
"$VENV_DIR/bin/pip" install -e .

if [ ! -f "$ROOT_DIR/.env" ] && [ -f "$ROOT_DIR/.env.example" ]; then
  echo
  echo "No .env found. To configure LLM access, run:"
  echo "  cp .env.example .env"
  echo "Then edit .env and fill FAULTLENS_API_KEY / FAULTLENS_BASE_URL / FAULTLENS_MODEL as needed."
fi

echo
echo "Bootstrap complete."
echo "Activate the environment with:"
echo "  source .venv/bin/activate"
echo "Then verify the CLI with:"
echo "  faultlens --help"
echo
echo "Without activation you can also run:"
echo "  ./scripts/run.sh --help"
