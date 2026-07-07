#!/bin/bash
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

echo -e "${YELLOW}[1/5] 检查工具链...${NC}"
command -v python3 >/dev/null 2>&1 || { echo "需要 python3"; exit 1; }
echo "  Python3: $(python3 --version)"

python3 -c "import PyInstaller" 2>/dev/null || pip3 install --user pyinstaller
python3 -c "import PySide2" 2>/dev/null || { 
    echo -e "${RED}错误: 需要 PySide2${NC}"
    echo "运行: pip3 install pyside2"
    exit 1
}

if ! command -v makeself &> /dev/null; then
    echo "  下载 makeself..."
    wget -q https://raw.githubusercontent.com/megastep/makeself/master/makeself.sh -O /tmp/makeself.sh
    chmod +x /tmp/makeself.sh
    MK="/tmp/makeself.sh"
else
    MK=$(command -v makeself)
fi

echo -e "${YELLOW}[2/5] 清理旧产物...${NC}"
rm -rf build/ dist/
echo "  已清理"

echo -e "${YELLOW}[3/5] PyInstaller 打包...${NC}"
python3 -m PyInstaller --onefile --noconsole --clean --noconfirm \
    --name main_app \
    --hidden-import PySide2 \
    --hidden-import PySide2.QtCore \
    --hidden-import PySide2.QtWidgets \
    --hidden-import PySide2.QtGui \
    --exclude-module PySide6 \
    --exclude-module PyQt5 \
    --exclude-module PyQt6 \
    main_app.py
echo -e "${GREEN}  主程序打包完成${NC}"

echo -e "${YELLOW}[4/5] 构建安装包目录...${NC}"
mkdir -p installer_linux/package
cp dist/main_app/main_app installer_linux/package/main_app 2>/dev/null || cp dist/main_app installer_linux/package/main_app

cat > installer_linux/package/start.sh << 'SCRIPTEOF'
#!/bin/bash
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$DIR/main_app"
SCRIPTEOF
chmod +x installer_linux/package/start.sh

cat > installer_linux/package/moisture.desktop << DESKEOF
[Desktop Entry]
Type=Application
Name=微机全自动水分测定仪
Comment=鹤壁市淇天仪器仪表有限公司 版本号：20.70
Exec=/opt/鹤壁淇天仪器/微机全自动水分测定仪/start.sh
Icon=/opt/鹤壁淇天仪器/微机全自动水分测定仪/main_app
Terminal=false
Categories=Office;Science;
DESKEOF

cat > installer_linux/install.sh << 'INSTEOF'
#!/bin/bash
set -e
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="/opt/鹤壁淇天仪器/微机全自动水分测定仪"
if [ "$(id -u)" -ne 0 ]; then
    DEST="$HOME/.local/opt/鹤壁淇天仪器/微机全自动水分测定仪"
fi
mkdir -p "$DEST"
cp -r "$SRC/"* "$DEST/"
chmod +x "$DEST/main_app" "$DEST/start.sh"
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
    "$DEST/main_app" &
fi
exit 0
INSTEOF
chmod +x installer_linux/install.sh

echo -e "${YELLOW}[5/5] 制作自解压安装包...${NC}"
mkdir -p dist
"$MK" --gzip --notemp --follow --noprogress \
    installer_linux/package/ \
    "dist/微机全自动水分测定仪_Setup.run" \
    "微机全自动水分测定仪 安装程序" \
    ../install.sh
chmod +x "dist/微机全自动水分测定仪_Setup.run"
echo ""
echo -e "${GREEN}================== 构建成功！==================${NC}"
echo -e "${GREEN}  安装包: dist/微机全自动水分测定仪_Setup.run${NC}"
echo -e "${GREEN}================================================${NC}"
echo ""