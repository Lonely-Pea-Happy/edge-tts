@echo off
cd /d "%~dp0"
python main.py
if errorlevel 1 (
    echo.
    echo [FAILED] Install dependencies first:
    echo     pip install -r requirements.txt
    echo.
    pause
)
