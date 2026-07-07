#!/bin/bash
# ============================================================
#  一键打包脚本 微机全自动水分测定仪 (麒麟Linux版)
#  使用 PyInstaller 将 PySide6 程序打包为独立可执行目录
# ============================================================

set -e

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  微机全自动水分测定仪 PyInstaller 打包脚本${NC}"
echo -e "${GREEN}  适用于 麒麟Linux / Ubuntu / Deepin / UOS${NC}"
echo -e "${GREEN}================================================${NC}"

# 1. 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${YELLOW}[1/6] 检查 Python3 环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: 未找到 python3，请先安装 Python 3.8+${NC}"
    exit 1
fi
echo "  Python3: $(python3 --version)"

# 2. 检查/安装 PyInstaller
echo -e "${YELLOW}[2/6] 检查 PyInstaller...${NC}"
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "  PyInstaller 未安装，正在安装..."
    pip3 install --user pyinstaller
    echo -e "${GREEN}  PyInstaller 安装完成${NC}"
else
    echo "  PyInstaller 已安装: $(python3 -m PyInstaller --version 2>/dev/null)"
fi

# 3. 检查依赖
echo -e "${YELLOW}[3/6] 检查 Python 依赖...${NC}"
python3 -c "import PySide6.QtWidgets" 2>/dev/null || {
    echo -e "${RED}错误: 缺少 PySide6，请先安装：pip3 install PySide6${NC}"
    exit 1
}
python3 -m py_compile main_app.py 2>/dev/null || {
    echo -e "${RED}错误: main_app.py 语法检查失败${NC}"
    exit 1
}
echo -e "${GREEN}  所有依赖检查通过${NC}"

# 4. 清理旧的打包产物
echo -e "${YELLOW}[4/6] 清理旧的打包产物...${NC}"
rm -rf build/ dist/ __pycache__/
echo "  已清理"

# 5. 执行 PyInstaller 打包
echo -e "${YELLOW}[5/6] 正在打包，请耐心等待（约 1~3 分钟）...${NC}"
echo ""
pyinstaller --clean --noconfirm main_app.spec

# 6. 重命名输出目录
echo -e "${YELLOW}[6/6] 整理输出目录...${NC}"
if [ -d "dist/main_app" ]; then
    mv "dist/main_app" "dist/微机全自动水分测定仪"
    echo "  输出目录: dist/微机全自动水分测定仪/"
fi

# 创建 .desktop 桌面快捷方式
cat > "dist/微机全自动水分测定仪.desktop" << DESKEOF
[Desktop Entry]
Type=Application
Name=微机全自动水分测定仪
Comment=鹤壁市淇天仪器仪表有限公司
Exec=$(pwd)/dist/微机全自动水分测定仪/main_app
Terminal=false
Categories=Office;Science;
DESKEOF
chmod +x "dist/微机全自动水分测定仪.desktop"

echo ""
echo -e "${GREEN}================== 打包成功！==================${NC}"
echo -e "${GREEN}  输出目录: dist/微机全自动水分测定仪/${NC}"
echo -e "${GREEN}  程序路径: dist/微机全自动水分测定仪/main_app${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
echo -e "${YELLOW}直接运行:${NC}"
echo "  ./dist/微机全自动水分测定仪/main_app"
echo ""
echo -e "${YELLOW}创建桌面快捷方式:${NC}"
echo "  cp dist/微机全自动水分测定仪.desktop ~/桌面/"
echo ""