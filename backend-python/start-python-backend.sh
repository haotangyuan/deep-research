#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v conda >/dev/null 2>&1; then
  if [ -x "/opt/anaconda3/bin/conda" ]; then
    CONDA_BIN="/opt/anaconda3/bin/conda"
  else
    echo "conda not found"
    exit 1
  fi
else
  CONDA_BIN="conda"
fi

cd "$ROOT_DIR/backend-python"
"$CONDA_BIN" run -n deep-research-py uvicorn app.main:app --host 0.0.0.0 --port 8080
