param([int]$Port = 8080, [string]$Data = 'data', [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 虚拟环境失败' }
    & $Python -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw '安装 Python 运行依赖失败' }
    & $Python -m pip install --no-deps -e .
    if ($LASTEXITCODE -ne 0) { throw '安装 Python 依赖失败' }
}
if (-not $SkipBuild) {
    Push-Location frontend
    try {
        if (-not (Test-Path node_modules)) { npm.cmd ci --no-audit --no-fund }
        if ($LASTEXITCODE -ne 0) { throw '安装前端依赖失败' }
        npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }
    } finally { Pop-Location }
    & $Python scripts/build_agent.py
    if ($LASTEXITCODE -ne 0) { throw 'Agent 发布包构建失败' }
}
$env:PYTHONUTF8 = '1'
& $Python -m sentinel.server --host 127.0.0.1 --port $Port --data $Data
