param(
  [string]$UpstreamUrl = "",
  [string]$UpstreamSha256 = "",
  [switch]$Activate
)
$ErrorActionPreference = "Stop"

function Invoke-Native {
  param(
    [Parameter(Mandatory=$true)][string]$FilePath,
    [string[]]$Arguments = @(),
    [switch]$Quiet
  )
  if ($Quiet) { & $FilePath @Arguments *> $null } else { & $FilePath @Arguments }
  $Code = $LASTEXITCODE
  if ($Code -ne 0) { throw "Native command failed ($Code): $FilePath $($Arguments -join ' ')" }
}
function Stop-TaskAndThrow {
  param([string]$Message)
  try { Invoke-Native -FilePath "schtasks.exe" -Arguments @("/End", "/TN", "Lan Mouse Suite") -Quiet } catch { }
  try { Invoke-Native -FilePath "schtasks.exe" -Arguments @("/Delete", "/TN", "Lan Mouse Suite", "/F") -Quiet } catch { }
  throw $Message
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Data = Join-Path $env:LOCALAPPDATA "LanMouseSuite"
$Venv = Join-Path $Data "venv"
$ConfigDir = Join-Path $env:APPDATA "LanMouseSuite"
$Python = $null
$PyArgs = @()
if (Get-Command py.exe -ErrorAction SilentlyContinue) {
  try {
    Invoke-Native -FilePath "py.exe" -Arguments @("-3", "-c", "import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)") -Quiet
    $Python = "py.exe"
    $PyArgs = @("-3")
  } catch { $Python = $null }
}
if (-not $Python -and (Get-Command python.exe -ErrorAction SilentlyContinue)) {
  try {
    Invoke-Native -FilePath "python.exe" -Arguments @("-c", "import sys; raise SystemExit(0 if sys.version_info >= (3,9) else 1)") -Quiet
    $Python = "python.exe"
    $PyArgs = @()
  } catch { $Python = $null }
}
if (-not $Python) { throw "Python 3.9+ is required. The installer tried 'py -3' first, then python.exe." }
Invoke-Native -FilePath $Python -Arguments ($PyArgs + @("-m", "venv", $Venv))
$VenvPython = Join-Path $Venv "Scripts\python.exe"
$GuiPython = Join-Path $Venv "Scripts\pythonw.exe"
if (-not (Test-Path $GuiPython)) { $GuiPython = $VenvPython }
Invoke-Native -FilePath $VenvPython -Arguments @((Join-Path $Root "scripts\install-local.py"))
New-Item -ItemType Directory -Force -Path $ConfigDir, $Data | Out-Null
$Config = Join-Path $ConfigDir "config.json"
$NewConfig = -not (Test-Path $Config)
if ($NewConfig) { Copy-Item (Join-Path $Root "examples\config.example.json") $Config }
if ($UpstreamUrl -or $UpstreamSha256) {
  throw "Explicit upstream download is raw Linux-only. Install a publisher-signed Windows package separately; ZIP bytes will never be written as an executable."
}
$ConfigureArgs = @((Join-Path $Root "scripts\configure-new-config.py"), "--config", $Config)
if ($NewConfig) { $ConfigureArgs += "--new-config" }
Invoke-Native -FilePath $VenvPython -Arguments $ConfigureArgs
if ($NewConfig) {
  Invoke-Native -FilePath $VenvPython -Arguments @("-m", "lanmouse_suite.cli", "--config", $Config, "off") -Quiet
}
$Template = Get-Content -Raw (Join-Path $Root "templates\windows\lanmouse-suite.xml")
$TaskArgs = "-m lanmouse_suite.cli service run"
$TaskXml = $Template.Replace("@CLI@", [System.Security.SecurityElement]::Escape($VenvPython)).Replace("@ARGS@", [System.Security.SecurityElement]::Escape($TaskArgs))
$TaskFile = Join-Path $Data "lanmouse-suite-task.xml"
[System.IO.File]::WriteAllText($TaskFile, $TaskXml, (New-Object System.Text.UTF8Encoding($false)))
$StartupTemplate = Join-Path $Data "Lan Mouse Suite GUI.cmd"
[System.IO.File]::WriteAllText($StartupTemplate, ("@start `"`" `"{0}`" -m lanmouse_suite.gui`r`n" -f $GuiPython), [System.Text.Encoding]::ASCII)
if ($Activate) {
  Invoke-Native -FilePath $VenvPython -Arguments @("-m", "lanmouse_suite.cli", "--config", $Config, "config", "validate")
  $DoctorJson = Invoke-Native -FilePath $VenvPython -Arguments @("-m", "lanmouse_suite.cli", "--config", $Config, "doctor", "--json")
  $Doctor = $DoctorJson | ConvertFrom-Json
  if ($Doctor.checks.executable.status -ne "ok") { throw "Activation refused: doctor executable check is not OK." }
  try { Invoke-Native -FilePath "schtasks.exe" -Arguments @("/End", "/TN", "Lan Mouse Suite") -Quiet } catch { }
  Invoke-Native -FilePath "schtasks.exe" -Arguments @("/Create", "/TN", "Lan Mouse Suite", "/XML", $TaskFile, "/F") -Quiet
  Invoke-Native -FilePath "schtasks.exe" -Arguments @("/Run", "/TN", "Lan Mouse Suite") -Quiet
  $Startup = [Environment]::GetFolderPath("Startup")
  $Task = $null
  for ($Attempt = 0; $Attempt -lt 20; $Attempt++) {
    $Task = Get-ScheduledTask -TaskName "Lan Mouse Suite" -ErrorAction Stop
    if ($Task.State -eq "Running") { break }
    Start-Sleep -Milliseconds 250
  }
  $Action = @($Task.Actions)[0]
  if ([IO.Path]::GetFullPath($Action.Execute) -ne [IO.Path]::GetFullPath($VenvPython)) { Stop-TaskAndThrow "Scheduled Task action executable read-back mismatch." }
  if ($Action.Arguments -ne $TaskArgs) { Stop-TaskAndThrow "Scheduled Task arguments read-back mismatch." }
  if ($Task.State -ne "Running") { Stop-TaskAndThrow "Scheduled Task did not reach Running state: $($Task.State)" }
  Invoke-Native -FilePath "schtasks.exe" -Arguments @("/Query", "/TN", "Lan Mouse Suite", "/XML") -Quiet
  Copy-Item -Force $StartupTemplate (Join-Path $Startup "Lan Mouse Suite GUI.cmd")
  Write-Host "Activated and verified Scheduled Task action/state: $($Task.State)"
} else {
  Write-Host "Staged only: files, task XML, GUI startup template, and config installed; no task/startup activation command was run. Rerun with -Activate."
}
if (-not (Get-Command ssh.exe -ErrorAction SilentlyContinue)) { Write-Warning "Windows OpenSSH Client is required for clipboard, remote control, and screenshot sync." }
Write-Host "Installed. Edit $Config, then run: `"$VenvPython`" -m lanmouse_suite.cli --config `"$Config`" doctor --json"
