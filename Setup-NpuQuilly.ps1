param([string]$Model)

$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot 'NpuQuilly\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    $localPython = Join-Path $projectRoot '.python312\python.exe'
    if (Test-Path -LiteralPath $localPython) {
        & $localPython -m venv (Join-Path $projectRoot 'NpuQuilly\.venv')
    } else {
        & py -3.12 -m venv (Join-Path $projectRoot 'NpuQuilly\.venv')
    }
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12, then rerun this script.' }
}
$desktopRequirements = Join-Path $projectRoot 'NpuQuilly\requirements.txt'
$serverRequirements = Join-Path $projectRoot 'server\requirements.txt'
& $python -m pip --disable-pip-version-check install -r $desktopRequirements -r $serverRequirements
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python (Join-Path $projectRoot 'server\check_gpu.py')
if ($LASTEXITCODE -ne 0) { throw 'OpenVINO device check failed.' }
if ($Model) {
    & $python (Join-Path $projectRoot 'server\download_model.py') --alias $Model
    if ($LASTEXITCODE -ne 0) { throw "Model download failed for '$Model'." }
}
Write-Host 'Setup complete. Double-click run.cmd to open NpuQuilly.'
