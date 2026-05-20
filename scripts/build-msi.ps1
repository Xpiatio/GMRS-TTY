<#
.SYNOPSIS
    Build a self-contained Windows MSI installer for GMRS-TTY.

.DESCRIPTION
    Bundles Python 3.13 embeddable runtime, all Python packages (CPU-only
    torch), and offline ML models into build\win\gmrs-tty_<VERSION>_x64.msi.

    Requirements (run on Windows before executing this script):
        * Python 3.13 on PATH  (for pip-downloading packages and models)
        * WiX v4 toolset:  dotnet tool install --global wix
        * .NET 6.0+ SDK
        * Models already downloaded:  python bootstrap_models.py

    Usage:
        .\scripts\build-msi.ps1                # version 0.0.1
        .\scripts\build-msi.ps1 -Version 0.0.2

    Output:
        build\win\gmrs-tty_<VERSION>_x64.msi   (~1.5 GB — models bundled)
#>

param(
    [string]$Version = "0.0.1"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$REPO_ROOT    = Split-Path -Parent $PSScriptRoot
$BUILD_DIR    = Join-Path $REPO_ROOT "build\win"
$BUNDLE       = Join-Path $BUILD_DIR "bundle"
$PY_EMBED     = Join-Path $BUNDLE "python"
$MSI_OUT      = Join-Path $BUILD_DIR "gmrs-tty_${Version}_x64.msi"
$FILES_WXS    = Join-Path $BUILD_DIR "bundle-files.wxs"
$PRODUCT_WXS  = Join-Path $REPO_ROOT "packaging\windows\product.wxs"

$PY_VERSION   = "3.13.3"
$PY_URL       = "https://www.python.org/ftp/python/$PY_VERSION/python-$PY_VERSION-embed-amd64.zip"
$PY_ZIP       = Join-Path $BUILD_DIR "python-$PY_VERSION-embed-amd64.zip"
$GET_PIP_URL  = "https://bootstrap.pypa.io/get-pip.py"
$GET_PIP      = Join-Path $BUILD_DIR "get-pip.py"

Write-Host ""
Write-Host ">>> GMRS-TTY MSI build — version $Version"
Write-Host ">>> Bundle: $BUNDLE"
Write-Host ">>> Output: $MSI_OUT"
Write-Host ""

# ---------------------------------------------------------------------------
# 0. Pre-flight checks
# ---------------------------------------------------------------------------
if (-not (Get-Command "wix" -ErrorAction SilentlyContinue)) {
    Write-Error @"
WiX v4 toolset not found. Install it with:
    dotnet tool install --global wix
Then re-run this script.
"@
    exit 1
}

$modelsDir = Join-Path $REPO_ROOT "Models\STT"
if (-not (Test-Path $modelsDir)) {
    Write-Error @"
Models\STT\ not found. Download the Whisper model first:
    python bootstrap_models.py
Then re-run this script.
"@
    exit 1
}

# ---------------------------------------------------------------------------
# 1. Reset staging tree
# ---------------------------------------------------------------------------
Write-Host ">>> Resetting bundle directory ..."
if (Test-Path $BUNDLE) { Remove-Item -Recurse -Force $BUNDLE }
New-Item -ItemType Directory -Force -Path $BUILD_DIR | Out-Null
New-Item -ItemType Directory -Force -Path $BUNDLE   | Out-Null

# ---------------------------------------------------------------------------
# 2. Download and extract Python embeddable distribution
# ---------------------------------------------------------------------------
Write-Host ">>> Downloading Python $PY_VERSION embeddable ..."
if (-not (Test-Path $PY_ZIP)) {
    Invoke-WebRequest $PY_URL -OutFile $PY_ZIP
}
Write-Host ">>> Extracting Python embeddable ..."
Expand-Archive -Path $PY_ZIP -DestinationPath $PY_EMBED -Force

# Enable site-packages so pip-installed packages are importable.
# The ._pth file ships with '#import site' commented out.
$pthFile = Get-Item "$PY_EMBED\python*._pth" | Select-Object -First 1
if (-not $pthFile) {
    Write-Error "python*._pth not found in embeddable distribution."
    exit 1
}
(Get-Content $pthFile.FullName) -replace "#import site", "import site" |
    Set-Content $pthFile.FullName
Write-Host "    Enabled site-packages in $($pthFile.Name)"

# ---------------------------------------------------------------------------
# 3. Bootstrap pip into the embeddable Python
# ---------------------------------------------------------------------------
Write-Host ">>> Bootstrapping pip ..."
if (-not (Test-Path $GET_PIP)) {
    Invoke-WebRequest $GET_PIP_URL -OutFile $GET_PIP
}
& "$PY_EMBED\python.exe" $GET_PIP --quiet

# ---------------------------------------------------------------------------
# 4. Install all packages (CPU-only torch to avoid CUDA bloat)
# ---------------------------------------------------------------------------
Write-Host ">>> Installing Python packages (this may take several minutes) ..."
& "$PY_EMBED\python.exe" -m pip install `
    --quiet `
    --extra-index-url "https://download.pytorch.org/whl/cpu" `
    -r "$REPO_ROOT\requirements.txt"
if ($LASTEXITCODE -ne 0) {
    Write-Error "pip install failed (exit $LASTEXITCODE)."
    exit 1
}

# ---------------------------------------------------------------------------
# 5. Copy application source
# ---------------------------------------------------------------------------
Write-Host ">>> Copying application source ..."
$appItems = @(
    "gmrs_tty", "main.py", "bootstrap_models.py",
    "requirements.txt", "config.example.json",
    "LICENSE", "NOTICES.md", "README.md"
)
foreach ($item in $appItems) {
    $src = Join-Path $REPO_ROOT $item
    if (Test-Path $src -PathType Container) {
        Copy-Item -Recurse $src $BUNDLE
    } else {
        Copy-Item $src $BUNDLE
    }
}

# __main__.py so the app can run as  python -m gmrs_tty
@"
from gmrs_tty.app import main

if __name__ == "__main__":
    main()
"@ | Set-Content "$BUNDLE\gmrs_tty\__main__.py" -Encoding UTF8

# ---------------------------------------------------------------------------
# 6. Bundle offline models
# ---------------------------------------------------------------------------
Write-Host ">>> Bundling offline models ..."
$modelsSrc = Join-Path $REPO_ROOT "Models"
Copy-Item -Recurse $modelsSrc $BUNDLE

# Strip HuggingFace download cache — only model weights needed at runtime.
Get-ChildItem "$BUNDLE\Models" -Recurse -Directory -Filter ".cache" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem "$BUNDLE\Models" -Recurse -Filter ".gitattributes" |
    Remove-Item -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# 7. Clean up build artefacts from the bundle
# ---------------------------------------------------------------------------
Write-Host ">>> Cleaning build artefacts ..."
Get-ChildItem $BUNDLE -Recurse -Directory -Filter "__pycache__" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem $BUNDLE -Recurse -Directory -Filter "*.dist-info" |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

# ---------------------------------------------------------------------------
# 8. Generate WiX component XML for the bundle directory tree
#    (avoids dependency on 'wix harvest dir' flag compatibility across versions)
# ---------------------------------------------------------------------------
Write-Host ">>> Generating WiX file components ..."

function ConvertTo-WixId([string]$raw) {
    # WiX identifiers: letters, digits, underscore, dot — max 72 chars, no leading digit.
    $id = $raw -replace '[^A-Za-z0-9_.]', '_'
    if ($id -match '^\d') { $id = "f_$id" }
    if ($id.Length -gt 72) { $id = $id.Substring(0, 72) }
    return $id
}

$allFiles = Get-ChildItem -Path $BUNDLE -Recurse -File
$xml = [System.Text.StringBuilder]::new()
$null = $xml.AppendLine('<?xml version="1.0" encoding="UTF-8"?>')
$null = $xml.AppendLine('<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">')
$null = $xml.AppendLine('  <Fragment>')
$null = $xml.AppendLine('    <ComponentGroup Id="BundleComponents" Directory="INSTALLFOLDER">')

$idx = 0
foreach ($file in $allFiles) {
    $rel    = $file.FullName.Substring($BUNDLE.Length).TrimStart('\', '/')
    $cmpId  = "cmp{0:D5}" -f $idx
    $fileId = ConvertTo-WixId($rel)
    # WiX requires KeyPath on the first (and only) file in each component.
    $null = $xml.AppendLine("      <Component Id=`"$cmpId`" Guid=`"*`" Subdirectory=`"$(Split-Path $rel -Parent)`">")
    $null = $xml.AppendLine("        <File Id=`"$fileId`" Source=`"$($file.FullName)`" KeyPath=`"yes`" />")
    $null = $xml.AppendLine("      </Component>")
    $idx++
}

$null = $xml.AppendLine('    </ComponentGroup>')
$null = $xml.AppendLine('  </Fragment>')
$null = $xml.AppendLine('</Wix>')

$xml.ToString() | Set-Content $FILES_WXS -Encoding UTF8
Write-Host "    $idx components written to $FILES_WXS"

# ---------------------------------------------------------------------------
# 9. Build MSI with WiX v4
# ---------------------------------------------------------------------------
Write-Host ">>> Building MSI (WiX v4) ..."
wix build $PRODUCT_WXS $FILES_WXS `
    -d "Version=$Version" `
    -ext WixToolset.UI.wixext `
    -o $MSI_OUT

if ($LASTEXITCODE -ne 0) {
    Write-Error "WiX build failed (exit $LASTEXITCODE)."
    exit 1
}

Write-Host ""
Write-Host ">>> Done."
$sizeMb = [math]::Round((Get-Item $MSI_OUT).Length / 1MB, 0)
Write-Host ">>> $MSI_OUT  ($sizeMb MB)"
