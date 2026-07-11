@echo off
REM Start the Second Brain chat interface
cd /d "%~dp0..\scripts"
uv run python "..\chat\main.py" %*
