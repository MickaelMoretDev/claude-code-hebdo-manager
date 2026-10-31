# Uninstall claude-usage-budget on Windows and remove the statusLine entry (config kept).
$ErrorActionPreference = "SilentlyContinue"
Set-Location $env:USERPROFILE
if (Get-Command pipx) { pipx uninstall claude-usage-budget | Out-Null }
foreach ($py in @("py", "python", "python3")) { if (Get-Command $py) { & $py -m pip uninstall -y claude-usage-budget | Out-Null; break } }
Write-Host "> package removed"
$claudeDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE ".claude" }
$settingsPath = Join-Path $claudeDir "settings.json"
if (Test-Path $settingsPath) {
  $obj = Get-Content $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json
  if ($obj.statusLine -and ($obj.statusLine.command -like "*claude-usage-budget*")) {
    $obj.PSObject.Properties.Remove("statusLine")
    [System.IO.File]::WriteAllText($settingsPath, ($obj | ConvertTo-Json -Depth 20), (New-Object System.Text.UTF8Encoding $false))
    Write-Host "> statusLine removed from settings.json"
  }
}
Write-Host "Config kept: $claudeDir\usage-budget.json"
