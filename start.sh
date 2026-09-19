#!/usr/bin/env bash
# macOS / Linux: install on first run, then start the app.
set -euo pipefail
cd "$(dirname "$0")"
export HF_HUB_DISABLE_SYMLINKS_WARNING=1 TOKENIZERS_PARALLELISM=false
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
if ! cmp -s requirements.txt .venv/requirements.installed; then
  echo "Installing packages (first run takes a while)..."
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
  .venv/bin/python -m pytest -q
  cp requirements.txt .venv/requirements.installed
fi
.venv/bin/python scripts/download_model.py --if-needed || \
  echo "[WARN] Model check failed - see model_check.txt. The app will still start."
echo "Open http://localhost:8501  (Ctrl+C to stop)"
exec .venv/bin/python -m streamlit run app.py
