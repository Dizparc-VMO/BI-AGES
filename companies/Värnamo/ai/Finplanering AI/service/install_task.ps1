<#
.SYNOPSIS
    Registrerar AI Omplanering som schemalagd uppgift i Windows.

.DESCRIPTION
    Skapar en Task Scheduler-uppgift som kör run_service.py --once på angivna
    tider. Detta är det rekommenderade driftsättet: uppgiften startas av
    Windows, loggas av Windows, startar om efter omstart av servern och kräver
    inga extra beroenden.

    Kontot som anges måste ha:
      - Läsrättighet på källtabellerna i BIzparc_Direct_VMO_AI
      - INSERT/DELETE på tblAIAnglysisGetAoColorCodeList och tblAIAnglysisRun
      - SELECT/UPDATE på dbo.sysRunScript
      - EXECUTE på dbo.uspAIAnglysisPurge
      - "Log on as a batch job" på servern

.EXAMPLE
    # Rekommenderat: pollar dbo.sysRunScript var 5:e minut och kör när
    # laddnings-SP:n satt Status = 0.
    .\install_task.ps1 -RunAsUser "VMO\svc_aiomplanering"

.EXAMPLE
    # Tätare pollning
    .\install_task.ps1 -EveryMinutes 2

.EXAMPLE
    # Fasta klockslag i stället för pollning
    .\install_task.ps1 -Times @("05:30","11:30","17:30")

.EXAMPLE
    .\install_task.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]   $TaskName     = "AI Omplanering Op10",
    [int]      $EveryMinutes = 5,
    [string[]] $Times        = @(),
    [string]   $RunAsUser    = "$env:USERDOMAIN\$env:USERNAME",
    [string]   $PythonExe    = "",
    [switch]   $Uninstall
)

$ErrorActionPreference = "Stop"
$here   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$script = Join-Path $here "run_service.py"

if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Uppgiften '$TaskName' är borttagen."
    } else {
        Write-Output "Ingen uppgift med namnet '$TaskName' hittades."
    }
    return
}

if (-not (Test-Path $script)) {
    throw "Hittar inte run_service.py i $here"
}

# Hitta pythonw.exe (konsollös) om ingen tolk angetts
if ([string]::IsNullOrWhiteSpace($PythonExe)) {
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($null -eq $cmd) { $cmd = Get-Command python.exe -ErrorAction SilentlyContinue }
    if ($null -eq $cmd) { throw "Hittar varken pythonw.exe eller python.exe i PATH. Ange -PythonExe." }
    $PythonExe = $cmd.Source
}
Write-Output "Python : $PythonExe"
Write-Output "Skript : $script"
Write-Output "Konto  : $RunAsUser"

$action = New-ScheduledTaskAction -Execute $PythonExe `
    -Argument ('"{0}" --once' -f $script) -WorkingDirectory $here

if ($Times.Count -gt 0) {
    # Fasta klockslag
    Write-Output "Schema : kl. $($Times -join ', ')"
    $triggers = foreach ($t in $Times) {
        New-ScheduledTaskTrigger -Daily -At ([datetime]::ParseExact($t, "HH:mm", $null))
    }
} else {
    # Pollning: kör dygnet runt med angivet intervall. Varje körning läser
    # dbo.sysRunScript och gör ingenting om SP:n inte satt Status = 0, så
    # tät pollning kostar bara en SELECT.
    Write-Output "Schema : var ${EveryMinutes}:e minut (pollar dbo.sysRunScript)"
    # [TimeSpan]::MaxValue faller i PowerShell 5.1 ("value incorrectly
    # formatted or out of range"). Tio år är i praktiken obegränsat.
    $t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date `
        -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) `
        -RepetitionDuration (New-TimeSpan -Days 3650)
    $triggers = @($t)
}

# IgnoreNew: hoppar över en start om föregående körning fortfarande pågår.
# Tillsammans med applåset i databasen kan två körningar aldrig krocka.
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)

$principal = New-ScheduledTaskPrincipal -UserId $RunAsUser `
    -LogonType Password -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Output "Ersätter befintlig uppgift."
}

Write-Output ""
Write-Output "Ange lösenordet för $RunAsUser i dialogen som följer."
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal `
    -Description "Planerar om Operation 10 mot BIzparc_Direct_VMO_AI och skriver tblAIAnglysisGetAoColorCodeList." | Out-Null

Write-Output ""
Write-Output "Klart. Uppgiften '$TaskName' är registrerad."
Write-Output ""
Write-Output "Testa den nu med:"
Write-Output "    Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "    Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Output ""
Write-Output "Loggar hamnar i: $(Join-Path $here 'logs')"
