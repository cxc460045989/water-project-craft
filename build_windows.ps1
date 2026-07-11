# ============================================================
#  一键打包脚本 — 微机全自动水分测定仪 (Windows PowerShell版)
#  使用 PyInstaller 将 PySide2 程序打包为独立可执行目录
# ============================================================

Write-Host "================================================" -ForegroundColor Green
Write-Host "  微机全自动水分测定仪 PyInstaller 打包脚本" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green

# 1. 检查 Python
Write-Host "[1/5] 检查 Python 环境..." -ForegroundColor Yellow
 = python --version 2>&1
if ( -ne 0) {
    Write-Host "错误: 未找到 Python，请先安装 Python 3.8+" -ForegroundColor Red
    exit 1
}
Write-Host "  "

# 2. 检查/安装 PyInstaller
Write-Host "[2/5] 检查 PyInstaller..." -ForegroundColor Yellow
 = python -c "import PyInstaller; print(PyInstaller.__version__)" 2>&1
if ( -ne 0) {
    Write-Host "  PyInstaller 未安装，正在安装..." -ForegroundColor Yellow
    pip install pyinstaller
    Write-Host "  PyInstaller 安装完成" -ForegroundColor Green
} else {
    Write-Host "  PyInstaller 已安装: "
}

# 3. 检查依赖
Write-Host "[3/5] 检查 Python 依赖..." -ForegroundColor Yellow
python -c "import PySide2; print(f'  PySide2 版本: {PySide2.__version__}')" 2>&1
if ( -ne 0) {
    Write-Host "错误: 缺少 PySide2" -ForegroundColor Red
    exit 1
}
python -m py_compile main_app.py 2>&1
if ( -ne 0) {
    Write-Host "错误: main_app.py 语法检查失败" -ForegroundColor Red
    exit 1
}
Write-Host "  所有依赖检查通过" -ForegroundColor Green

# 4. 清理旧的打包产物
Write-Host "[4/5] 清理旧的打包产物..." -ForegroundColor Yellow
Remove-Item -Path build -Recurse -Force -ErrorAction SilentlyContinue
# 保留 dist 目录，避免删除用户 data.db
Write-Host "  已清理"

# 5. 执行 PyInstaller 打包
Write-Host "[5/5] 正在打包，请耐心等待（约 1~3 分钟）..." -ForegroundColor Yellow
Write-Host ""

pyinstaller --clean --noconfirm main_app.spec

# 6. 删除无用 DLL（缩小体积、加快启动）
Write-Host "[6/6] 清理无用 DLL..." -ForegroundColor Yellow
$dllNames = @(
    "opengl32sw.dll",
    "Qt5Pdf.dll", "Qt5Qml.dll", "Qt5QmlModels.dll",
    "Qt5Quick.dll", "Qt5VirtualKeyboard.dll",
    "Qt5WebSockets.dll", "Qt5Network.dll",
    "Qt5DBus.dll", "Qt5Svg.dll",
    "d3dcompiler_47.dll"
)
$outputDirs = @("dist/水分测定仪/_internal/PySide2", "dist/水分测定仪_debug/_internal/PySide2")
foreach ($dir in $outputDirs) {
    if (Test-Path $dir) {
        foreach ($dll in $dllNames) {
            $dllPath = Join-Path $dir $dll
            if (Test-Path $dllPath) { Remove-Item $dllPath -Force; Write-Host "  删除: $dllPath" }
        }
    }
}
Write-Host "  清理完成"

Write-Host ""
Write-Host "================== 打包成功！==================" -ForegroundColor Green
Write-Host "  Release: dist/水分测定仪.exe + dist/水分测定仪/" -ForegroundColor Green
Write-Host "  Debug:   dist/水分测定仪_debug.exe + dist/水分测定仪_debug/" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "直接运行: .\dist\水分测定仪.exe" -ForegroundColor Yellow
Write-Host ""
