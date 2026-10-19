$ErrorActionPreference = 'Stop'
$phraseRoot = $PSScriptRoot
$phrasePython = Join-Path $phraseRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $phrasePython)) { throw '请先安装本项目的 Python 3.11 运行环境。' }
Push-Location -LiteralPath $phraseRoot
try {
    & $phrasePython -m pip install -r requirements-phrases.lock
    if ($LASTEXITCODE -ne 0) { throw '自动分段依赖安装失败。' }
    & $phrasePython -m piano.install_phrase_engine
    if ($LASTEXITCODE -ne 0) { throw '自动分段引擎下载或校验失败。' }
} finally { Pop-Location }
