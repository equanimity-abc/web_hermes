@echo off
chcp 65001 >nul
title Agent Chat - 启动中...

echo ============================================
echo    Agent Chat - 通用智能体框架
echo ============================================
echo.

:: 检查 .env 配置
if not exist "backend\.env" (
    echo [警告] 未找到 backend\.env 配置文件！
    echo 请先创建 backend\.env 并配置 DEEPSEEK_API_KEY
    echo 示例:
    echo   DEEPSEEK_API_KEY=sk-your-actual-api-key
    echo.
    pause
    exit /b 1
)
echo [✓] .env 配置文件已找到
echo.

:: 检测 Python 版本
echo [0/4] 检测运行环境...
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [✓] Python 版本: %PYVER%
echo [✓] Node.js 版本:
node --version 2>nul
echo.

:: 安装后端依赖
echo [1/4] 检查后端依赖...
cd /d "%~dp0backend"
pip install -r requirements.txt -q
if %errorlevel% neq 0 (
    echo.
    echo [✗] 后端依赖安装失败！
    echo.
    echo 常见解决方案:
    echo   1. 如果提示 "linker link.exe not found"，说明缺少 C++ 编译工具：
    echo      推荐使用 Python 3.12 或 3.13 替代 Python 3.14
    echo      或者安装 Visual Studio Build Tools: https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022
    echo   2. 运行 pip install --upgrade pip 后重试
    echo.
    pause
    exit /b 1
)
echo [✓] 后端依赖就绪
echo.

:: 安装前端依赖
echo [2/4] 检查前端依赖...
cd /d "%~dp0frontend"
if not exist "node_modules" (
    echo 首次运行，正在安装前端依赖，请稍候...
    call npm install
    if %errorlevel% neq 0 (
        echo [✗] 前端依赖安装失败！
        pause
        exit /b 1
    )
)
echo [✓] 前端依赖就绪
echo.

:: 启动后端 + 前端（Windows Terminal 同窗口 PowerShell 标签页）
echo [3/4] 启动后端服务 (http://localhost:8000)...
echo [4/4] 启动前端服务 (http://localhost:5173)...
where wt >nul 2>&1
if %errorlevel% equ 0 (
    if defined WT_SESSION (
        wt -w 0 new-tab --title "Agent Chat - 后端" -d "%~dp0backend" powershell -NoExit -Command "python main.py"
        wt -w 0 new-tab --title "Agent Chat - 前端" -d "%~dp0frontend" powershell -NoExit -Command "npm run dev"
    ) else (
        wt new-tab --title "Agent Chat - 后端" -d "%~dp0backend" powershell -NoExit -Command "python main.py" ; new-tab --title "Agent Chat - 前端" -d "%~dp0frontend" powershell -NoExit -Command "npm run dev"
    )
    echo [✓] 后端与前端已在 Windows Terminal 标签页中启动
) else (
    echo [i] 未检测到 Windows Terminal ^(wt^)，回退为独立窗口启动...
    cd /d "%~dp0backend"
    start "Agent Chat - 后端" powershell -NoExit -Command "python main.py"
    cd /d "%~dp0frontend"
    start "Agent Chat - 前端" powershell -NoExit -Command "npm run dev"
    echo [✓] 后端与前端已在独立 PowerShell 窗口中启动
)
echo.

:: 等待后端就绪
echo 等待后端就绪...
timeout /t 3 /nobreak >nul

:: 打开浏览器
timeout /t 2 /nobreak >nul
start http://localhost:5173

echo ============================================
echo    启动完成！
echo    后端: http://localhost:8000
echo    前端: http://localhost:5173
echo ============================================
echo.
echo 关闭此窗口不会影响服务运行（服务在 Terminal 标签页中）。
echo 如需停止所有服务，请运行 stop.bat
echo.
pause
exit /b 0