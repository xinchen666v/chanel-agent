#!/bin/bash
set -e

echo "============================================"
echo "  Chanel Agent - 一键环境配置（macOS / Linux）"
echo "============================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装 Python 3.10+"
    echo "macOS: brew install python3"
    echo "Linux: sudo apt install python3 python3-venv"
    exit 1
fi

echo "[1/3] 创建虚拟环境 .venv ..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "      虚拟环境已创建"
else
    echo "      虚拟环境已存在，跳过"
fi

echo "[2/3] 安装依赖..."
.venv/bin/python -m pip install -r requirements.txt --quiet
if [ $? -ne 0 ]; then
    echo "[错误] 依赖安装失败，请检查网络连接"
    exit 1
fi
echo "      依赖安装完成"

echo "[3/3] 启动 Chanel Agent..."
echo ""
echo "============================================"
echo "  启动方式："
echo "    - 直接回车：TUI 三面板界面"
echo "    - 输入 t  : 纯终端模式（方便日志分享）"
echo "============================================"
echo ""

read -p "请选择启动模式 [回车=TUI / t=终端]: " mode

if [ "$mode" = "t" ] || [ "$mode" = "T" ]; then
    echo ""
    echo "启动纯终端模式..."
    .venv/bin/python -m src.main --terminal
else
    echo ""
    echo "启动 TUI 界面模式..."
    .venv/bin/python -m src.main
fi