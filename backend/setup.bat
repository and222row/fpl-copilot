@echo off
echo Setting up FPL Copilot backend...

REM Remove old broken venv if it exists
if exist .venv rmdir /s /q .venv

REM Create virtual environment using Python 3.12
py -3.12 -m venv .venv
if errorlevel 1 (
    echo ERROR: Python 3.12 not found. Install it from python.org/downloads
    exit /b 1
)

REM Activate it
call .venv\Scripts\activate.bat

REM Upgrade pip first
python -m pip install --upgrade pip

REM Install dependencies
pip install -r requirements.txt

echo.
echo Setup complete! Run .\start.bat to launch the backend.
