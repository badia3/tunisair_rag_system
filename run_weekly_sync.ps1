$ErrorActionPreference = "Stop"

$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot "venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $python)) {
    throw "Python virtual environment not found. Expected venv\Scripts\python.exe or .venv\Scripts\python.exe."
}

$dataDirectory = Join-Path $projectRoot "data"
New-Item -ItemType Directory -Force -Path $dataDirectory | Out-Null
$logPath = Join-Path $dataDirectory "tunisair_sync.log"
$syncScript = Join-Path $projectRoot "sync_tunisair.py"

& $python $syncScript *>> $logPath
exit $LASTEXITCODE
