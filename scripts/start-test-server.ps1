$ErrorActionPreference='Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$Processes = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'sentinel\.server --port 8081 --data \.runtime/e2e-data' -and $_.ExecutablePath -like '*python*' }
foreach ($TestProcess in $Processes) {
    try { Stop-Process -Id $TestProcess.ProcessId -Force -ErrorAction Stop }
    catch { if (Get-Process -Id $TestProcess.ProcessId -ErrorAction SilentlyContinue) { throw } }
}
New-Item -ItemType Directory -Force '.runtime' | Out-Null
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$env:PYTHONUTF8='1'
$Started = Start-Process -FilePath $Python -ArgumentList '-m','sentinel.server','--port','8081','--data','.runtime/e2e-data' -WorkingDirectory $ProjectRoot -WindowStyle Hidden -RedirectStandardOutput '.runtime\e2e-server.log' -RedirectStandardError '.runtime\e2e-server-error.log' -PassThru
$Started.Id | Set-Content '.runtime\e2e-server.pid'
Write-Output "E2E server launcher: $($Started.Id)"
