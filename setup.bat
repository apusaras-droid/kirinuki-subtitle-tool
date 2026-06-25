@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "STATUS_FILE=%SCRIPT_DIR%logs\setup-status.txt"

if exist "%STATUS_FILE%" del /q "%STATUS_FILE%"

echo [setup] starting...
echo [setup] step 1/2: runtime
call "%SCRIPT_DIR%download-runtime.bat"
if errorlevel 1 goto :fail

echo [setup] step 2/2: ffmpeg
call "%SCRIPT_DIR%download-ffmpeg.bat"
if errorlevel 1 goto :fail

if exist "%STATUS_FILE%" (
  echo [setup] summary:
  type "%STATUS_FILE%"
)

echo [setup] step 3/3: launch app
call "%SCRIPT_DIR%launch.bat"
if errorlevel 1 goto :fail

echo [setup] completed
pause
exit /b 0

:fail
if exist "%STATUS_FILE%" (
  echo [setup] partial summary:
  type "%STATUS_FILE%"
)
echo [setup] failed with exit code %ERRORLEVEL%
pause
exit /b %ERRORLEVEL%
