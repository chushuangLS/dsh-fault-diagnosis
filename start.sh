#!/usr/bin/env bash
#
# 机房故障智能诊断助手 · 一键启动（Linux / macOS）
#
# 用法：
#   ./start.sh              # 端口 5000，自动打开浏览器
#   ./start.sh 5001         # 指定端口
#   NO_BROWSER=1 ./start.sh # 不自动打开浏览器
#
# Windows 用户请改用 start.bat。

set -euo pipefail

PORT="${1:-5000}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="$ROOT/src"
URL="http://127.0.0.1:${PORT}"

ok()   { printf '  [OK] %s\n' "$1"; }
warn() { printf '  [!] %s\n' "$1"; }
err()  { printf '  [X] %s\n' "$1"; }

echo
echo '=========================================='
echo '   机房故障智能诊断助手 · 启动'
echo '=========================================='
echo

# ---------- 1. Python ----------
printf '  检查 Python ...\n'
PYTHON=""
for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1; then
        PYTHON="$cand"
        break
    fi
done

if [ -z "$PYTHON" ]; then
    err '找不到 Python，请先安装 Python 3.10 或更高版本'
    exit 1
fi
ok "$($PYTHON --version 2>&1)"

# ---------- 2. 依赖 ----------
printf '  检查依赖 ...\n'
if ! "$PYTHON" -c 'import flask, openai, openpyxl' >/dev/null 2>&1; then
    warn '缺少依赖，正在安装 ...'
    "$PYTHON" -m pip install -q -r "$ROOT/requirements.txt"
fi
ok 'flask / openai / openpyxl 均已就绪'

# ---------- 3. API Key ----------
# 这一步最容易漏：忘了它服务能起来，但一问诊就报「请求失败」
printf '  加载 DEEPSEEK_API_KEY ...\n'
if [ -n "${DEEPSEEK_API_KEY:-}" ]; then
    ok "当前环境已有（${#DEEPSEEK_API_KEY} 字符）"
else
    warn '没有找到 API Key，AI 诊断会不可用'
    echo '      设置方法（写进 ~/.bashrc 或 ~/.zshrc 后重开终端）：'
    echo '        export DEEPSEEK_API_KEY="你的key"'
    echo '      申请地址: https://platform.deepseek.com/'
    echo
    read -r -p '      仍然继续启动吗？(y/N) ' ans
    case "$ans" in
        [Yy]*) ;;
        *) exit 0 ;;
    esac
fi

# ---------- 4. 端口 ----------
printf '  检查端口 %s ...\n' "$PORT"
if command -v lsof >/dev/null 2>&1 && lsof -i ":$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    warn "端口 $PORT 已被占用"
    printf '  看这样子服务已经在跑了，直接打开浏览器即可。\n\n'
    printf '      地址: %s\n\n' "$URL"
    if [ -z "${NO_BROWSER:-}" ]; then
        (xdg-open "$URL" >/dev/null 2>&1 || open "$URL" >/dev/null 2>&1 || true)
    fi
    exit 0
fi
ok '端口空闲'

# ---------- 5. 启动 ----------
echo
printf '  启动中 ... 浏览器会自动打开 %s\n' "$URL"
echo '  按 Ctrl+C 停止服务'
echo

if [ -z "${NO_BROWSER:-}" ]; then
    ( sleep 4
      xdg-open "$URL" >/dev/null 2>&1 || open "$URL" >/dev/null 2>&1 || true ) &
fi

# 切到 src/ 再启动：app.py 里用的是相对路径（data/、web/）
cd "$SRC_DIR"
exec "$PYTHON" app.py
