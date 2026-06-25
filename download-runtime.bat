@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%scripts\download-runtime.ps1"

set "MODELS=large-v3 silero-v5.1.2"
set "SKIP_PIP="

if /i "%~1"=="skip-pip" set "SKIP_PIP=-SkipPip"
if /i "%~1"=="models-only" set "SKIP_PIP=-SkipPip"

echo [download-runtime] starting...
echo [download-runtime] repo=%SCRIPT_DIR%
echo [download-runtime] models=%MODELS%

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -RepoRoot "%SCRIPT_DIR%" -Models %MODELS% %SKIP_PIP%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [download-runtime] failed with exit code %EXIT_CODE%
  pause
  exit /b %EXIT_CODE%
)

echo [download-runtime] completed
pause
