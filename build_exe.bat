@echo off
cd /d "%~dp0"
echo [1/2] Building VoiceStudio.exe ...
python -m PyInstaller --noconfirm --clean --windowed --onefile ^
  --name "VoiceStudio" ^
  --icon "%~dp0assets\app.ico" ^
  --distpath "%~dp0dict" ^
  --workpath "%~dp0build" ^
  --specpath "%~dp0build" ^
  --collect-submodules edge_tts ^
  main.py
if errorlevel 1 (
    echo.
    echo [FAILED] Install PyInstaller first:
    echo     pip install pyinstaller
    echo.
    pause
    exit /b 1
)
echo.
echo [2/2] Done: dict\VoiceStudio.exe
pause
