@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "PS1=%SCRIPT_DIR%scripts\download-ffmpeg.ps1"
set "RELEASE_TAG=autobuild-2026-06-15-15-03"

if /i "%~1"=="release=" set "RELEASE_TAG=%~2"
if /i not "%~1"=="" (
  for /f "tokens=1,* delims==" %%A in ("%~1") do (
    if /i "%%A"=="release" set "RELEASE_TAG=%%B"
  )
)

echo [download-ffmpeg] starting...
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -RepoRoot "%SCRIPT_DIR%" -ReleaseTag "%RELEASE_TAG%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [download-ffmpeg] failed with exit code %EXIT_CODE%
  if not defined CUTSUBTITLE_NO_PAUSE pause
  exit /b %EXIT_CODE%
)

echo [download-ffmpeg] completed
if not defined CUTSUBTITLE_NO_PAUSE pause
