@echo off
setlocal EnableDelayedExpansion

REM ============================================================================
REM  tsticker-gui - first-time setup (run ONCE, or auto-invoked by Run.bat)
REM  Pure ASCII on purpose - cmd.exe breaks on UTF-8 Cyrillic.
REM ============================================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   tsticker-gui - first-time setup
echo ============================================================
echo.

REM --- check Python 3.13+ ----------------------------------------------------
echo [1/4] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo ERROR: Python not found in PATH.
    echo.
    echo Install Python 3.13+ from https://www.python.org/downloads/windows/
    echo IMPORTANT: tick "Add python.exe to PATH" during installation.
    echo.
    pause
    exit /b 1
)
for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo     OK - Python %PYVER%

REM --- create virtual environment in deps\ -----------------------------------
echo.
echo [2/4] Creating virtual environment in deps\...
if exist deps (
    rmdir /s /q deps
)
python -m venv deps
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)
echo     OK

REM --- upgrade pip -----------------------------------------------------------
echo.
echo [3/4] Upgrading pip...
call deps\Scripts\activate.bat
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo ERROR: Failed to upgrade pip.
    pause
    exit /b 1
)

REM --- install dependencies --------------------------------------------------
echo.
echo [4/4] Installing dependencies (this takes 1-3 minutes)...
echo.
pip install -r app\requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install dependencies.
    echo Check your internet connection and run setup.bat again.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Setup complete!
echo ============================================================
echo.
echo Now double-click "Run.bat" to start the app.
echo.
pause
