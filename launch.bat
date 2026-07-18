@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "HOST_NAME=127.0.0.1"
set "PORT=8000"
set "OPEN_BROWSER=1"
set "HIDDEN=0"

echo [launcher] starting...

:parse_args
if "%~1"=="" goto run
if /I "%~1"=="hidden" (
  set "HIDDEN=1"
  set "OPEN_BROWSER=0"
)
if /I "%~1"=="nobrowser" set "OPEN_BROWSER=0"
for /f "tokens=1,2 delims==" %%A in ("%~1") do (
  if /I "%%A"=="port" set "PORT=%%B"
  if /I "%%A"=="host" set "HOST_NAME=%%B"
)
shift
goto parse_args

:run
echo [launcher] host=%HOST_NAME% port=%PORT%
if "%HIDDEN%"=="1" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0scripts\launch-server.ps1' -HostName $env:HOST_NAME -Port ([int]$env:PORT) -Hidden -NoBrowser"
) else if "%OPEN_BROWSER%"=="1" (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0scripts\launch-server.ps1' -HostName $env:HOST_NAME -Port ([int]$env:PORT)"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%~dp0scripts\launch-server.ps1' -HostName $env:HOST_NAME -Port ([int]$env:PORT) -NoBrowser"
)
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [launcher] exit code: %EXIT_CODE%
pause
exit /b %EXIT_CODE%
