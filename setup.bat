@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "STATUS_FILE=%SCRIPT_DIR%logs\setup-status.txt"
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "PYTHON_EXE=%VENV_DIR%\Scripts\python.exe"
set "CUTSUBTITLE_NO_PAUSE=1"

:menu
cls
echo ============================================================
echo  Kirinuki Douga Kobo - Setup
echo ============================================================
echo.
echo  [1] Standard setup - Recommended
echo      App + Gemini + FFmpeg + fonts + Whisper/VAD models
echo.
echo  [2] Minimal setup
echo      App + FFmpeg only. No AI model download.
echo.
echo  [3] Full setup
echo      Standard + WhisperX + Demucs + speaker diarization.
echo      This option requires several GB of disk space.
echo.
echo  [4] Download or verify AI models only
echo  [5] Check installation status
echo  [6] Launch application
echo  [0] Exit
echo.
set "SETUP_CHOICE="
set /p "SETUP_CHOICE=Select a number: "

if "%SETUP_CHOICE%"=="1" goto :install_standard
if "%SETUP_CHOICE%"=="2" goto :install_minimal
if "%SETUP_CHOICE%"=="3" goto :install_full
if "%SETUP_CHOICE%"=="4" goto :install_models
if "%SETUP_CHOICE%"=="5" goto :check_status
if "%SETUP_CHOICE%"=="6" goto :launch_app
if "%SETUP_CHOICE%"=="0" exit /b 0

echo Invalid selection.
pause
goto :menu

:prepare_python
if exist "%PYTHON_EXE%" goto :python_ready
where python >nul 2>nul
if errorlevel 1 (
  echo [setup] Python was not found. Install 64-bit Python 3.10 or later.
  exit /b 1
)
echo [setup] creating virtual environment...
python -m venv "%VENV_DIR%"
if errorlevel 1 exit /b %ERRORLEVEL%

:python_ready
set "CUTSUBTITLE_PYTHON=%PYTHON_EXE%"
echo [setup] python=%PYTHON_EXE%
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if (3, 10) ^<= sys.version_info[:2] ^< (3, 13) else 1)"
if errorlevel 1 (
  echo [setup] Unsupported Python version. Install 64-bit Python 3.10, 3.11, or 3.12.
  exit /b 1
)
"%PYTHON_EXE%" -m pip install --upgrade pip
exit /b %ERRORLEVEL%

:reset_status
if exist "%STATUS_FILE%" del /q "%STATUS_FILE%"
exit /b 0

:install_minimal
call :reset_status
call :prepare_python
if errorlevel 1 goto :install_fail
echo [setup] installing minimal profile...
call "%SCRIPT_DIR%download-runtime.bat" minimal
if errorlevel 1 goto :install_fail
call "%SCRIPT_DIR%download-ffmpeg.bat"
if errorlevel 1 goto :install_fail
goto :install_complete

:install_standard
call :reset_status
call :prepare_python
if errorlevel 1 goto :install_fail
echo [setup] installing standard profile...
call "%SCRIPT_DIR%download-runtime.bat" standard
if errorlevel 1 goto :install_fail
call "%SCRIPT_DIR%download-ffmpeg.bat"
if errorlevel 1 goto :install_fail
call "%SCRIPT_DIR%download-japanese-fonts.bat"
if errorlevel 1 goto :install_fail
goto :install_complete

:install_full
call :reset_status
call :prepare_python
if errorlevel 1 goto :install_fail
echo [setup] installing full profile...
call "%SCRIPT_DIR%download-runtime.bat" full
if errorlevel 1 goto :install_fail
call "%SCRIPT_DIR%download-ffmpeg.bat"
if errorlevel 1 goto :install_fail
call "%SCRIPT_DIR%download-japanese-fonts.bat"
if errorlevel 1 goto :install_fail
goto :install_complete

:install_models
set "MODEL_PROFILE="
cls
echo ============================================================
echo  Whisper.cpp Model Setup
echo ============================================================
echo.
echo  [1] Base + Silero VAD       - fastest test model
echo  [2] Small + Silero VAD      - app default, recommended
echo  [3] Medium + Silero VAD     - higher accuracy
echo  [4] Large-v3 + Silero VAD   - highest local accuracy
echo  [5] All transcription models + Silero VAD
echo  [0] Back
echo.
set "MODEL_CHOICE="
set /p "MODEL_CHOICE=Select a number: "
if "%MODEL_CHOICE%"=="0" goto :menu
if "%MODEL_CHOICE%"=="1" set "MODEL_PROFILE=model-base"
if "%MODEL_CHOICE%"=="2" set "MODEL_PROFILE=model-small"
if "%MODEL_CHOICE%"=="3" set "MODEL_PROFILE=model-medium"
if "%MODEL_CHOICE%"=="4" set "MODEL_PROFILE=model-large-v3"
if "%MODEL_CHOICE%"=="5" set "MODEL_PROFILE=model-all"
if not defined MODEL_PROFILE (
  echo Invalid selection.
  pause
  goto :install_models
)
call :reset_status
call :prepare_python
if errorlevel 1 goto :install_fail
echo [setup] downloading or verifying local AI models...
call "%SCRIPT_DIR%download-runtime.bat" %MODEL_PROFILE%
if errorlevel 1 goto :install_fail
set "MODEL_PROFILE="
goto :install_complete

:check_status
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%scripts\check-installation.ps1"
echo.
pause
goto :menu

:launch_app
call "%SCRIPT_DIR%launch.bat"
if errorlevel 1 (
  echo [setup] application launch failed.
  pause
)
goto :menu

:install_complete
echo.
echo [setup] completed successfully.
if exist "%STATUS_FILE%" (
  echo [setup] summary:
  type "%STATUS_FILE%"
)
echo.
pause
goto :menu

:install_fail
set "EXIT_CODE=%ERRORLEVEL%"
if "%EXIT_CODE%"=="0" set "EXIT_CODE=1"
echo.
if exist "%STATUS_FILE%" (
  echo [setup] partial summary:
  type "%STATUS_FILE%"
)
echo [setup] failed with exit code %EXIT_CODE%
pause
goto :menu
