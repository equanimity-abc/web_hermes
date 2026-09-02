#!/usr/bin/env bash
# Agent Chat - 跨平台启动脚本 (Linux / macOS / Git Bash / WSL)
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

print_ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
print_err()  { echo -e "${RED}[✗]${NC} $1"; }
print_info() { echo -e "${CYAN}[*]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

FORCE_INSTALL=0
[[ "${1:-}" == "--install" ]] && FORCE_INSTALL=1

if command -v python3 &>/dev/null; then
    PYTHON=python3
elif command -v python &>/dev/null; then
    PYTHON=python
else
    print_err "未找到 Python"
    exit 1
fi

command -v npm &>/dev/null || { print_err "未找到 npm"; exit 1; }

echo ""
echo "============================================"
echo "   Agent Chat - 通用智能体框架"
echo "============================================"
echo ""

[[ -f backend/.env ]] || { print_err "未找到 backend/.env"; exit 1; }

if [[ "$FORCE_INSTALL" == 1 ]]; then
    rm -f backend/.deps_ok
fi

if [[ ! -f backend/.deps_ok ]]; then
    print_info "安装后端依赖（仅首次或 ./start.sh --install）..."
    (cd backend && "$PYTHON" -m pip install -r requirements.txt -q)
    echo ok > backend/.deps_ok
fi
print_ok "后端依赖就绪"

if [[ ! -d frontend/node_modules ]]; then
    print_info "安装前端依赖（仅首次）..."
    (cd frontend && npm install)
fi
print_ok "前端依赖就绪"
echo ""

cleanup() {
    echo ""
    print_info "正在停止服务..."
    [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
    rm -f /tmp/agent_chat_backend.pid /tmp/agent_chat_frontend.pid
    print_ok "所有服务已停止"
    exit 0
}
trap cleanup SIGINT SIGTERM

print_info "在本终端启动后端与前端..."
(cd backend && "$PYTHON" main.py) &
BACKEND_PID=$!
echo "$BACKEND_PID" > /tmp/agent_chat_backend.pid

(cd frontend && npm run dev) &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > /tmp/agent_chat_frontend.pid

sleep 2
case "$(uname -s)" in
    Linux*)  xdg-open http://localhost:5173 2>/dev/null & ;;
    Darwin*) open http://localhost:5173 2>/dev/null & ;;
    *)       start http://localhost:5173 2>/dev/null & ;;
esac

echo ""
print_ok "后端 http://localhost:8000"
print_ok "前端 http://localhost:5173"
echo "    日志在本终端输出；Ctrl+C 停止"
echo "    重装依赖: ./start.sh --install"
echo ""

wait
