# ============================================================
#  微机全自动水分测定仪 — 一键构建安装包 (Windows)
#  流程：PyInstaller 打包 → NSIS 制作安装包
# ============================================================

Write-Host "================================================" -ForegroundColor Green
Write-Host "  微机全自动水分测定仪 — 一键构建安装包" -ForegroundColor Green
Write-Host "  流程: PyInstaller -> NSIS -> Setup.exe" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green

# 获取脚本所在目录
 = Split-Path -Parent System.Management.Automation.InvocationInfo.MyCommand.Definition
Set-Location 

# ---------- 1. 检查工具 ----------
Write-Host "[1/5] 检查工具链..." -ForegroundColor Yellow

 = python --version 2>&1
if ( -ne 0) {
    Write-Host "错误: 未找到 Python" -ForegroundColor Red
    exit 1
}
Write-Host "  Python: "

try {
     = python -m PyInstaller --version 2>&1
    Write-Host "  PyInstaller: " -ForegroundColor Green
} catch {
    Write-Host "  PyInstaller 未安装..." -ForegroundColor Yellow
    python -m pip install pyinstaller
}

 = @(
    "C:\Program Files\NSIS\makensis.exe",
    "C:\Program Files (x86)\NSIS\makensis.exe"
)
 = False
foreach ( in ) {
    if (Test-Path ) {
         = True
         = 
        break
    }
}
if (-not ) {
     = (Get-Command makensis -ErrorAction SilentlyContinue).Source
    if () {  = True }
}
if (-not ) {
    Write-Host "错误: 未找到 NSIS (makensis.exe)" -ForegroundColor Red
    Write-Host "请从 https://nsis.sourceforge.io/Download 下载安装" -ForegroundColor Yellow
    exit 1
}
Write-Host "  NSIS: " -ForegroundColor Green

# ---------- 2. 清理 ----------
Write-Host "[2/5] 清理..." -ForegroundColor Yellow
Remove-Item "\build" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item "\dist" -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "  已清理"

# ---------- 3. 图标 ----------
Write-Host "[3/5] 生成图标..." -ForegroundColor Yellow
python "\generate_icon.py"
Write-Host "  图标已生成"

# ---------- 4. PyInstaller ----------
Write-Host "[4/5] PyInstaller 打包..." -ForegroundColor Yellow
python -m PyInstaller --clean --noconfirm "\main_app.spec"
if ( -ne 0) {
    Write-Host "打包失败！" -ForegroundColor Red
    exit 1
}
 = "\dist\main_app.exe"
 = (Get-Item ).Length
New-Item "\installer" -ItemType Directory -Force | Out-Null
Copy-Item  "\installer\main_app.exe" -Force
Copy-Item "\app_icon.ico" "\installer\app_icon.ico" -Force
Write-Host "  exe: 0.0 MB" -ForegroundColor Green

# ---------- 5. NSIS ----------
Write-Host "[5/5] NSIS 制作安装包..." -ForegroundColor Yellow
Set-Location "\installer"
&  installer.nsi
Set-Location 

 = "\installer\微机全自动水分测定仪_Setup.exe"
if (Test-Path ) {
     = (Get-Item ).Length
    Write-Host ""
    Write-Host "================== 构建成功！==================" -ForegroundColor Green
    Write-Host "  安装包: " -ForegroundColor Green
    Write-Host "  大小: 0.00 MB" -ForegroundColor Green
    Write-Host "================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "双击运行安装包即可安装程序" -ForegroundColor Yellow
} else {
    Write-Host "制作安装包失败！" -ForegroundColor Red
}
