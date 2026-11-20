# Install the bridge as a hidden, current-user Windows logon task.
$ErrorActionPreference = 'Stop'

$TaskName = 'T3 Code (Gemini) Bridge'
$Account = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$Launcher = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'start-bridge.ps1')).Path
$PowerShell = Join-Path $PSHOME 'powershell.exe'
if (-not (Test-Path -LiteralPath $PowerShell)) {
    $PowerShell = (Get-Command powershell.exe).Source
}

$Arguments = '-NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -Background' -f $Launcher
$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument $Arguments -WorkingDirectory $PSScriptRoot
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $Account
$Principal = New-ScheduledTaskPrincipal -UserId $Account -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal `
    -Settings $Settings -Description 'Starts the local T3 Code Gemini bridge in the background.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed '$TaskName' for $Account."
