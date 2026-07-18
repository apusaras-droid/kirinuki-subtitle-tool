@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%scripts\download-runtime.ps1"
if defined CUTSUBTITLE_PYTHON (
  set "PYTHON_EXE=%CUTSUBTITLE_PYTHON%"
) else if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
  set "PYTHON_EXE=%SCRIPT_DIR%.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

set "PROFILE=standard"
set "MODEL_SET=default"
set "SKIP_PIP="

if /i "%~1"=="minimal" set "PROFILE=minimal"
if /i "%~1"=="standard" set "PROFILE=standard"
if /i "%~1"=="full" set "PROFILE=full"
if /i "%~1"=="models" set "PROFILE=models"
if /i "%~1"=="skip-pip" set "PROFILE=models"
if /i "%~1"=="models-only" set "PROFILE=models"
if /i "%~1"=="model-base" (
  set "PROFILE=models"
  set "MODEL_SET=base"
)
if /i "%~1"=="model-small" (
  set "PROFILE=models"
  set "MODEL_SET=small"
)
if /i "%~1"=="model-medium" (
  set "PROFILE=models"
  set "MODEL_SET=medium"
)
if /i "%~1"=="model-large-v3" (
  set "PROFILE=models"
  set "MODEL_SET=large-v3"
)
if /i "%~1"=="model-all" (
  set "PROFILE=models"
  set "MODEL_SET=all"
)
if /i "%~2"=="skip-pip" set "SKIP_PIP=-SkipPip"

echo [download-runtime] starting...
echo [download-runtime] repo=%SCRIPT_DIR%
echo [download-runtime] profile=%PROFILE%
if /i "%PROFILE%"=="models" echo [download-runtime] model-set=%MODEL_SET%

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -PythonExe "%PYTHON_EXE%" -Profile "%PROFILE%" -ModelSet "%MODEL_SET%" %SKIP_PIP%
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [download-runtime] failed with exit code %EXIT_CODE%
  if not defined CUTSUBTITLE_NO_PAUSE pause
  exit /b %EXIT_CODE%
)

echo [download-runtime] completed
if not defined CUTSUBTITLE_NO_PAUSE pause
