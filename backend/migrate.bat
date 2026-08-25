@echo off
REM Generates a migration from model changes, then applies it.
REM Usage:  .\migrate.bat "describe your change"

call .venv\Scripts\activate.bat

set MSG=%~1
if "%MSG%"=="" set MSG=auto

echo Generating migration: %MSG%
alembic revision --autogenerate -m "%MSG%"
if errorlevel 1 (
    echo.
    echo Migration generation failed.
    exit /b 1
)

echo.
echo Applying migration...
alembic upgrade head
if errorlevel 1 (
    echo.
    echo Migration apply failed.
    exit /b 1
)

echo.
echo Done. Database is up to date.
