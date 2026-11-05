# 사용자 요청: 2026-11-06 본인 아침 뉴스레터 1회. 자격 증명은 action에 포함하지 않는다.
$ErrorActionPreference = 'Stop'
$runtimeRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$runtimeHelper = Join-Path $runtimeRoot 'scripts/dev/run_local_phase.ps1'
$runtimeUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$runtimePrincipal = New-ScheduledTaskPrincipal -UserId $runtimeUser -LogonType Interactive -RunLevel Limited
$runtimeSettings = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
foreach ($runtimeItem in @(
    @{Name='StartDB'; Phase='setup'; At='2026-11-06T07:35:00'},
    @{Name='Prepare'; Phase='prepare'; At='2026-11-06T07:50:00'},
    @{Name='Send'; Phase='send'; At='2026-11-06T08:00:00'}
)) {
    $runtimeAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -File `"$runtimeHelper`" -Phase $($runtimeItem.Phase) -TargetDate 2026-11-06" -WorkingDirectory $runtimeRoot
    $runtimeTrigger = New-ScheduledTaskTrigger -Once -At ([datetime]$runtimeItem.At)
    Register-ScheduledTask -TaskName "XFolio-20261106-$($runtimeItem.Name)" -Action $runtimeAction -Trigger $runtimeTrigger -Settings $runtimeSettings -Principal $runtimePrincipal -Description 'XFolio 11/6 본인 뉴스레터 날짜 한정 인수' -Force | Out-Null
}
Get-ScheduledTask -TaskName 'XFolio-20261106-*' | ForEach-Object {
    $runtimeInfo = $_ | Get-ScheduledTaskInfo
    [pscustomobject]@{Name=$_.TaskName; State=$_.State; NextRunTime=$runtimeInfo.NextRunTime}
}
