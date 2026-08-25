param([switch]$PurgeConfig)
$ErrorActionPreference = "Stop"
function Invoke-Native {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [string[]]$Arguments = @(),
    [int[]]$SuccessCodes = @(0),
    [switch]$Quiet
  )
  if ($Quiet) { & $FilePath @Arguments *> $null } else { & $FilePath @Arguments }
  $Code = $LASTEXITCODE
  if ($SuccessCodes -notcontains $Code) { throw "Native command failed ($Code): $FilePath $($Arguments -join ' ')" }
  return $Code
}
$Data = Join-Path $env:LOCALAPPDATA "LanMouseSuite"
$Config = Join-Path $env:APPDATA "LanMouseSuite\config.json"
$Python = Join-Path $Data "venv\Scripts\python.exe"
if ((Test-Path $Python) -and (Test-Path $Config)) {
  $null = Invoke-Native -FilePath $Python -Arguments @("-m", "lanmouse_suite.cli", "--config", $Config, "all-off") -Quiet
}
$QueryCode = Invoke-Native -FilePath "schtasks.exe" -Arguments @("/Query", "/TN", "Lan Mouse Suite") -SuccessCodes @(0, 1) -Quiet
if ($QueryCode -eq 0) {
  $null = Invoke-Native -FilePath "schtasks.exe" -Arguments @("/Delete", "/TN", "Lan Mouse Suite", "/F") -Quiet
}
$StartupCmd = Join-Path ([Environment]::GetFolderPath("Startup")) "Lan Mouse Suite GUI.cmd"
Remove-Item -Force -ErrorAction SilentlyContinue $StartupCmd
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Data
if ($PurgeConfig) { Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $env:APPDATA "LanMouseSuite") }
Write-Host "Lan Mouse Suite removed. Upstream Lan Mouse and its configuration were not touched."
