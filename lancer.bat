@echo off
rem ===== Met a jour les previsions et ouvre la page =====
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 surf.py
) else (
  python surf.py
)
if errorlevel 1 (
  echo.
  echo Probleme avec Python. Installe-le depuis python.org en cochant "Add Python to PATH".
  pause
  exit /b
)
start "" "%~dp0web\index.html"
timeout /t 4 >nul
