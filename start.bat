@echo off
REM ============================================================
REM  English -> SQL : one-click install, test and launch (Windows)
REM  LLM: LangChain + Hugging Face (runs locally, no Ollama)
REM ============================================================
setlocal
cd /d "%~dp0"
set LOG=%~dp0install_log.txt
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TOKENIZERS_PARALLELISM=false
echo ==== %DATE% %TIME% ==== > "%LOG%"

REM ---- find Python --------------------------------------------------
set PY=
where py >nul 2>nul && set PY=py -3
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY if exist "%USERPROFILE%\miniconda3\python.exe" set PY="%USERPROFILE%\miniconda3\python.exe"
if not defined PY (
  echo [ERROR] Python not found. Install Python 3.11+ from python.org
  echo [ERROR] Python not found >> "%LOG%"
  pause & exit /b 1
)
echo Using Python: %PY%

REM ---- virtual environment -----------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PY% -m venv .venv >> "%LOG%" 2>&1
)
set VPY=.venv\Scripts\python.exe

REM Install + test only on first run or when requirements.txt changed.
fc /b requirements.txt .venv\requirements.installed >nul 2>nul
if not errorlevel 1 goto :installed

echo Installing packages (LangChain, Transformers, PyTorch - first run takes a while)...
%VPY% -m pip install --upgrade pip >> "%LOG%" 2>&1
%VPY% -m pip install -r requirements.txt >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] pip install failed - check your internet connection, then see install_log.txt
  echo PIP_FAILED >> "%LOG%"
  pause & exit /b 1
)
echo PACKAGES_OK >> "%LOG%"
if not exist "data\sample.db" %VPY% scripts\create_sample_db.py >> "%LOG%" 2>&1

echo Running tests...
%VPY% -m pytest -q >> "%LOG%" 2>&1
if errorlevel 1 (
  echo TESTS_FAILED >> "%LOG%"
  echo [ERROR] Some tests failed - see install_log.txt
  pause & exit /b 1
)
echo TESTS_OK >> "%LOG%"
echo Tests passed.
copy /y requirements.txt .venv\requirements.installed >nul

:installed
REM ---- download model + one real question (skipped once verified) ---
echo Checking the AI model (first run downloads ~1 GB)...
%VPY% scripts\download_model.py --if-needed
if errorlevel 1 echo [WARN] Model check failed - see model_check.txt. The app will still start.

REM ---- launch --------------------------------------------------------
call "%~dp0stop.bat" quiet >nul
echo Starting the app at http://localhost:8501  (close this window to stop it)
start "" cmd /c "timeout /t 10 >nul & start http://localhost:8501"
%VPY% -m streamlit run app.py > "%~dp0app_log.txt" 2>&1
pause
