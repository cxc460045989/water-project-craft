#!/bin/bash
# ============================================================
#  一键打包脚本 — 微机全自动水分测定仪 (麒麟Linux版)
#  PySide2 + PyInstaller，兼容麒麟 x86/ARM64
# ============================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  微机全自动水分测定仪 PyInstaller 打包脚本${NC}"
echo -e "${GREEN}  麒麟Linux / Ubuntu / Deepin / UOS (x86/ARM64)${NC}"
echo -e "${GREEN}================================================${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 检查 Python3
echo -e "${YELLOW}[1/6] 检查 Python3 环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 python3${NC}"
    exit 1
fi
echo "  Python3: $(python3 --version)"

# 2. 安装依赖
echo -e "${YELLOW}[2/6] 检查依赖 (PySide2 / PyInstaller / pyserial)...${NC}"
python3 -c "import PySide2.QtWidgets" 2>/dev/null || {
    echo -e "${YELLOW}  PySide2 未安装，正在安装...${NC}"
    pip3 install --user PySide2 pyserial pyinstaller
}
python3 -c "import PyInstaller" 2>/dev/null || pip3 install --user pyinstaller

# 语法检查
echo "  语法检查 main_app.py ..."
python3 -m py_compile main_app.py || { echo -e "${RED}main_app.py 语法错误${NC}"; exit 1; }
python3 -m py_compile main_app_debug.py 2>/dev/null || echo "  (debug 入口跳过)"
echo -e "${GREEN}  依赖检查通过${NC}"

# 3. 清理
echo -e "${YELLOW}[3/6] 清理旧产物 + PyInstaller 缓存...${NC}"
rm -rf build/ dist/ __pycache__/
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf ~/.cache/pyinstaller 2>/dev/null || true
echo "  已清理"

# 4. 检查 data.db
echo -e "${YELLOW}[4/6] 检查 data.db...${NC}"
if [ ! -f "data.db" ]; then
    echo -e "${RED}错误: 缺少 data.db，请确保数据库文件在项目根目录${NC}"
    exit 1
fi
echo "  data.db 就绪"

# 5. PyInstaller 打包
echo -e "${YELLOW}[5/6] PyInstaller 打包中（约 1~3 分钟）...${NC}"
pyinstaller --clean --noconfirm main_app.spec

# 6. 验证输出 + 设置权限
echo -e "${YELLOW}[6/6] 验证输出...${NC}"

# Release 验证
RELEASE_DIR="dist/水分测定仪"
RELEASE_EXE="$RELEASE_DIR/水分测定仪"
if [ -f "$RELEASE_EXE" ]; then
    chmod +x "$RELEASE_EXE"
    echo -e "${GREEN}  Release: $RELEASE_EXE${NC}"
else
    echo -e "${RED}  错误: 未找到 Release 可执行文件 ($RELEASE_EXE)${NC}"
    echo "  dist 目录内容:"
    ls -la dist/ 2>/dev/null || echo "  (dist 为空)"
    exit 1
fi

# Debug 验证
DEBUG_EXE="dist/水分测定仪_debug/水分测定仪_debug"
if [ -f "$DEBUG_EXE" ]; then
    chmod +x "$DEBUG_EXE"
    echo -e "${GREEN}  Debug: $DEBUG_EXE${NC}"
else
    echo -e "${YELLOW}  注意: Debug 版本未生成（如不需要可忽略）${NC}"
fi

# 验证 data.db 是否在输出目录
if [ -f "$RELEASE_DIR/data.db" ]; then
    echo -e "${GREEN}  data.db -> $RELEASE_DIR/${NC}"
else
    echo -e "${RED}  警告: data.db 未复制到 Release 输出目录${NC}"
fi

echo ""
echo -e "${GREEN}================== 打包成功！==================${NC}"
echo -e "${GREEN}  程序: $RELEASE_EXE${NC}"
echo -e "${GREEN}  目录: $RELEASE_DIR/${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${YELLOW}运行:${NC} ./$RELEASE_EXE"
echo ""
