@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"

echo [preflight] Running release checks and package build...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\preflight-release.ps1" -RunTests -BuildPackage
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
  echo [preflight] FAILED. See release\preflight-report.json
) else (
  echo [preflight] PASSED. Artifacts are in release\
)

pause
exit /b %EXIT_CODE%
