#!/usr/bin/env bash
# Setup for macOS / Linux: install packages, build sample DB, download model.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python scripts/create_sample_db.py
python scripts/download_model.py
echo "Done. Start the app with:  source .venv/bin/activate && streamlit run app.py"
