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
echo -e "${YELLOW}[1/5] 检查 Python3 环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 python3${NC}"
    exit 1
fi
echo "  Python3: $(python3 --version)"

# 2. 安装依赖
echo -e "${YELLOW}[2/5] 检查依赖 (PySide2 / PyInstaller / pyserial)...${NC}"
python3 -c "import PySide2.QtWidgets" 2>/dev/null || {
    echo -e "${YELLOW}  PySide2 未安装，正在安装...${NC}"
    pip3 install --user PySide2 pyserial pyinstaller
}
python3 -c "import PyInstaller" 2>/dev/null || pip3 install --user pyinstaller
python3 -m py_compile main_app.py || { echo -e "${RED}语法错误${NC}"; exit 1; }
echo -e "${GREEN}  依赖检查通过${NC}"

# 3. 清理
echo -e "${YELLOW}[3/5] 清理旧产物 + PyInstaller 缓存...${NC}"
rm -rf build/ dist/ __pycache__/
rm -rf ~/.cache/pyinstaller 2>/dev/null
echo "  已清理"

# 4. PyInstaller 打包
echo -e "${YELLOW}[4/5] PyInstaller 打包中（约 1~3 分钟）...${NC}"
pyinstaller --clean --noconfirm main_app.spec

# 5. 验证输出
echo -e "${YELLOW}[5/5] 验证输出...${NC}"
if [ -f "dist/水分测定仪" ]; then
    chmod +x "dist/水分测定仪"
fi

# 创建 .desktop
echo -e "${GREEN}  整理完成${NC}"

echo ""
echo -e "${GREEN}================== 打包成功！==================${NC}"
echo -e "${GREEN}  程序: dist/水分测定仪${NC}"
echo -e "${GREEN}  目录: dist/水分测定仪/${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${YELLOW}运行:${NC} ./dist/水分测定仪"
echo ""