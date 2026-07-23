@echo off
setlocal

REM ============================================================================
REM  tsticker-gui - cleanup (removes deps\ virtual environment, ~150 MB)
REM  Your app code and sticker packs are NOT touched.
REM ============================================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo   tsticker-gui - cleanup
echo ============================================================
echo.
echo This will delete deps\ (virtual environment, ~150 MB).
echo Your app code (app\) and sticker packs are NOT deleted.
echo.
echo To FULLY remove tsticker-gui: delete the whole folder after this.
echo.

set /p CONFIRM="Delete deps\? (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo Cancelled.
    pause
    exit /b 0
)

echo.
echo Deleting deps\...
rmdir /s /q deps 2>nul

if exist deps (
    echo ERROR: Could not delete deps\ - Python may still be running.
    echo Close all tsticker-gui windows and try again.
    pause
    exit /b 1
)

echo.
echo Done. deps\ removed.
echo To run the app again: double-click "Run.bat" and the environment
echo will be recreated automatically.
echo.
pause
