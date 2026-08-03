@echo off
title Edge Analysis - MT5 sync
where python >nul 2>nul
if errorlevel 1 (
  echo Python isn't installed. Get it from https://python.org/downloads
  echo IMPORTANT: tick "Add python.exe to PATH" during install, then run me again.
  pause & exit /b 1
)
python -m pip install --quiet MetaTrader5 requests
python "%~dp0ea_mt5_sync.py"
pause
