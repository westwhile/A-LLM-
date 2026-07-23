# 只读研究看板启动脚本（阶段 9）
# 默认仅监听 127.0.0.1；从项目根调用 .venv 中的 streamlit。
# 用法：powershell -File scripts/run_dashboard.ps1 [-- 额外 streamlit 参数]
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$App = Join-Path $ProjectRoot "dashboard\app.py"

if (-not (Test-Path $Python)) {
    throw "未找到 .venv 解释器：$Python。请先在项目根创建 .venv 并安装依赖（pip install -e . 与 streamlit）。"
}

Set-Location $ProjectRoot
& $Python -m streamlit run $App --server.address 127.0.0.1 @args
