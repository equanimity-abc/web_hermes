@echo off
chcp 65001 >nul
title Agent Chat - 停止中...

echo ============================================
echo    正在停止 Agent Chat 服务...
echo ============================================
echo.


:: 停止后端 (FastAPI / uvicorn)
echo [1/2] 停止后端服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
    echo [✓] 后端进程 (PID: %%a) 已停止
)

:: 停止前端 (Vite / Node.js)
echo [2/2] 停止前端服务...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do (
    taskkill /f /pid %%a >nul 2>&1
    echo [✓] 前端进程 (PID: %%a) 已停止
)

:: 关闭所有 Agent Chat 相关窗口（安静模式）
taskkill /fi "WINDOWTITLE eq Agent Chat - 后端*" >nul 2>&1
taskkill /fi "WINDOWTITLE eq Agent Chat - 前端*" >nul 2>&1

echo.
echo ============================================
echo    所有服务已停止！
echo ============================================
echo.
pause
exit /b 0