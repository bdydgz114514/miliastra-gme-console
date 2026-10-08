# Creates the two desktop shortcuts. ASCII-only source so Windows PowerShell 5.1
# (which decodes BOM-less files as ANSI) can read it safely.
# Chinese characters are built from code points to keep this file pure ASCII.

$ErrorActionPreference = 'Stop'

# Repo root = the directory that holds this script, so any clone works.
# $PSScriptRoot is set automatically for .ps1 files since PowerShell 3.0
# (including Windows PowerShell 5.1); the fallback covers hosts that clear it.
$root = $PSScriptRoot
if (-not $root) {
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $root) {
    throw 'Cannot determine the repo root: save this as a .ps1 file and run that file.'
}
$root = (Resolve-Path -LiteralPath $root).Path
$desktop = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell

# U+4F53 U+68C0 = "ti jian" (health check)
$checkLabel = [string][char]0x4F53 + [string][char]0x68C0
# U+63A7 U+5236 U+53F0 = "kong zhi tai" (console)
$consoleLabel = [string][char]0x63A7 + [string][char]0x5236 + [string][char]0x53F0

$icon = Join-Path $root 'gui\assets\icon.ico'
$ps1 = Join-Path $root ($checkLabel + '.ps1')

# ---------- 1) GUI console (elevates itself) ----------
$guiPath = Join-Path $desktop ('MiliastraGME ' + $consoleLabel + '.lnk')
$gui = $shell.CreateShortcut($guiPath)
$gui.TargetPath = Join-Path $root 'run-gui-admin.cmd'
$gui.WorkingDirectory = $root
$gui.IconLocation = $icon + ',0'
$gui.Description = 'Open the MiliastraGME console as administrator (tune params / disable audio processing / inject / restore)'
$gui.WindowStyle = 7
$gui.Save()

# ---------- 2) Read-only health check ----------
$checkPath = Join-Path $desktop ('MiliastraGME ' + $checkLabel + '.lnk')
$check = $shell.CreateShortcut($checkPath)
$check.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$check.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $ps1 + '"'
$check.WorkingDirectory = $root
$check.IconLocation = $icon + ',0'
$check.Description = 'Read-only check: are GME audio processing switches still off, is the hosts block active, has the game picked up the new params'
$check.Save()

Write-Output ('Desktop: ' + $desktop)
foreach ($file in @($guiPath, $checkPath)) {
    if (-not (Test-Path -LiteralPath $file)) {
        Write-Output ('MISSING: ' + $file)
        continue
    }
    $s = $shell.CreateShortcut($file)
    Write-Output ''
    Write-Output ('LNK      : ' + (Split-Path -Leaf $file))
    Write-Output ('  target : ' + $s.TargetPath)
    Write-Output ('  args   : ' + $s.Arguments)
    Write-Output ('  start  : ' + $s.WorkingDirectory)
    Write-Output ('  icon   : ' + $s.IconLocation)
    Write-Output ('  target exists: ' + (Test-Path -LiteralPath $s.TargetPath))
}
