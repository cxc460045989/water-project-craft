#!/bin/bash
# ============================================================
#  微机全自动水分测定仪 — 麒麟 Linux 一键打包
#  使用 main_app_kylin.spec（onedir 模式）
#  兼容: 麒麟 x86_64 / ARM64
# ============================================================
set -e

GREEN='\033[0;32m' YELLOW='\033[1;33m' RED='\033[0;31m' NC='\033[0m'
echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  微机全自动水分测定仪 — 麒麟 Linux 打包${NC}"
echo -e "${GREEN}================================================${NC}"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. 环境检查（麒麟系统多版本并存，强制 python3.9）
echo -e "${YELLOW}[1/5] 检查 Python3.9...${NC}"
PY_BIN="python3.9"
command -v $PY_BIN &>/dev/null || { echo -e "${RED}未找到 python3.9${NC}"; exit 1; }
echo "  $($PY_BIN --version)"

# 2. 依赖
echo -e "${YELLOW}[2/5] 检查依赖...${NC}"
$PY_BIN -c "import PySide2.QtWidgets" 2>/dev/null || {
    echo -e "${YELLOW}  安装 PySide2 + pyserial + pyinstaller...${NC}"
    $PY_BIN -m pip install --user PySide2 pyserial pyinstaller pyinstaller-hooks-contrib
}
$PY_BIN -m py_compile main_app.py || { echo -e "${RED}语法错误${NC}"; exit 1; }
echo -e "${GREEN}  依赖 OK${NC}"

# 3. 清理
echo -e "${YELLOW}[3/5] 清理...${NC}"
rm -rf build/ dist/ __pycache__/
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
rm -rf ~/.cache/pyinstaller 2>/dev/null || true
echo "  已清理"

# 4. 打包
echo -e "${YELLOW}[4/5] PyInstaller 打包（约 1-3 分钟）...${NC}"
$PY_BIN -m PyInstaller --clean --noconfirm main_app_kylin.spec

# 5. 验证
echo -e "${YELLOW}[5/5] 验证...${NC}"
DIR="dist/水分测定仪"
EXE="$DIR/水分测定仪"
[ -f "$EXE" ] || { echo -e "${RED}未找到 $EXE${NC}"; ls -la dist/ 2>/dev/null; exit 1; }
chmod +x "$EXE"

# 兜底复制 data.db
cp -f data.db "$DIR/"
echo -e "${GREEN}  data.db -> $DIR/${NC}"

echo ""
echo -e "${GREEN}================== 打包成功 ==================${NC}"
echo -e "${GREEN}  程序: $EXE${NC}"
echo -e "${GREEN}  目录: $DIR/${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${YELLOW}运行:${NC} ./$EXE"
