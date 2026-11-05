param(
    [ValidateSet('setup', 'prepare', 'send')][string]$Phase,
    [string]$TargetDate = '2026-11-06'
)
$ErrorActionPreference = 'Stop'
$runtimeRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $runtimeRoot
$runtimeNow = [TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTimeOffset]::UtcNow, 'Korea Standard Time')
if ($TargetDate -ne '2026-11-06' -or $runtimeNow.ToString('yyyy-MM-dd') -ne $TargetDate) { exit 0 }
$runtimePython = Join-Path $runtimeRoot '.venv/Scripts/python.exe'
$runtimeScript = Join-Path $runtimeRoot 'scripts/dev/local_runtime.py'
$runtimeLog = Join-Path $runtimeRoot ".cache/local_runtime/${TargetDate}_${Phase}_task.log"
if ($Phase -eq 'setup') {
    if ($runtimeNow.Hour -ne 7 -or $runtimeNow.Minute -lt 30 -or $runtimeNow.Minute -ge 45) { exit 0 }
    & $runtimePython $runtimeScript setup *> $runtimeLog
} else {
    & $runtimePython $runtimeScript phase --day $TargetDate --phase $Phase *> $runtimeLog
}
exit $LASTEXITCODE
