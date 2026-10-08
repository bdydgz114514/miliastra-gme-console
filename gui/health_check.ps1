# Read-only health check for MiliastraGME.
# ASCII-only on purpose: launched via run-check.ps1 which supplies the Chinese labels.
param(
    [string]$Title = 'MiliastraGME health check'
)

$ErrorActionPreference = 'Continue'
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

# repo root = parent of this script (script lives in <root>\gui)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $scriptDir
Set-Location -LiteralPath $root

function Find-Python {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $bases = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python310\python.exe'),
        'C:\Python312\python.exe',
        'C:\Python311\python.exe'
    )
    foreach ($candidate in $bases) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

$python = Find-Python
if (-not $python) {
    Write-Host ''
    Write-Host '[!] Python not found. Install Python 3.10+ and add it to PATH.' -ForegroundColor Red
    Write-Host ''
    Read-Host 'Press Enter to close'
    exit 1
}

Write-Host ''
Write-Host '-----------------------------------------------' -ForegroundColor DarkGray
Write-Host $Title -ForegroundColor Cyan
Write-Host '-----------------------------------------------' -ForegroundColor DarkGray
Write-Host ''

& $python (Join-Path 'gui' 'persistence_check.py')
$code = $LASTEXITCODE

Write-Host ''
if ($code -ne 0) {
    Write-Host ("[!] script exited with {0}; some info may be unavailable (permission or path issue)." -f $code) -ForegroundColor Yellow
}
Write-Host '-----------------------------------------------'
Read-Host 'Done. Press Enter to close this window'
exit $code
