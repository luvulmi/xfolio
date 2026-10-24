# 현재 PC에서만 접근하는 가상 미리보기 서버를 실행합니다.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw '먼저 저장소 루트에서 uv sync --extra dashboard를 실행하세요.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonPath -m streamlit run dashboard/app.py `
        --server.address 127.0.0.1 --server.port 8501 `
        --server.headless true --browser.gatherUsageStats false
    $dashboardExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $dashboardExitCode
