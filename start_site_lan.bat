@echo off
rem Double-click to open ShelfPulse on this computer AND on phones and tablets on the same Wi-Fi.
rem The window shows the address to open on the phone and a six-digit code. Close this window to stop ShelfPulse.
rem The first time, Windows may ask whether Python may use private networks: allow it, or phones cannot connect.
cd /d "%~dp0"
python scripts\serve_site.py --lan %*
if errorlevel 1 pause
