@echo off
setlocal EnableDelayedExpansion

REM ============================================================================
REM  tsticker-gui - MAIN LAUNCHER (double-click this file)
REM
REM  Auto-runs setup.bat on first launch (or if deps are missing/stale).
REM  GUI starts via pythonw.exe (no black console window).
REM
REM  If the GUI fails to start (pythonw.exe crashes silently), this script
REM  detects a fresh crash.log written within the last few seconds and falls
REM  back to opening the log so the user can see what went wrong.
REM ============================================================================

cd /d "%~dp0"

REM --- if deps not created yet, run setup automatically ----------------------
if not exist deps\Scripts\pythonw.exe (
    echo.
    echo First launch: installing dependencies...
    echo.
    call setup.bat
    if errorlevel 1 (
        echo.
        echo Setup failed. See errors above.
        pause
        exit /b 1
    )
    goto :launch
)

REM --- check for stale deps (wand installed = old version) -------------------
if exist deps\Lib\site-packages\wand (
    echo.
    echo Old dependencies detected (wand/ImageMagick). Reinstalling...
    echo.
    call setup.bat
    if errorlevel 1 (
        echo.
        echo Setup failed. See errors above.
        pause
        exit /b 1
    )
)

:launch
REM --- record crash.log timestamp BEFORE launching (so we can detect new crashes) ---
set "OLD_CRASH=0"
if exist crash.log (
    for %%I in (crash.log) do set "OLD_CRASH=%%~tI"
)

REM --- launch GUI without console window -------------------------------------
start "" deps\Scripts\pythonw.exe "%~dp0launch.py"

REM --- wait briefly, then check if a NEW crash appeared ----------------------
REM    pythonw.exe returns immediately because of `start`, so we sleep 3s
REM    and check whether crash.log was rewritten in that window.
timeout /t 3 /nobreak >nul 2>&1

set "NEW_CRASH=0"
if exist crash.log (
    for %%I in (crash.log) do set "NEW_CRASH=%%~tI"
)

if not "%OLD_CRASH%"=="%NEW_CRASH%" (
    echo.
    echo ============================================================
    echo   The GUI crashed during startup.
    echo   A crash.log was written next to this .bat file.
    echo.
    echo   Opening the log now so you can report it...
    echo ============================================================
    echo.
    notepad crash.log
    exit /b 1
)

REM --- exit silently (no crash detected) -------------------------------------
exit /b 0
