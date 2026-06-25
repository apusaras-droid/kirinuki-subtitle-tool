@echo off
setlocal EnableExtensions
pushd "%~dp0"

if "%~1"=="" (
  echo [processor] Drop one or more video files onto this BAT.
  echo [processor] This preset runs CPU without auto cut.
  popd
  pause
  exit /b 1
)

echo [processor] Starting batch processing...
echo [processor] preset=cpu_nocut
echo [processor] inputs=%*

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\process-video.ps1" -VideoPath %* -PresetName cpu_nocut -OutputTag cpu_nocut
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [processor] exit code: %EXIT_CODE%
popd
pause
exit /b %EXIT_CODE%
