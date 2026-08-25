@echo off
REM Run the test suite.
REM   .\test.bat            unit + integration (fast, no network)
REM   .\test.bat network     contract tests against the live FPL API
REM   .\test.bat all         everything
REM   .\test.bat -k parser   pass any pytest args through

call .venv\Scripts\activate.bat

set DATABASE_URL=sqlite+aiosqlite:///:memory:
set SECRET_KEY=test-only
set ENVIRONMENT=test

if "%1"=="network" (
    pytest -m network -v
) else if "%1"=="all" (
    pytest -v
) else if "%1"=="" (
    pytest -m "not network"
) else (
    pytest -m "not network" %*
)
