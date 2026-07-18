@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\install-japanese-fonts.ps1" -RepoRoot "%SCRIPT_DIR%."
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" echo [japanese-fonts] failed with exit code %EXIT_CODE%
exit /b %EXIT_CODE%
