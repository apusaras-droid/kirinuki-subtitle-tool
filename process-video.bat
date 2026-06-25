@echo off
setlocal EnableExtensions
pushd "%~dp0"

if "%~1"=="" (
  echo [processor] Drop one or more video files onto this BAT.
  echo [processor] This preset runs GPU with auto cut.
  popd
  pause
  exit /b 1
)

echo [processor] Starting batch processing...
echo [processor] preset=gpu_autocut
echo [processor] inputs=%*

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\process-video.ps1" -VideoPath %* -PresetName gpu_autocut -OutputTag gpu_autocut
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo [processor] exit code: %EXIT_CODE%
popd
pause
exit /b %EXIT_CODE%
