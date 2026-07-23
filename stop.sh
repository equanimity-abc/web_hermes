#!/usr/bin/env bash
# Agent Chat - 跨平台停止脚本 (Linux / macOS / Windows-Git-Bash / WSL)

# =============================================
# 颜色输出
# =============================================
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_ok()   { echo -e "${GREEN}[✓]${NC} $1"; }
print_warn() { echo -e "${YELLOW}[!]${NC} $1"; }

# =============================================
# 主流程
# =============================================
echo ""
echo "============================================"
echo "    正在停止 Agent Chat 服务..."
echo "============================================"
echo ""

# 停止后端 (通过 PID 文件)
if [ -f /tmp/agent_chat_backend.pid ]; then
    PID=$(cat /tmp/agent_chat_backend.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        print_ok "后端进程 (PID: $PID) 已停止"
    else
        print_warn "后端进程 (PID: $PID) 已不存在"
    fi
    rm -f /tmp/agent_chat_backend.pid
fi

# 停止前端 (通过 PID 文件)
if [ -f /tmp/agent_chat_frontend.pid ]; then
    PID=$(cat /tmp/agent_chat_frontend.pid)
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null
        print_ok "前端进程 (PID: $PID) 已停止"
    else
        print_warn "前端进程 (PID: $PID) 已不存在"
    fi
    rm -f /tmp/agent_chat_frontend.pid
fi

# 兜底：按端口强杀（lsof / fuser）
kill_port() {
    local port=$1
    local name=$2

    # macOS / Linux: lsof
    if command -v lsof &>/dev/null; then
        local pids=$(lsof -ti :"$port" 2>/dev/null)
        if [ -n "$pids" ]; then
            echo "$pids" | xargs kill -9 2>/dev/null
            print_ok "已释放端口 $port ($name)"
        fi
