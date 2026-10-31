<#
.SYNOPSIS
  Install / reinstall claude-usage-budget on native Windows (PowerShell).
  Idempotent: safe to re-run for updates.

.USAGE
  powershell -ExecutionPolicy Bypass -File install.ps1
  powershell -ExecutionPolicy Bypass -File install.ps1 -NoTest
#>
[CmdletBinding()]
param(
  [switch]$NoTest
)

$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Here

function Say($msg) { Write-Host "> $msg" -ForegroundColor Cyan }

# ------------------------------------------------------------------ python
$py = $null
foreach ($cand in @("py", "python", "python3")) {
  $cmd = Get-Command $cand -ErrorAction SilentlyContinue
  if ($cmd) {
    try {
      $v = & $cand -c "import sys; print(sys.version_info >= (3, 8))" 2>$null
      if ($v -eq "True") { $py = $cand; break }
    } catch { }
  }
}
if (-not $py) {
  Write-Host "Python 3.8+ not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH') or 'winget install Python.Python.3.12', then re-run." -ForegroundColor Red
  exit 1
}
Say "Python: $py"

# ------------------------------------------------------------------ package
$usedPipx = $false
if (Get-Command pipx -ErrorAction SilentlyContinue) {
  Say "Installing package with pipx (editable, from $Here)"
  & pipx install --force -e "$Here" | Out-Null
  $usedPipx = $true
} else {
  Say "Installing package with pip --user (editable, from $Here)"
  & $py -m pip install --user --quiet -e "$Here"
}

# Locate the console script
$bin = $null
$cmd = Get-Command claude-usage-budget -ErrorAction SilentlyContinue
if ($cmd) { $bin = $cmd.Source }
if (-not $bin) {
  $candidates = @()
  if ($usedPipx) { $candidates += Join-Path $env:USERPROFILE ".local\bin\claude-usage-budget.exe" }
  $scripts = & $py -c "import sysconfig; print(sysconfig.get_path('scripts', 'nt_user'))" 2>$null
  if ($scripts) { $candidates += Join-Path $scripts "claude-usage-budget.exe" }
  foreach ($c in $candidates) { if (Test-Path $c) { $bin = $c; break } }
}
if (-not $bin) {
  Write-Host "Installed, but claude-usage-budget.exe was not found on PATH. Open a new terminal and re-run this script." -ForegroundColor Yellow
  exit 1
}
Say "Executable: $bin"

# ------------------------------------------------------------------ config
$claudeDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE ".claude" }
New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
$cfg = Join-Path $claudeDir "usage-budget.json"
if (-not (Test-Path $cfg)) {
  Say "Creating default config"
  & $bin init | Out-Null
} else {
  Say "Existing config kept: $cfg"
}

# ------------------------------------------------------------------ settings.json
$settingsPath = Join-Path $claudeDir "settings.json"
Say "Updating $settingsPath (statusLine)"
$settings = @{}
if (Test-Path $settingsPath) {
  Copy-Item $settingsPath "$settingsPath.bak" -Force
  try {
    $raw = Get-Content $settingsPath -Raw -Encoding UTF8
    if ($raw.Trim()) {
      $obj = $raw | ConvertFrom-Json
      # Convert PSCustomObject -> hashtable (PowerShell 5.1 compatible)
      $obj.PSObject.Properties | ForEach-Object { $settings[$_.Name] = $_.Value }
    }
  } catch { $settings = @{} }
}
$quotedBin = if ($bin -match " ") { "`"$bin`"" } else { $bin }
$settings["statusLine"] = [ordered]@{
  type    = "command"
  command = "$quotedBin statusline"
  padding = 0
}
$json = $settings | ConvertTo-Json -Depth 20
[System.IO.File]::WriteAllText($settingsPath, $json, (New-Object System.Text.UTF8Encoding $false))
Write-Host "   statusLine.command = $($settings['statusLine'].command)"

# ------------------------------------------------------------------ tests
Say "Statusline render (sample payload)"
Get-Content (Join-Path $Here "examples\statusline-payload.json") -Raw | & $bin statusline
Write-Host ""
if (-not $NoTest) {
  Say "Test notification"
  try { & $bin test-notify } catch { }
}

Write-Host ""
Write-Host "Done. Restart Claude Code to see the statusline." -ForegroundColor Green
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  claude-usage-budget edit                             # open the config"
Write-Host "  claude-usage-budget set ramp 30 45 60 72 84 94 100   # cumulative caps d1..d7"
Write-Host "  claude-usage-budget set lang fr                      # French UI"
Write-Host "  claude-usage-budget simulate 20 40 55 70 80 92 99    # preview a week"
