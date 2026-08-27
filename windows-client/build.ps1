[CmdletBinding()]
param(
    [string]$ReleaseOrigin = "https://causalagent.example.com",
    [ValidateSet("onedir", "onefile")]
    [string]$PackageMode = "onedir",
    [string]$IconPath = ""
)

$ErrorActionPreference = "Stop"
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$pythonPath = Join-Path $repositoryRoot ".venv-desktop\Scripts\python.exe"
$desktopRoot = Join-Path $repositoryRoot "windows-client"
$entrypoint = Join-Path $repositoryRoot "Run_causal.py"

if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw "未找到桌面虚拟环境，请先安装 windows-client/requirements-desktop.txt。"
}

try {
    $originUri = [Uri]$ReleaseOrigin
} catch {
    throw "Release origin 必须是 HTTPS origin。"
}
if ($originUri.Scheme -ne "https" -or $originUri.AbsolutePath -ne "/" -or $originUri.Query -or $originUri.Fragment -or $originUri.UserInfo) {
    throw "Release origin 必须是 HTTPS origin。"
}

$releaseOriginTempDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ("causalagent-desktop-" + [guid]::NewGuid().ToString("N"))
$releaseOriginFile = Join-Path $releaseOriginTempDirectory "release_origin.txt"
try {
    New-Item -ItemType Directory -Path $releaseOriginTempDirectory -Force | Out-Null
    [System.IO.File]::WriteAllText(
        $releaseOriginFile,
        "$ReleaseOrigin`n",
        [System.Text.UTF8Encoding]::new($false)
    )

    $pyinstallerArguments = @(
        "-m", "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name", "CausalAgent",
        "--paths", $desktopRoot,
        "--hidden-import", "webview.platforms.edgechromium",
        "--hidden-import", "webview.platforms.winforms",
        "--collect-all", "pywebview",
        "--add-data", "$releaseOriginFile;causalagent_desktop"
    )
    if ($PackageMode -eq "onefile") {
        $pyinstallerArguments += "--onefile"
    }
    if ($IconPath) {
        $resolvedIcon = (Resolve-Path -LiteralPath $IconPath).Path
        if ([IO.Path]::GetExtension($resolvedIcon).ToLowerInvariant() -ne ".ico") {
            throw "Windows 应用图标必须是 .ico 文件。"
        }
        $pyinstallerArguments += @("--icon", $resolvedIcon)
    }
    $pyinstallerArguments += $entrypoint

    Push-Location $repositoryRoot
    try {
        & $pythonPath @pyinstallerArguments
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller 构建失败。"
        }
    } finally {
        Pop-Location
    }
} finally {
    Remove-Item -LiteralPath $releaseOriginTempDirectory -Recurse -Force -ErrorAction SilentlyContinue
}
