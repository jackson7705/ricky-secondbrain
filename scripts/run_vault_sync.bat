@echo off
REM Vault sync runner for Windows Task Scheduler
REM Syncs Obsidian vault with GitHub via git-sync every 2 minutes

cd /d "%~dp0"

REM Resolve vault path (two levels up from .claude/scripts/, then into the vault folder)
REM Change "Vault" below to match your actual vault folder name
set "VAULT_DIR=%~dp0..\..\Vault"

REM Run git-sync via Git Bash
"C:\Program Files\Git\bin\bash.exe" -c "cd \"$(cygpath '%VAULT_DIR%')\" && bash \"$(cygpath '%~dp0git-sync')\""

set SYNC_RESULT=%ERRORLEVEL%

REM Log the result
if %SYNC_RESULT% EQU 0 (
    echo %date% %time% - Vault sync OK >> vault_sync_runs.log
) else if %SYNC_RESULT% EQU 1 (
    echo %date% %time% - Vault sync CONFLICT - manual resolution needed >> vault_sync_runs.log
) else (
    echo %date% %time% - Vault sync FAILED exit=%SYNC_RESULT% >> vault_sync_runs.log
)
