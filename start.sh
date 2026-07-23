#!/usr/bin/env bash
# Agent Chat - 跨平台启动脚本 (Linux / macOS / Windows-Git-Bash / WSL)
set -e

# =============================================
# 颜色输出
# =============================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_ok()    { echo -e "${GREEN}[✓]${NC} $1"; }
print_err()   { echo -e "${RED}[✗]${NC} $1"; }
print_warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
print_info()  { echo -e "${CYAN}[*]${NC} $1"; }

# =============================================
# OS 检测
# =============================================
detect_os() {
    case "$(uname -s)" in
        Linux*)     OS="linux";;
        Darwin*)    OS="macos";;
        CYGWIN*|MINGW*|MSYS*) OS="gitbash";;
        *)          OS="unknown";;
    esac
}

detect_python() {
    # 尝试找到 python3 或 python 命令
    if command -v python3 &>/dev/null; then
        PYTHON="python3"
    elif command -v python &>/dev/null; then
        PYTHON="python"
    else
        print_err "未找到 Python，请先安装 Python 3.8+"
        exit 1
    fi
}

detect_node() {
    if ! command -v npm &>/dev/null; then
        print_err "未找到 npm，请先安装 Node.js"
        exit 1
    fi
}

# =============================================
# 启动后端
# =============================================
start_backend() {
    print_info "启动后端服务 (http://localhost:8000)..."
    cd "$SCRIPT_DIR/backend"

    "$PYTHON" main.py &
    BACKEND_PID=$!
    echo $BACKEND_PID > /tmp/agent_chat_backend.pid

    # 等待后端就绪
    for i in $(seq 1 15); do
        if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
            print_ok "后端就绪 (PID: $BACKEND_PID)"
            return 0
        fi
        sleep 1
    done
    print_err "后端启动超时，请检查日志"
    return 1
}

# =============================================
# 启动前端
# =============================================
start_frontend() {
    print_info "启动前端服务 (http://localhost:5173)..."
    cd "$SCRIPT_DIR/frontend"

    npm run dev &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > /tmp/agent_chat_frontend.pid

    # 等待前端就绪
    for i in $(seq 1 20); do
        if curl -s http://localhost:5173 > /dev/null 2>&1; then
            print_ok "前端就绪 (PID: $FRONTEND_PID)"
            return 0
        fi
        sleep 1
    done
    print_warn "前端可能仍在编译中，请稍后访问"
    return 0
}

# =============================================
# 打开浏览器
# =============================================
open_browser() {
    print_info "正在打开浏览器..."
    sleep 2
    case "$OS" in
        linux)  xdg-open http://localhost:5173 2>/dev/null & ;;
        macos)  open http://localhost:5173 2>/dev/null & ;;
        gitbash|*) start http://localhost:5173 2>/dev/null & ;;
    esac
}

# =============================================
# 清理函数 (CTRL+C)
# =============================================
cleanup() {
    echo ""
    print_warn "正在停止服务..."
    [ -n "$BACKEND_PID" ] && kill $BACKEND_PID 2>/dev/null
    [ -n "$FRONTEND_PID" ] && kill $FRONTEND_PID 2>/dev/null
    rm -f /tmp/agent_chat_backend.pid /tmp/agent_chat_frontend.pid
    print_ok "所有服务已停止"
    exit 0
}
trap cleanup SIGINT SIGTERM

# =============================================
# 主流程
# =============================================
main() {
    SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
    cd "$SCRIPT_DIR"

    detect_os
    detect_python
    detect_node

    echo ""
    echo "============================================"
    echo "   Agent Chat - 通用智能体框架"
    echo "============================================"
    echo ""

    # 检查 .env 配置
    if [ ! -f "backend/.env" ]; then
        print_err "未找到 backend/.env 配置文件！"
        echo "请先创建 backend/.env 并配置 DEEPSEEK_API_KEY"
        echo "示例: DEEPSEEK_API_KEY=sk-your-actual-api-key"
        exit 1
    fi
    print_ok ".env 配置文件已找到"
    echo ""

    # 安装后端依赖
    print_info "检查后端依赖..."
    cd "$SCRIPT_DIR/backend"
    "$PYTHON" -m pip install -r requirements.txt -q 2>&1 | tail -1
    if [ ${PIPESTATUS[0]} -ne 0 ]; then
        print_err "后端依赖安装失败"
        exit 1
    fi
    print_ok "后端依赖就绪"
    echo ""

    # 安装前端依赖
    print_info "检查前端依赖..."
    cd "$SCRIPT_DIR/frontend"
    if [ ! -d "node_modules" ]; then
        echo "首次运行，正在安装前端依赖..."
        npm install
    fi
    print_ok "前端依赖就绪"
    echo ""

    # 启动服务
    start_backend || exit 1
    echo ""
    start_frontend
    echo ""

    # 打开浏览器
    open_browser

    echo ""
    echo "============================================"
    echo "    启动完成！"
    echo "    后端: http://localhost:8000"
    echo "    前端: http://localhost:5173"
    echo "    按 Ctrl+C 停止所有服务"
    echo "============================================"
    echo ""

    # 等待子进程
    wait
}

main