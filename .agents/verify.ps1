# 系统入口薄壳（Windows）：找到 Python 并转交 tsc.py verify
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = @("py", "python", "python3") | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
if (-not $py) { Write-Host "未找到 Python。请安装后重试：https://www.python.org/downloads/ （安装时勾选 Add python.exe to PATH）"; exit 3 }
& $py (Join-Path $here "tsc.py") verify
exit $LASTEXITCODE
