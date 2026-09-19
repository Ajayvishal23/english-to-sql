@echo off
REM Stops the English -> SQL app (the server listening on port 8501).
set FOUND=
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":8501 .*LISTENING"') do (
  taskkill /PID %%p /F >nul 2>nul
  set FOUND=1
)
if defined FOUND (echo The app has been stopped.) else (echo The app was not running.)
if /i not "%~1"=="quiet" timeout /t 3 >nul
