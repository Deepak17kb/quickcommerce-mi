@echo off
rem Double-click to open the project website at http://localhost:8000 (close this window to stop it).
cd /d "%~dp0"
python scripts\serve_site.py %*
if errorlevel 1 pause
