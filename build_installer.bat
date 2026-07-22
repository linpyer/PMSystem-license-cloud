@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

set "PYTHON=.venv\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
for /f "usebackq delims=" %%V in (`"%PYTHON%" -c "from app.core.version import APP_VERSION; print(APP_VERSION)"`) do set "APP_VERSION=%%V"
if "%APP_VERSION%"=="" (
    echo 无法从 app\core\version.py 读取版本号。
    exit /b 1
)

set "APP_EXE=dist\电商打包发货监控溯源系统\电商打包发货监控溯源系统.exe"
set "ISS_FILE=installer\PMSystem.iss"
set "OUTPUT_EXE=release\client\%APP_VERSION%\PMSystem-Setup-%APP_VERSION%-x64.exe"
set "ISCC="

if not exist "%APP_EXE%" (
    echo 未检测到打包后的 exe，请先运行 build.bat。
    echo 缺少文件：%APP_EXE%
    echo.
    pause
    exit /b 1
)

if exist "C:\Users\lin\AppData\Local\Programs\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Users\lin\AppData\Local\Programs\Inno Setup 6\ISCC.exe"
)

if "%ISCC%"=="" (
    for %%I in (ISCC.exe) do set "ISCC=%%~$PATH:I"
)

if "%ISCC%"=="" if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)

if "%ISCC%"=="" if exist "C:\Program Files\Inno Setup 6\ISCC.exe" (
    set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
)

if "%ISCC%"=="" (
    echo 未检测到 Inno Setup 编译器 ISCC.exe。
    echo 请确认 Inno Setup 已安装。
    echo 当前用户路径应为：
    echo C:\Users\lin\AppData\Local\Programs\Inno Setup 6\ISCC.exe
    echo.
    echo 也可以手动打开 installer\PMSystem.iss 编译安装包。
    echo.
    pause
    exit /b 1
)

echo 检测到 Inno Setup 编译器：
echo "%ISCC%"
echo.
echo 开始编译安装包...
echo.

"%ISCC%" /DMyAppVersion=%APP_VERSION% "%ISS_FILE%"

if errorlevel 1 (
    echo.
    echo 安装包编译失败，请检查上方错误信息。
    echo.
    pause
    exit /b 1
)

echo.
echo 安装包编译完成。
echo 输出位置：
echo %OUTPUT_EXE%
echo.
pause

endlocal

