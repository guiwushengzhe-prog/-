$ErrorActionPreference = 'Stop'
$pianoRoot = $PSScriptRoot
$pianoPython = Join-Path $pianoRoot '.venv\Scripts\python.exe'
$pianoUrl = 'http://127.0.0.1:18766'
if (-not (Test-Path -LiteralPath $pianoPython)) { throw '本项目运行环境不存在。' }
$pianoListeners = @(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 18766 -State Listen -ErrorAction SilentlyContinue)
foreach ($pianoListener in $pianoListeners) {
    $pianoProcess = Get-CimInstance Win32_Process -Filter "ProcessId = $($pianoListener.OwningProcess)"
    if ($pianoProcess.CommandLine -notmatch '\s-m\s+piano\.server(\s+--port\s+18766)?\s*$') {
        throw '18766端口属于其他程序，已停止重启。'
    }
    $pianoServed = (Invoke-WebRequest "$pianoUrl/app.js" -TimeoutSec 5).Content
    $pianoLocal = [IO.File]::ReadAllText((Join-Path $pianoRoot 'static\app.js'))
    if ($pianoServed -ne $pianoLocal) { throw '当前后台不属于这一份项目，已停止重启。' }
    Stop-Process -Id $pianoListener.OwningProcess
}
Start-Process -FilePath $pianoPython -ArgumentList @('-m','piano.server') -WorkingDirectory $pianoRoot -WindowStyle Hidden
$pianoReady = $false
for ($pianoAttempt = 0; $pianoAttempt -lt 30; $pianoAttempt++) {
    try {
        $null = Invoke-RestMethod "$pianoUrl/api/library" -TimeoutSec 1
        $pianoReady = $true
        break
    } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $pianoReady) { throw '后台尚未就绪，请检查 Python 运行环境。' }
Start-Process $pianoUrl
Write-Host "练习台已更新并打开：$pianoUrl"
