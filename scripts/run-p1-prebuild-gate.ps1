[CmdletBinding()]
param(
    [string]$DoclingArtifactsDir = (Join-Path $env:USERPROFILE ".cache\\docling\\models"),
    [string]$WorkerImage = "causalagent-demopaper-worker",
    [long]$MinimumFreeBytes = 2GB,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$BaseComposeFile = Join-Path $RepositoryRoot "docker-compose.replica.yml"
$GateComposeFile = Join-Path $RepositoryRoot "docker-compose.p1.yml"
$ActivePointer = Join-Path $RepositoryRoot "Agent\\knowledge_base\\multimodal_runtime\\active_index.json"
$ProductionDefaults = Join-Path $RepositoryRoot "Agent\\knowledge_base\\multimodal\\production_defaults.json"
$SourceRoot = Join-Path $RepositoryRoot "Agent\\knowledge_base\\source"
$AssetRoot = Join-Path $RepositoryRoot "Agent\\knowledge_base\\multimodal_assets"
$IndexRoot = Join-Path $RepositoryRoot "Agent\\knowledge_base\\multimodal_indexes"

function Invoke-DockerCompose {
    <# Executes a Docker Compose command and turns a non-zero exit code into a gate failure. #>
    param([string[]]$Arguments)

    if ($DryRun) {
        Write-Host ("DRY RUN: docker " + ($Arguments -join " "))
        return
    }
    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose command failed with exit code $LASTEXITCODE."
    }
}

function Invoke-GateContainer {
    <# Runs one explicit command in the offline P1 container without building or starting dependencies. #>
    param([string[]]$Command)

    $arguments = @(
        "compose", "-f", $BaseComposeFile, "-f", $GateComposeFile,
        "--profile", "p1", "run", "--rm", "--no-deps", "p1-gate"
    ) + $Command
    Invoke-DockerCompose -Arguments $arguments
}

function Invoke-GatePython {
    <# Sends Python source through standard input so Docker Compose cannot alter embedded quotes. #>
    param([string]$Source)

    $arguments = @(
        "compose", "-f", $BaseComposeFile, "-f", $GateComposeFile,
        "--profile", "p1", "run", "--rm", "--no-deps", "-T", "p1-gate", "python", "-"
    )
    if ($DryRun) {
        Write-Host ("DRY RUN: docker " + ($arguments -join " ") + " < Python probe")
        return
    }
    $Source | & docker @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose Python probe failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $DoclingArtifactsDir -PathType Container)) {
    throw "Docling artifacts directory is missing: $DoclingArtifactsDir"
}
if (-not (Test-Path -LiteralPath $ActivePointer -PathType Leaf)) {
    throw "Active pointer is missing: $ActivePointer"
}
if (-not (Test-Path -LiteralPath $BaseComposeFile -PathType Leaf) -or -not (Test-Path -LiteralPath $GateComposeFile -PathType Leaf)) {
    throw "P1 Compose configuration is incomplete."
}
if (-not (Test-Path -LiteralPath $ProductionDefaults -PathType Leaf)) {
    throw "Frozen production defaults are missing: $ProductionDefaults"
}

$defaults = Get-Content -LiteralPath $ProductionDefaults -Raw | ConvertFrom-Json
$requiredSources = @($defaults.sources | Where-Object { $_.required })
if ($requiredSources.Count -ne 2) {
    throw "P1 expects exactly two required frozen knowledge sources."
}
$sourceChecks = foreach ($source in $requiredSources) {
    $sourcePath = Join-Path $RepositoryRoot $source.path
    $exists = Test-Path -LiteralPath $sourcePath -PathType Leaf
    $actualHash = if ($exists) { (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant() } else { $null }
    [PSCustomObject]@{
        path = $source.path
        required = [bool]$source.required
        format = [IO.Path]::GetExtension($source.path).TrimStart('.').ToLowerInvariant()
        exists = $exists
        expected_sha256 = $source.sha256
        actual_sha256 = $actualHash
    }
}
if ($sourceChecks | Where-Object { -not $_.exists -or $_.format -ne "pdf" -or $_.actual_sha256 -ne $_.expected_sha256 }) {
    throw "Frozen required knowledge source validation failed."
}
Write-Host ($sourceChecks | ConvertTo-Json -Compress)

function Get-DirectoryBytes {
    <# Returns the current file footprint without creating, deleting, or modifying any path. #>
    param([string]$Path)

    return [int64](Get-ChildItem -LiteralPath $Path -Recurse -Force -File | Measure-Object -Property Length -Sum).Sum
}

if (-not (Test-Path -LiteralPath $AssetRoot -PathType Container) -or -not (Test-Path -LiteralPath $IndexRoot -PathType Container)) {
    throw "P1 asset or staged-index root is missing."
}
$sourceBytes = Get-DirectoryBytes -Path $SourceRoot
$parserArtifactBudgetBytes = Get-DirectoryBytes -Path $AssetRoot
$vectorIndexBudgetBytes = Get-DirectoryBytes -Path $IndexRoot
$bufferBytes = 512MB
$estimatedBytes = $sourceBytes + $parserArtifactBudgetBytes + $vectorIndexBudgetBytes + $bufferBytes
$requiredBytes = [Math]::Max($estimatedBytes, $MinimumFreeBytes)
$freeBytes = (Get-PSDrive -Name (Split-Path -Qualifier $RepositoryRoot).TrimEnd(':')).Free
if ($freeBytes -lt $requiredBytes) {
    throw "Insufficient disk space for full ingestion: need at least $requiredBytes bytes, have $freeBytes bytes."
}
Write-Host (([PSCustomObject]@{ source_bytes = $sourceBytes; parser_artifact_budget_bytes = $parserArtifactBudgetBytes; vector_index_budget_bytes = $vectorIndexBudgetBytes; buffer_bytes = $bufferBytes; estimated_bytes = $estimatedBytes; minimum_free_bytes = $MinimumFreeBytes; required_bytes = $requiredBytes; free_bytes = $freeBytes }) | ConvertTo-Json -Compress)

$env:MULTIMODAL_DOCLING_HOST_DIR = (Resolve-Path -LiteralPath $DoclingArtifactsDir).Path
$env:P1_WORKER_IMAGE = $WorkerImage
$pointerHashBefore = (Get-FileHash -LiteralPath $ActivePointer -Algorithm SHA256).Hash

Push-Location $RepositoryRoot
try {
    $composePrefix = @("compose", "-f", $BaseComposeFile, "-f", $GateComposeFile, "--profile", "p1")
    Invoke-DockerCompose -Arguments ($composePrefix + @("config", "--quiet"))

    if (-not $DryRun) {
        & docker image inspect $WorkerImage *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Required worker image is not available locally: $WorkerImage. P1 never builds or pulls images."
        }
    }

    $mountProbe = @'
import json
import os
from pathlib import Path

checks = {
    "embedding_model_readable": os.access("/app/Agent/knowledge_base/models/bge-small-zh-v1.5", os.R_OK),
    "embedding_snapshot_complete": all((Path("/app/Agent/knowledge_base/models/bge-small-zh-v1.5") / name).is_file() for name in ("config.json", "modules.json", "model.safetensors", "tokenizer.json", "vocab.txt")),
    "docling_assets_readable": os.access("/opt/docling-models", os.R_OK),
    "assets_writable": os.access("/app/Agent/knowledge_base/multimodal_assets", os.W_OK),
    "indexes_writable": os.access("/app/Agent/knowledge_base/multimodal_indexes", os.W_OK),
    # The production pipeline stages each immutable version directly at <index-root>/mm_*.
    "staged_index_parent_writable": os.access("/app/Agent/knowledge_base/multimodal_indexes", os.W_OK),
    "active_pointer_readable": os.access("/app/Agent/knowledge_base/multimodal_runtime/active_index.json", os.R_OK),
    "active_pointer_writable": os.access("/app/Agent/knowledge_base/multimodal_runtime/active_index.json", os.W_OK),
    "rapidocr_assets_present": all((Path("/opt/docling-models") / relative).is_file() for relative in (
        "RapidOcr/onnx/PP-OCRv6/det/PP-OCRv6_det_small.onnx",
        "RapidOcr/onnx/PP-OCRv4/cls/ch_ppocr_mobile_v2.0_cls_mobile.onnx",
        "RapidOcr/onnx/PP-OCRv6/rec/PP-OCRv6_rec_small.onnx",
    )),
    "layout_model_present": any(Path("/opt/docling-models").rglob("model.safetensors")),
}
if not all(checks[name] for name in ("embedding_model_readable", "embedding_snapshot_complete", "docling_assets_readable", "assets_writable", "indexes_writable", "staged_index_parent_writable", "active_pointer_readable", "rapidocr_assets_present", "layout_model_present")):
    raise SystemExit(json.dumps(checks, ensure_ascii=False))
if checks["active_pointer_writable"]:
    raise SystemExit("active pointer must be read-only in the P1 container")
print(json.dumps(checks, ensure_ascii=False))
'@
    Invoke-GatePython -Source $mountProbe

    $embeddingProbe = @'
import json
from Agent.knowledge_base.multimodal.index import _embeddings, embedding_fingerprint

first = _embeddings()
second = _embeddings()
first_vector = first.embed_query("离线 embedding P1 smoke")
second_vector = second.embed_query("离线 embedding P1 smoke")
first_fingerprint = embedding_fingerprint()
second_fingerprint = embedding_fingerprint()
if first_fingerprint != second_fingerprint or len(first_vector) != 512 or len(second_vector) != 512:
    raise SystemExit("embedding fingerprint or vector dimension check failed")
print(json.dumps({"first_fingerprint": first_fingerprint, "second_fingerprint": second_fingerprint, "dimension": len(first_vector)}, ensure_ascii=False))
'@
    Invoke-GatePython -Source $embeddingProbe
    Invoke-GateContainer -Command @("python", "-m", "Agent.knowledge_base.multimodal.cli", "inspect")
    Invoke-GateContainer -Command @("python", "-m", "unittest", "tests.test_multimodal_contracts.MultimodalContractTests.test_docling_pdf_parser_returns_page_scoped_text", "-v")
}
finally {
    Pop-Location
    $pointerHashAfter = (Get-FileHash -LiteralPath $ActivePointer -Algorithm SHA256).Hash
    if ($pointerHashBefore -ne $pointerHashAfter) {
        throw "Active pointer changed during P1: $pointerHashBefore -> $pointerHashAfter"
    }
    Write-Host "P1 active pointer remained unchanged: $pointerHashAfter"
}

if ($DryRun) {
    Write-Host "P1 dry-run validation passed."
} else {
    Write-Host "P1 checks passed."
}
