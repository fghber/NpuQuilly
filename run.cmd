@echo off
setlocal
set "project=%~dp0"
set "pythonw=%project%NpuQuilly\.venv\Scripts\pythonw.exe"
set "main=%project%NpuQuilly\main.py"

if not exist "%main%" (
    echo Keep run.cmd in the NpuQuilly project folder.
    pause
    exit /b 1
)
if not exist "%pythonw%" (
    echo Run Setup-NpuQuilly.ps1 -Model grammar-fast in PowerShell first.
    echo See README.md for setup.
    pause
    exit /b 1
)

start "" /d "%project%." "%pythonw%" "%main%"
if errorlevel 1 (
    echo Could not start NpuQuilly. Rerun Setup-NpuQuilly.ps1 and try again.
    pause
    exit /b 1
)
