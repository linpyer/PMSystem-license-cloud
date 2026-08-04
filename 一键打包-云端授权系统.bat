@echo off
setlocal EnableExtensions

pushd "%~dp0" || (
    echo ERROR: Cannot enter the project directory.
    pause
    exit /b 1
)

set "MENU_SCRIPT=%~dp0scripts\build_cloud_menu.ps1"
if not exist "%MENU_SCRIPT%" (
    echo ERROR: Cloud build menu script not found:
    echo %MENU_SCRIPT%
    popd
    pause
    exit /b 2
)

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%MENU_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo Cloud build failed. Exit code: %EXIT_CODE%
)

popd
pause
exit /b %EXIT_CODE%
