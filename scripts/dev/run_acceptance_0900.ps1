$ErrorActionPreference = 'Stop'
$runtimeRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location -LiteralPath $runtimeRoot
. (Join-Path $PSScriptRoot 'native_process.ps1')
$runtimeExit = Invoke-XFolioPython -Python (Join-Path $runtimeRoot '.venv/Scripts/python.exe') -Script (Join-Path $PSScriptRoot 'acceptance_0900.py') -ScriptArguments @('send') -StdoutPath (Join-Path $runtimeRoot '.cache/local_runtime/2026-11-06_0900_send_task.log') -StderrPath (Join-Path $runtimeRoot '.cache/local_runtime/2026-11-06_0900_send_task.err.log')
exit $runtimeExit
