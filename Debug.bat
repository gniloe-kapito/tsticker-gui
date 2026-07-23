@echo off
setlocal

REM ============================================================================
REM  tsticker-gui - DEBUG launcher (shows console with Python errors)
REM
REM  Use this if "Run.bat" doesn't open the GUI. It will show any Python
REM  errors directly in this window so you can report them.
REM ============================================================================

cd /d "%~dp0"

if not exist deps\Scripts\python.exe (
    echo.
    echo Dependencies not installed yet. Running setup first...
    echo.
    call setup.bat
    if errorlevel 1 (
        echo Setup failed. See errors above.
        pause
        exit /b 1
    )
)

echo.
echo Starting tsticker-gui in DEBUG mode (console stays open)...
echo Close this window to quit the app.
echo ============================================================
echo.
deps\Scripts\python.exe "%~dp0launch.py"

echo.
echo ============================================================
echo App exited. If you see an error above, report it.
echo ============================================================
pause
