$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$python = Join-Path $projectRoot 'NpuQuilly\.venv\Scripts\python.exe'
$pythonw = Join-Path $projectRoot 'NpuQuilly\.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw 'Run Setup-NpuQuilly.ps1 first to create the Python environment.'
}
& $python -c 'import openvino_genai, fastapi, uvicorn, PySide6, httpx, pynput'
if ($LASTEXITCODE -ne 0) { throw 'Dependencies are missing. Run Setup-NpuQuilly.ps1.' }

# The tray process owns its local API. No detached server remains after Quit.
$mainScript = Join-Path $projectRoot 'NpuQuilly\main.py'
Start-Process -FilePath $pythonw -ArgumentList ('"{0}"' -f $mainScript) `
    -WorkingDirectory $projectRoot -WindowStyle Hidden
Write-Host 'NpuQuilly started. The tray app starts its local server and releases its models on Quit.'
Write-Host 'Select text, then press Ctrl+Shift+G for spelling/grammar, or Win+Shift+Q for the menu.'
Write-Host 'Progress and errors: %APPDATA%\NpuQuilly\npuquilly.log'
