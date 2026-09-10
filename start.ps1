<#
.SYNOPSIS
    Start the API and the web UI locally.

.DESCRIPTION
    One command, no Docker and no database server: the backend stores documents
    in a SQLite file and answers from them directly. Add an LLM API key in the
    UI afterwards if you also want generated answers.

    Both processes run in this window; Ctrl+C stops them together.

.PARAMETER Install
    Install or refresh dependencies before starting. Needed on a fresh clone,
    and after a dependency changes.

.PARAMETER ApiPort
    Port for the API. Default 8000.

.EXAMPLE
    .\start.ps1 -Install
#>
[CmdletBinding()]
param(
    [switch]$Install,
    [int]$ApiPort = 8000
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$backend = Join-Path $root 'backend'
$frontend = Join-Path $root 'frontend'
$python = Join-Path $backend '.venv\Scripts\python.exe'

function Write-Step($message) { Write-Host "==> $message" -ForegroundColor Cyan }
function Write-Warn($message) { Write-Host "    $message" -ForegroundColor Yellow }

# ---- Prerequisites ---------------------------------------------------------

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js is not installed or not on PATH. Install Node 20+ from https://nodejs.org"
}

if (-not (Test-Path (Join-Path $root '.env'))) {
    Write-Step 'Creating .env from .env.example'
    Copy-Item (Join-Path $root '.env.example') (Join-Path $root '.env')
}

# ---- Dependencies ----------------------------------------------------------

$needsBackendInstall = $Install -or -not (Test-Path $python)
$needsFrontendInstall = $Install -or -not (Test-Path (Join-Path $frontend 'node_modules'))

if ($needsBackendInstall) {
    Write-Step 'Installing backend dependencies'
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Push-Location $backend
        try {
            if (-not (Test-Path $python)) { & uv venv }
            $env:VIRTUAL_ENV = Join-Path $backend '.venv'
            & uv pip install -e ".[dev]"
        } finally { Pop-Location }
    }
    else {
        # No uv: fall back to the stdlib venv module and pip.
        if (-not (Test-Path $python)) {
            $systemPython = (Get-Command python -ErrorAction SilentlyContinue).Source
            if (-not $systemPython) {
                throw "Python 3.12 is not installed or not on PATH. Install it from https://python.org"
            }
            & $systemPython -m venv (Join-Path $backend '.venv')
        }
        Push-Location $backend
        try { & $python -m pip install -e ".[dev]" } finally { Pop-Location }
    }
}

if ($needsFrontendInstall) {
    Write-Step 'Installing frontend dependencies'
    Push-Location $frontend
    try { & npm install } finally { Pop-Location }
}

if (-not (Test-Path $python)) {
    throw "Backend virtualenv is missing. Re-run with -Install."
}

# ---- Run -------------------------------------------------------------------

$jobs = @()
try {
    Write-Step "Starting API on http://127.0.0.1:$ApiPort"
    # --reload-dir app, not a bare --reload: the default watches the whole
    # backend directory, including .data/, so uploading a document would restart
    # the server mid-request and strand that document at "pending".
    $api = Start-Process -FilePath $python `
        -ArgumentList @(
            '-m', 'uvicorn', 'app.main:app',
            '--host', '127.0.0.1', '--port', "$ApiPort",
            '--reload', '--reload-dir', 'app'
        ) `
        -WorkingDirectory $backend -PassThru -NoNewWindow
    $jobs += $api

    # The UI calls the API from the browser, so it has to know a non-default port.
    $env:VITE_API_URL = "http://127.0.0.1:$ApiPort"

    Write-Step 'Starting web UI on http://localhost:5173'
    $web = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'dev') `
        -WorkingDirectory $frontend -PassThru -NoNewWindow
    $jobs += $web

    Write-Host ''
    Write-Host '  Open http://localhost:5173 and upload a PDF.' -ForegroundColor Green
    Write-Warn 'Answers come from your documents. Paste an LLM API key in the app to add generated answers.'
    Write-Host '  Ctrl+C stops both processes.'
    Write-Host ''

    while ($true) {
        Start-Sleep -Seconds 1
        foreach ($job in $jobs) {
            if ($job.HasExited) {
                Write-Warn "Process $($job.Id) exited with code $($job.ExitCode). Shutting down."
                return
            }
        }
    }
}
finally {
    foreach ($job in $jobs) {
        if ($job -and -not $job.HasExited) {
            # /T kills the process tree, not just the parent. Both processes
            # spawn children — uvicorn's reloader forks a worker, npm forks
            # vite — and killing only the parent leaves those children running,
            # still holding the database file and the ports.
            & taskkill.exe /PID $job.Id /T /F 2>&1 | Out-Null
        }
    }
    Write-Step 'Stopped.'
}
