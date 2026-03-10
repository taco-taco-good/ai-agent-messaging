#!/usr/bin/env sh

set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SETUP_DIR="$ROOT_DIR/setup"
CONFIG_DIR="$ROOT_DIR/config"
VENV_DIR="$ROOT_DIR/.venv"
PYTHON_BIN="${PYTHON:-python3}"

mkdir -p "$CONFIG_DIR"
mkdir -p "$CONFIG_DIR/personas"
mkdir -p "$ROOT_DIR/jobs"
mkdir -p "$ROOT_DIR/skills"
mkdir -p "$ROOT_DIR/agents"
mkdir -p "$ROOT_DIR/tools"
mkdir -p "$ROOT_DIR/runtime"
mkdir -p "$ROOT_DIR/memory"
mkdir -p "$ROOT_DIR/workspace"

if [ ! -f "$CONFIG_DIR/agents.yaml" ]; then
  cp "$SETUP_DIR/agents.yaml.template" "$CONFIG_DIR/agents.yaml"
  echo "Created $CONFIG_DIR/agents.yaml"
else
  echo "Skipped $CONFIG_DIR/agents.yaml (already exists)"
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  echo "Created $VENV_DIR"
else
  echo "Skipped $VENV_DIR (already exists)"
fi

cd "$ROOT_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -e ".[discord]"
"$VENV_DIR/bin/python" "$SETUP_DIR/bootstrap.py" --config "$CONFIG_DIR/agents.yaml"

echo "Ensured directories:"
echo "  - $CONFIG_DIR/personas"
echo "  - $ROOT_DIR/runtime"
echo "  - $ROOT_DIR/memory"
echo "  - $ROOT_DIR/workspace"
