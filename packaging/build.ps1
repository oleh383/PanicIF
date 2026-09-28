# ----------------------------------------------------------------------------
#  PanicIF - Windows installer build
#  (ASCII only - Powershell 5.1 compatible, avoids encoding issues)
#
#  Usage:
#    1) optional: place Apple driver into packaging/drivers/ (see README.txt)
#    2) run:  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
#
#  Results:
#    dist\PanicIF\PanicIF.exe    - runnable .exe (PyInstaller onedir)
#    dist\PanicIF-Setup.exe      - final installer (Inno Setup)
#
#  Version comes from APP_VERSION in app/iphone_panic_diagnostics.py
#  (single source); installer reads ProductVersion from the built .exe.
# ----------------------------------------------------------------------------

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Packaging   = Join-Path $ProjectRoot "packaging"
$DistDir     = Join-Path $ProjectRoot "dist"

Write-Host "==> Python: $((python --version) 2>&1)"

# 1) ensure PyInstaller is installed
$PyInstaller = python -m PyInstaller --version 2>$null
if (-not $PyInstaller) {
    Write-Host "==> Installing PyInstaller..."
    python -m pip install --upgrade --quiet pyinstaller
}

# 2) build onedir exe (no console; DLL/.pyd/data сідають у dist\PanicIF\)
Write-Host "==> Building PanicIF.exe (onedir, takes a few minutes)..."
python -m PyInstaller --noconfirm --clean `
    --distpath $DistDir `
    --workpath (Join-Path $ProjectRoot "build") `
    (Join-Path $Packaging "iphone_panic.spec")

$AppDir   = Join-Path $DistDir "PanicIF"
$Exe      = Join-Path $AppDir "PanicIF.exe"
if (-not (Test-Path $Exe)) { throw "EXE build failed: $Exe not found" }
$ExeSizeMB = [math]::Round((Get-Item $Exe).Length / 1MB, 1)
$AppDirSizeMB = [math]::Round(((Get-ChildItem $AppDir -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)
Write-Host "==> OK: $Exe  (${ExeSizeMB} MB)  -- folder installed size: ${AppDirSizeMB} MB"

# 3) compile Setup installer with Inno Setup (if installed)
$Iscc = @(
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($Iscc) {
    Write-Host "==> Compiling installer with: $Iscc"
    & $Iscc (Join-Path $Packaging "Setup.iss")
    $Setup = Join-Path $DistDir "PanicIF-Setup.exe"
    if (Test-Path $Setup) {
        $SetupSizeMB = [math]::Round((Get-Item $Setup).Length / 1MB, 1)
        Write-Host "==> DONE: $Setup  (${SetupSizeMB} MB)"
    }
} else {
    Write-Host "!! Inno Setup 6 not found. EXE built, but Setup was not created."
    Write-Host "   Download Inno Setup 6: https://jrsoftware.org/isinfo.php"
    Write-Host "   Then run from 'packaging':  ISCC.exe Setup.iss"
}

Write-Host "All done."