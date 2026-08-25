[CmdletBinding()]
param(
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$projectName = "causalagent-searxng-validation-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
$artifactRoot = Join-Path ([IO.Path]::GetTempPath()) $projectName
$configRoot = Join-Path $artifactRoot "core-config"
$overridePath = Join-Path $artifactRoot "compose.validation.yml"
$composeArgs = @(
    "--project-name", $projectName,
    "-f", (Join-Path $repoRoot "docker-compose.yml"),
    "-f", $overridePath
)

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "docker CLI is unavailable; SearXNG Docker validation cannot run."
}

& docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine is not running; SearXNG Docker validation cannot run."
}

New-Item -ItemType Directory -Path $configRoot -Force | Out-Null
Copy-Item `
    -LiteralPath (Join-Path $repoRoot "searxng/core-config/settings.yml.example") `
    -Destination (Join-Path $configRoot "settings.yml.example")

$configRootForCompose = $configRoot.Replace("\", "/")
@"
services:
  searxng-init:
    container_name: ${projectName}_init
    volumes: !override
      - type: bind
        source: '$configRootForCompose'
        target: /etc/searxng
      - type: bind
        source: ./searxng/init
        target: /init
        read_only: true

  searxng:
    container_name: ${projectName}_core
    volumes: !override
      - type: bind
        source: '$configRootForCompose'
        target: /etc/searxng
      - searxng_validation_core_data:/var/cache/searxng

  valkey:
    container_name: ${projectName}_valkey

volumes:
  searxng_validation_core_data:
"@ | Set-Content -LiteralPath $overridePath -Encoding utf8

function Invoke-ValidationCompose {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & docker compose @composeArgs @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "docker compose $($Arguments -join ' ') failed with exit code $LASTEXITCODE."
    }
}

try {
    Invoke-ValidationCompose -Arguments @("up", "-d", "--wait", "searxng")

    $settingsPath = Join-Path $configRoot "settings.yml"
    if (-not (Test-Path -LiteralPath $settingsPath -PathType Leaf)) {
        throw "searxng-init did not generate settings.yml."
    }

    $settingsText = Get-Content -Raw -LiteralPath $settingsPath
    if ($settingsText -match "ultrasecretkey") {
        throw "settings.yml still contains the secret_key placeholder."
    }
    $firstHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $settingsPath).Hash

    Invoke-ValidationCompose -Arguments @("run", "--rm", "searxng-init")
    $secondHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $settingsPath).Hash
    if ($firstHash -ne $secondHash) {
        throw "A repeated searxng-init run changed the existing settings.yml."
    }

    Invoke-ValidationCompose -Arguments @(
        "exec",
        "-T",
        "searxng",
        "/usr/local/searxng/.venv/bin/python",
        "-c",
        "import urllib.request; response = urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=2); assert response.status == 200; assert response.read() == b'OK'"
    )

    Write-Output "SearXNG Docker validation passed: init atomic target, init idempotency, and /healthz."
}
finally {
    & docker compose @composeArgs down --volumes --remove-orphans *> $null
    if (-not $KeepArtifacts -and (Test-Path -LiteralPath $artifactRoot)) {
        Remove-Item -LiteralPath $artifactRoot -Recurse -Force
    }
    elseif (Test-Path -LiteralPath $artifactRoot) {
        Write-Output "Validation artifacts kept at: $artifactRoot"
    }
}
