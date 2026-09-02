@echo off
chcp 65001 >nul
title Agent Chat
setlocal EnableDelayedExpansion

set "ROOT=%~dp0"
set "FORCE_INSTALL=0"
if /i "%~1"=="--install" set "FORCE_INSTALL=1"

echo ============================================
echo    Agent Chat - 通用智能体框架
echo ============================================
echo.

if not exist "%ROOT%backend\.env" (
    echo [x] 未找到 backend\.env，请先配置 DEEPSEEK_API_KEY
    pause
    exit /b 1
)

where python >nul 2>&1
if errorlevel 1 (
    echo [x] 未找到 Python
    pause
    exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
    echo [x] 未找到 Node.js
    pause
    exit /b 1
)

if "%FORCE_INSTALL%"=="1" del "%ROOT%backend\.deps_ok" 2>nul

if not exist "%ROOT%backend\.deps_ok" (
    echo [*] 安装后端依赖（仅首次或 start.bat --install）...
    cd /d "%ROOT%backend"
    pip install -r requirements.txt -q
    if errorlevel 1 (
        echo [x] 后端依赖安装失败，可尝试 start.bat --install
        pause
        exit /b 1
    )
    echo ok>"%ROOT%backend\.deps_ok"
)

if not exist "%ROOT%frontend\node_modules" (
    echo [*] 安装前端依赖（仅首次）...
    cd /d "%ROOT%frontend"
    call npm install
    if errorlevel 1 (
        echo [x] 前端依赖安装失败
        pause
        exit /b 1
    )
)

echo [*] 在终端标签页中启动后端与前端...
where wt >nul 2>&1
if %errorlevel% equ 0 (
    if defined WT_SESSION (
        wt -w 0 new-tab --title "后端 :8000" -d "%ROOT%backend" powershell -NoExit -Command "python main.py"
        wt -w 0 new-tab --title "前端 :5173" -d "%ROOT%frontend" powershell -NoExit -Command "npm run dev"
    ) else (
        wt -M --title "Agent Chat" new-tab --title "后端 :8000" -d "%ROOT%backend" powershell -NoExit -Command "python main.py" ; new-tab --title "前端 :5173" -d "%ROOT%frontend" powershell -NoExit -Command "npm run dev"
    )
    echo [✓] 已在 Windows Terminal 同一窗口的标签页中启动
) else (
    echo [i] 未检测到 Windows Terminal ^(wt^)，在本窗口后台启动...
    cd /d "%ROOT%backend"
    start /b python main.py
    cd /d "%ROOT%frontend"
    start /b npm run dev
    echo [✓] 后端与前端已在当前窗口后台运行
)

timeout /t 2 /nobreak >nul
start "" http://localhost:5173

echo.
echo [✓] 后端 http://localhost:8000  ^|  前端 http://localhost:5173
echo     停止服务: stop.bat
echo     重装依赖: start.bat --install
echo.

if defined WT_SESSION (
    exit /b 0
)
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe" (
    exit /b 0
)
where wt >nul 2>&1 && exit /b 0

echo 按任意键关闭本窗口（不影响 Terminal 中的服务）...
pause >nul
exit /b 0
