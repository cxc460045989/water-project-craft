# 微机全自动水分测定仪 — 编译与安装包部署方案

> 鹤壁市淇天仪器仪表有限公司 版本号：20.70
> 基于 Python + PySide2 (Qt5) 构建，同时支持 Windows 7+ 和 麒麟Linux x86/ARM

---

## 项目文件说明

```
waterProject/
  main_app.py                  # 主程序 (PySide2, 单文件)
  app_icon.ico                 # 程序图标

  ==== Windows 编译链 ====
  build_windows.ps1            # PS脚本: PyInstaller 打包 exe
  build_installer.ps1          # PS脚本: PyInstaller + NSIS 制作安装包
  installer/
    installer.nsi              # NSIS 安装包脚本
    main_app.exe               # (编译后) 单文件 exe
    app_icon.ico               # 程序图标

  ==== 麒麟Linux 编译链 ====
  build_linux.sh               # 脚本: PyInstaller 打包可执行文件
  build_installer_linux.sh     # 脚本: PyInstaller + makeself 制作 .run 安装包

  README.md                    # 本说明文档
```

---

## 第一部分：Windows 编译与安装包制作

### 流程概述

```
main_app.py (源码)
    |
    v (PyInstaller --onefile)
main_app.exe (单文件, 42MB)
    |
    v (NSIS 编译 installer.nsi)
微机全自动水分测定仪_Setup.exe (安装包, ~20MB)
```

### 前置工具安装

1. **Python 3.9 ~ 3.12**（PySide2 不支持 Python 3.13+）
   下载: https://www.python.org/downloads/

```powershell
# 安装 PySide2 + pyserial + PyInstaller
pip install pyside2 pyserial pyinstaller

# 安装 NSIS（安装包制作工具）
# 下载: https://nsis.sourceforge.io/Download
# 安装时勾选 Include Modern UI 2
```

### 方法A：仅编译 exe（不制作安装包）

```powershell
.\build_windows.ps1
```

输出: \dist/main_app.exe\（42MB，单文件，双击直接运行）

### 方法B：完整安装包（推荐）

```powershell
# 以管理员身份运行 PowerShell
.\build_installer.ps1
```

该脚本自动完成:

### Windows 安装包功能

双击 \installer/微机全自动水分测定仪_Setup.exe\：
- 选择安装路径（默认 \Program Files\）
- 自动创建桌面快捷方式
- 自动创建开始菜单快捷方式
- 支持控制面板卸载

\n---\n\n## 第二部分：麒麟Linux 编译与安装包制作\n\n### 流程概述\n\n`\nmain_app.py (源码)\n    |\n    v (PyInstaller --onefile)\nmain_app (单文件可执行程序)\n    |\n    v (makeself --gzip)\n微机全自动水分测定仪_Setup.run (自解压安装包)\n`\n\n### 前置工具安装（麒麟系统上执行）\n\n`ash\n# 1. 安装 Python 依赖\npip3 install pyside2 pyserial pyinstaller\n\n# 2. 安装 makeself（自解压安装包工具）\nwget https://raw.githubusercontent.com/megastep/makeself/master/makeself.sh\nchmod +x makeself.sh\nsudo mv makeself.sh /usr/local/bin/makeself\n`\n\n### 方法A：仅编译可执行文件\n\n`ash\nchmod +x build_linux.sh\n./build_linux.sh\n# 输出: dist/main_app（单文件，双击运行）\n`\n\n### 方法B：完整安装包（推荐）\n\n`ash\nchmod +x build_installer_linux.sh\n./build_installer_linux.sh\n# 输出: dist/微机全自动水分测定仪_Setup.run\n`\n\n\n### 麒麟安装包功能\n\n1. 双击安装\n2. 自动创建桌面快捷方式\n3. 自动启动程序\n\n---\n\n## 常见问题\n\n### Q1: PyInstaller 打包失败\n- Python 版本必须是 3.9~3.12\n- PySide2 不支持 Python 3.13+\n\n### Q2: 麒麟系统运行 .run 没反应\n- 检查文件权限：chmod +x *.run\n- 终端运行查看错误信息\n- 可能缺少 libfuse：sudo apt install libfuse2\n\n### Q3: exe 太大\n- 包含完整 PySide2/Qt5 运行时，正常大小 40~50MB\n- NSIS 安装包会压缩到约 20MB\n\n### Q4: 如何卸载\n- Windows: 控制面板 → 添加/删除程序\n- 麒麟: sudo rm -rf /opt/鹤壁淇天仪器/\n\n---\n\n## 验证清单\n\n- [ ] Windows 下 PyInstaller 打包成功\n- [ ] Windows 安装包正常安装、卸载\n- [ ] 麒麟Linux 下 PyInstaller 打包成功\n- [ ] 麒麟Linux .run 安装包正常安装\n- [ ] 桌面快捷方式创建正常\n- [ ] 程序启动后界面完整、按钮可点击\n- [ ] 所有按钮点击控制台输出日志\n- [ ] 布局自适应窗口缩放\n- [ ] 数据表格正确显示23行数据\n