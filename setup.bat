@echo off
REM Setup only (no launch). For install + test + launch, double-click start.bat.
cd /d %~dp0
python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts\create_sample_db.py
python scripts\download_model.py
echo Done. Start the app with:  .venv\Scripts\activate ^&^& streamlit run app.py
