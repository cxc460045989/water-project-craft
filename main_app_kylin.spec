# -*- mode: python ; coding: utf-8 -*-
# ===== 麒麟 Linux 专用 spec（onedir 模式）=====
import sys, os

a = Analysis(
    ["main_app.py"],
    pathex=[],
    binaries=[],
    datas=[("data.db", ".")],
    hiddenimports=[
        "PySide2", "PySide2.QtCore", "PySide2.QtWidgets", "PySide2.QtGui",
        "PySide2.QtPrintSupport",
        "serial", "protocol_layer", "serial_comm",
        "db", "button_styles", "confirm_dialog", "print_report",
        "hardware_check_dialog", "settings_dialog", "data_query_dialog",
        "weigh_dialog", "weigh_controller", "weight_check_dialog",
        "test_controller", "sample_append", "logging_util",
        "batch_weigh_module", "append_sample_worker",
        "temp_control_module", "constant_weight_module",
        "core_data_entities", "workflow_validator",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6", "PyQt5", "PyQt6",
        "PySide2.QtQml", "PySide2.QtQuick", "PySide2.QtPdf",
        "PySide2.QtNetwork", "PySide2.QtWebSockets", "PySide2.QtSvg",
        "PySide2.QtDBus", "PySide2.QtVirtualKeyboard",
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="水分测定仪",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="水分测定仪",
)

# ===== 打包后复制 title.txt(可选) + 创建 logs 目录 =====
import shutil
_title_src = os.path.join(SPECPATH, "title.txt")
_dir = os.path.join(DISTPATH, "水分测定仪")
if not os.path.exists(_dir):
    os.makedirs(_dir)
os.makedirs(os.path.join(_dir, "logs"), exist_ok=True)
if os.path.exists(_title_src):
    shutil.copy2(_title_src, os.path.join(_dir, "title.txt"))
    print("  [SPEC] title.txt -> %s" % _dir)
else:
    print("  [SPEC] title.txt 未找到, 使用默认标题")
