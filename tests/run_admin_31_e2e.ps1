param(
    [switch]$ReuseExisting,
    [switch]$KeepSeededData
)

$ErrorActionPreference = "Stop"

function New-Admin31Secret {
    param([int]$Bytes = 24)
    $buffer = New-Object byte[] $Bytes
    $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($buffer)
    } finally {
        $generator.Dispose()
    }
    return [Convert]::ToBase64String($buffer).Replace("+", "A").Replace("/", "B").TrimEnd("=")
}

function Assert-Admin31Exit {
    param([string]$Step)
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

$primaryContainer = "causalchat31e2e_mysql_primary"
$replicaContainer = "causalchat31e2e_mysql_replica"
$existingContainers = docker ps -a --format "{{.Names}}"
Assert-Admin31Exit "docker ps"
$primaryExists = $existingContainers -contains $primaryContainer
$replicaExists = $existingContainers -contains $replicaContainer
if (($primaryExists -or $replicaExists) -and -not $ReuseExisting) {
    throw "Existing 3.1 E2E containers found; refusing to overwrite or delete them."
}
if ($ReuseExisting -and -not ($primaryExists -and $replicaExists)) {
    throw "ReuseExisting requires both isolated 3.1 database containers."
}
if ($KeepSeededData -and -not $ReuseExisting) {
    throw "KeepSeededData requires ReuseExisting."
}

$env:MYSQL_ROOT_PASSWORD = New-Admin31Secret
$env:MYSQL_DATABASE = "causalchat31e2e"
$env:MYSQL_USER = "compat31"
$env:MYSQL_PASSWORD = New-Admin31Secret
$env:MYSQL_WRITE_USER = "writer31"
$env:MYSQL_WRITE_PASSWORD = New-Admin31Secret
$env:MYSQL_READ_USER = "reader31"
$env:MYSQL_READ_PASSWORD = New-Admin31Secret
$env:MYSQL_REPLICA_STATUS_USER = "status31"
$env:MYSQL_REPLICA_STATUS_PASSWORD = New-Admin31Secret
$env:MYSQL_REPLICATION_USER = "replica31"
$env:MYSQL_REPLICATION_PASSWORD = New-Admin31Secret
$env:API_KEY = "isolated-e2e-not-used"
$env:BASE_URL = "https://example.invalid"
$env:MODEL = "isolated-e2e-model"
$env:SECRET_KEY = New-Admin31Secret 48
$env:E2E_ADMIN_PASSWORD = New-Admin31Secret
$env:E2E_USER_PASSWORD = New-Admin31Secret

$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_WRITE_HOST = "127.0.0.1"
$env:MYSQL_READ_HOSTS = "127.0.0.2"
$env:MYSQL_PORT = "13317"
$env:MYSQL_POOL_SIZE_WRITE = "5"
$env:MYSQL_POOL_SIZE_READ = "5"
$env:MYSQL_REPLICA_MAX_LAG_SECONDS = "5"
$env:DB_INSPECTION_QUERY_TIMEOUT_MS = "3000"
$env:ADMIN_FRONTEND_DIST_DIR = (Resolve-Path "admin-frontend/dist").Path
$env:ADMIN_VITE_DEV_SERVER_URL = ""
$env:FLASK_ENV = "development"
$env:PLAYWRIGHT_BASE_URL = "http://127.0.0.1:15011"
$env:PLAYWRIGHT_ADMIN_USERNAME = "e2e-admin-31"
$env:PLAYWRIGHT_ADMIN_PASSWORD = $env:E2E_ADMIN_PASSWORD
$env:PLAYWRIGHT_USER_USERNAME = "e2e-user-31"
$env:PLAYWRIGHT_USER_PASSWORD = $env:E2E_USER_PASSWORD
$env:PLAYWRIGHT_CHANNEL = "msedge"

$flaskProcess = $null
$monitorProcess = $null
try {
    if ($ReuseExisting) {
        $rotationSql = @"
ALTER USER 'compat31'@'%' IDENTIFIED BY '$($env:MYSQL_PASSWORD)';
ALTER USER 'writer31'@'%' IDENTIFIED BY '$($env:MYSQL_WRITE_PASSWORD)';
ALTER USER 'reader31'@'%' IDENTIFIED BY '$($env:MYSQL_READ_PASSWORD)';
ALTER USER 'status31'@'%' IDENTIFIED BY '$($env:MYSQL_REPLICA_STATUS_PASSWORD)';
FLUSH PRIVILEGES;
"@
        $rotationSql | docker exec -i $primaryContainer sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD"'
        Assert-Admin31Exit "rotate isolated credentials"
    } else {
        docker-compose `
            -p causalchat31e2e `
            -f docker-compose.replica.yml `
            -f docker-compose.admin-e2e.yml `
            up -d --build mysql-primary mysql-replica
        Assert-Admin31Exit "start isolated MySQL pair"
    }

    $healthDeadline = [DateTime]::UtcNow.AddMinutes(3)
    do {
        $primaryHealth = docker inspect --format "{{.State.Health.Status}}" $primaryContainer
        $replicaHealth = docker inspect --format "{{.State.Health.Status}}" $replicaContainer
        if ($primaryHealth -eq "healthy" -and $replicaHealth -eq "healthy") {
            break
        }
        if ([DateTime]::UtcNow -ge $healthDeadline) {
            throw "Timed out waiting for the isolated 3.1 MySQL pair."
        }
        Start-Sleep -Seconds 2
    } while ($true)

    if ($ReuseExisting) {
        python -c "from app.db import get_write_connection; c=get_write_connection(); c.close()"
        Assert-Admin31Exit "database connectivity"
    } else {
        python Database/database_init.py
        Assert-Admin31Exit "database readiness"
    }
    alembic upgrade head
    Assert-Admin31Exit "empty database upgrade"
    alembic downgrade c2d3e4f5a6b7
    Assert-Admin31Exit "3.1 migration downgrade"
    alembic upgrade head
    Assert-Admin31Exit "existing structure upgrade"
    if (-not $KeepSeededData) {
        python -m tests.seed_admin_31_e2e
        Assert-Admin31Exit "seed isolated fixtures"
    } else {
        $env:E2E_REFRESH_PASSWORDS_ONLY = "true"
        try {
            python -m tests.seed_admin_31_e2e
            Assert-Admin31Exit "refresh isolated login fixtures"
        } finally {
            Remove-Item Env:E2E_REFRESH_PASSWORDS_ONLY -ErrorAction SilentlyContinue
        }
    }

    $monitorProcess = Start-Process `
        -FilePath "python" `
        -ArgumentList "-m", "Database.monitor_worker" `
        -PassThru `
        -WindowStyle Hidden
    $flaskProcess = Start-Process `
        -FilePath "python" `
        -ArgumentList "-m", "flask", "--app", "Causalchat", "run", "--host", "127.0.0.1", "--port", "15011", "--no-reload" `
        -PassThru `
        -WindowStyle Hidden

    $webDeadline = [DateTime]::UtcNow.AddMinutes(2)
    do {
        try {
            $response = Invoke-WebRequest -Uri "$($env:PLAYWRIGHT_BASE_URL)/" -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -eq 200) {
                break
            }
        } catch {
            if ($flaskProcess.HasExited) {
                throw "The isolated 3.1 Flask process exited early."
            }
        }
        if ([DateTime]::UtcNow -ge $webDeadline) {
            throw "Timed out waiting for the isolated 3.1 Flask server."
        }
        Start-Sleep -Seconds 1
    } while ($true)

    Push-Location admin-frontend
    try {
        npm run test:e2e
        Assert-Admin31Exit "real Playwright E2E"
    } finally {
        Pop-Location
    }
    python -m tests.verify_admin_31_e2e
    Assert-Admin31Exit "database verification"
} finally {
    if ($flaskProcess -and -not $flaskProcess.HasExited) {
        Stop-Process -Id $flaskProcess.Id
    }
    if ($monitorProcess -and -not $monitorProcess.HasExited) {
        Stop-Process -Id $monitorProcess.Id
    }
    Write-Host "Isolated database containers and volumes were retained: $primaryContainer, $replicaContainer"
}
