# Windows PowerShell 5.1 must not interpret native stderr as a terminating error.
function Invoke-XFolioPython {
    param(
        [string]$Python,
        [string]$Script,
        [string[]]$ScriptArguments = @(),
        [string]$StdoutPath,
        [string]$StderrPath
    )
    $runtimeArguments = @('-X', 'utf8', '-u', ('"{0}"' -f $Script)) + $ScriptArguments
    $runtimeProcess = Start-Process -FilePath $Python -ArgumentList $runtimeArguments -RedirectStandardOutput $StdoutPath -RedirectStandardError $StderrPath -WindowStyle Hidden -Wait -PassThru
    return $runtimeProcess.ExitCode
}
