param([Parameter(Position = 0)][string]$Command)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") {
    Write-Error "autostart.ps1 is for Windows; use ./autostart.sh on macOS and Linux." -ErrorAction Continue
    exit 1
}
$TaskName = "MCP Hub"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = if ($env:PORT) { $env:PORT } else { "4747" }
$Url = "http://127.0.0.1:$Port"
$Log = Join-Path $env:LOCALAPPDATA "mcp-hub\mcp-hub.log"

function Show-Usage {
    Write-Output "Usage: .\autostart.ps1 install | uninstall | restart | status"
    Write-Output ""
    Write-Output "  install    Start the hub at login (and right now)."
    Write-Output "  uninstall  Remove the autostart and stop the hub it started."
    Write-Output "  restart    Restart the hub started by the autostart."
    Write-Output "  status     Show whether the autostart is set up and the hub is running."
}

function Test-Hub {
    try {
        Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 "$Url/api/hub" | Out-Null
        return $true
    } catch {
        return $false
    }
}

function Get-HubTask {
    Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

function Stop-Hub {
    if (Get-HubTask) { Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue }
    $listeners = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        $process = Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue
        if ($process -and $process.ProcessName -like "python*") { Stop-Process -Id $process.Id -Force }
    }
}

function Find-Python {
    foreach ($name in "pythonw.exe", "python.exe") {
        $found = Get-Command $name -ErrorAction SilentlyContinue
        if ($found -and $found.Source -notlike "*\WindowsApps\*") { return $found.Source }
    }
    throw "Python not found. Install Python 3.11 or newer from python.org and try again."
}

function Install-Hub {
    $python = Find-Python
    if (-not (Get-HubTask) -and (Test-Hub)) {
        throw "A hub is already running at $Url. Stop it first, then install."
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Log) | Out-Null
    $action = New-ScheduledTaskAction -Execute $python -WorkingDirectory $Root `
        -Argument "`"$Root\app.py`" --port $Port --log `"$Log`""
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    Register-ScheduledTask -TaskName $TaskName -Description "MCP Hub at http://127.0.0.1:$Port" -Action $action `
        -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Autostart installed: scheduled task `"$TaskName`""
    Write-Output "Hub: $Url - Log: $Log"
}

function Uninstall-Hub {
    Stop-Hub
    if (Get-HubTask) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false }
    Write-Output "Autostart removed."
}

function Restart-Hub {
    if (-not (Get-HubTask)) { throw "Autostart is not set up." }
    Stop-Hub
    Start-ScheduledTask -TaskName $TaskName
    Write-Output "Hub restarted."
}

function Show-Status {
    if (Get-HubTask) {
        Write-Output "Autostart: installed, scheduled task `"$TaskName`""
    } else {
        Write-Output "Autostart: not set up"
    }
    if (Test-Hub) { Write-Output "Hub: running at $Url" } else { Write-Output "Hub: not reachable" }
}

try {
    switch ($Command) {
        "install" { Install-Hub }
        "uninstall" { Uninstall-Hub }
        "restart" { Restart-Hub }
        "status" { Show-Status }
        "" { Show-Usage }
        default { Show-Usage; exit 1 }
    }
} catch {
    Write-Error $_.Exception.Message -ErrorAction Continue
    exit 1
}
