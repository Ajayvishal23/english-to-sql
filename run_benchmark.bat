@echo off
REM Measures English -> SQL accuracy across 5 sample databases.
REM Usage: double-click, or: run_benchmark.bat --limit 3
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set TOKENIZERS_PARALLELISM=false
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Run start.bat once first to install everything.
  pause & exit /b 1
)
echo Running the accuracy benchmark. This takes a while - the model answers
echo every question and each answer is checked against a reference query.
.venv\Scripts\python.exe scripts\benchmark.py %* > benchmark_log.txt 2>&1
type benchmark_results.md
echo.
echo Full log: benchmark_log.txt
pause
