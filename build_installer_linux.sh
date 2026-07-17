#!/bin/bash
# ============================================================
#  构建安装包 — 微机全自动水分测定仪 (Linux .run)
#  依赖: 先运行 build_linux.sh 完成 PyInstaller 打包
# ============================================================
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}================================================${NC}"
echo -e "${GREEN}  微机全自动水分测定仪 - 构建安装包${NC}"
echo -e "${GREEN}================================================${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 检查工具链
echo -e "${YELLOW}[1/4] 检查工具链...${NC}"
command -v python3 >/dev/null 2>&1 || { echo -e "${RED}需要 python3${NC}"; exit 1; }
echo "  Python3: $(python3 --version)"

if ! command -v makeself &> /dev/null; then
    echo "  下载 makeself..."
    wget -q https://raw.githubusercontent.com/megastep/makeself/master/makeself.sh -O /tmp/makeself.sh
    chmod +x /tmp/makeself.sh
    MK="/tmp/makeself.sh"
else
    MK=$(command -v makeself)
fi

# 2. 验证 PyInstaller 产物
echo -e "${YELLOW}[2/4] 检查打包产物...${NC}"
RELEASE_DIR="dist/水分测定仪"
RELEASE_EXE="$RELEASE_DIR/水分测定仪"

if [ ! -f "$RELEASE_EXE" ]; then
    echo -e "${RED}错误: 未找到 $RELEASE_EXE${NC}"
    echo "请先运行: bash build_linux.sh"
    exit 1
fi
echo -e "${GREEN}  可执行文件: $RELEASE_EXE${NC}"

# 3. 构建安装包目录
echo -e "${YELLOW}[3/4] 构建安装包目录...${NC}"
PKG_DIR="installer_linux/package"
rm -rf installer_linux/
mkdir -p "$PKG_DIR"

# 复制整个单目录输出
cp -r "$RELEASE_DIR"/* "$PKG_DIR/"

# 启动脚本
cat > "$PKG_DIR/start.sh" << 'SCRIPTEOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$DIR/水分测定仪"
SCRIPTEOF
chmod +x "$PKG_DIR/start.sh"

# .desktop 快捷方式
cat > "$PKG_DIR/moisture.desktop" << DESKEOF
[Desktop Entry]
Type=Application
Name=微机全自动水分测定仪
Comment=鹤壁市淇天仪器仪表有限公司 版本号：20.70
Exec=/opt/鹤壁淇天仪器/微机全自动水分测定仪/start.sh
Icon=/opt/鹤壁淇天仪器/微机全自动水分测定仪/水分测定仪
Terminal=false
Categories=Office;Science;
DESKEOF

# 安装脚本
cat > installer_linux/install.sh << 'INSTEOF'
#!/bin/bash
set -e
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/package"
DEST="/opt/鹤壁淇天仪器/微机全自动水分测定仪"
if [ "$(id -u)" -ne 0 ]; then
    DEST="$HOME/.local/opt/鹤壁淇天仪器/微机全自动水分测定仪"
fi
mkdir -p "$DEST"
cp -r "$SRC/"* "$DEST/"
chmod +x "$DEST/水分测定仪" "$DEST/start.sh"
if [ -d "$HOME/桌面" ]; then
    cp "$DEST/moisture.desktop" "$HOME/桌面/"
    chmod +x "$HOME/桌面/moisture.desktop"
elif [ -d "$HOME/Desktop" ]; then
    cp "$DEST/moisture.desktop" "$HOME/Desktop/"
    chmod +x "$HOME/Desktop/moisture.desktop"
fi
if [ "$(id -u)" -eq 0 ]; then
    cp "$DEST/moisture.desktop" /usr/share/applications/ 2>/dev/null || true
fi
echo ""
echo "========================================"
echo "  安装完成！"
echo "  安装路径: $DEST"
echo "  桌面快捷方式已创建"
echo "========================================"
echo ""
if [ -n "$DISPLAY" ]; then
    "$DEST/start.sh" &
fi
exit 0
INSTEOF
chmod +x installer_linux/install.sh

echo -e "${GREEN}  安装包目录已构建${NC}"

# 4. 制作自解压安装包
echo -e "${YELLOW}[4/4] 制作自解压安装包...${NC}"
mkdir -p dist
"$MK" --gzip --notemp --follow --noprogress \
    "$PKG_DIR/" \
    "dist/微机全自动水分测定仪_Setup.run" \
    "微机全自动水分测定仪 安装程序" \
    ../install.sh
chmod +x "dist/微机全自动水分测定仪_Setup.run"

echo ""
echo -e "${GREEN}================== 构建成功！==================${NC}"
echo -e "${GREEN}  安装包: dist/微机全自动水分测定仪_Setup.run${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""
