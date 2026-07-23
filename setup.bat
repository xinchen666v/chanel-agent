@echo off
chcp 65001 >nul
title Chanel Agent Setup

echo ============================================
echo   Chanel Agent - 一键环境配置（Windows）
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.10+
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 创建虚拟环境 .venv ...
if not exist .venv (
    python -m venv .venv
    echo       虚拟环境已创建
) else (
    echo       虚拟环境已存在，跳过
)

echo [2/3] 安装依赖...
.venv\Scripts\python.exe -m pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，请检查网络连接
    pause
    exit /b 1
)
echo       依赖安装完成

echo [3/3] 启动 Chanel Agent...
echo.
echo ============================================
echo   启动方式：
echo     - 直接回车：TUI 三面板界面
echo     - 输入 t  : 纯终端模式（方便日志分享）
echo ============================================
echo.

set /p mode="请选择启动模式 [回车=TUI / t=终端]: "

if /i "%mode%"=="t" (
    echo.
    echo 启动纯终端模式...
    .venv\Scripts\python.exe -m src.main --terminal
) else (
    echo.
    echo 启动 TUI 界面模式...
    .venv\Scripts\python.exe -m src.main
)

pause