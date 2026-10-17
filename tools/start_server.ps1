#requires -version 5.1
<#
.SYNOPSIS
    一键启动机房故障智能诊断助手的开发服务器

.DESCRIPTION
    做这个脚本是为了省掉每次手动敲三行的麻烦：

        cd src
        $env:DEEPSEEK_API_KEY = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY','User')
        python app.py

    其中第二行尤其容易被忘 —— 忘了它服务照样能起来，
    但一问诊就报「请求失败」，很难第一眼看出是 Key 没加载。

    这个脚本会自动处理这些事：
      · 从用户环境变量读取 DEEPSEEK_API_KEY（当前进程没设的话）
      · 检查依赖是否装好
      · 检查 5000 端口是否已被占用（占用则直接打开浏览器，不重复启动）
      · 启动后自动打开浏览器

.PARAMETER Port
    监听端口，默认 5000。

.PARAMETER NoBrowser
    只启动服务，不自动打开浏览器。

.EXAMPLE
    .\tools\start_server.ps1

.EXAMPLE
    .\tools\start_server.ps1 -Port 5001 -NoBrowser
#>

param(
    [int]$Port = 5000,
    [switch]$NoBrowser
)

$ErrorActionPreference = 'Stop'

# 仓库根目录（本脚本在 tools/ 下）
$Root = Split-Path -Parent $PSScriptRoot
$SrcDir = Join-Path $Root 'src'
$AppPy = Join-Path $SrcDir 'app.py'
$Url = "http://127.0.0.1:$Port"

function Write-Step($msg) { Write-Host "  $msg" }
function Write-Ok($msg) { Write-Host "  [OK] $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "  [!] $msg" -ForegroundColor Yellow }
function Write-Err2($msg) { Write-Host "  [X] $msg" -ForegroundColor Red }


Write-Host ''
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host '   机房故障智能诊断助手 · 启动' -ForegroundColor Cyan
Write-Host '==========================================' -ForegroundColor Cyan
Write-Host ''

# ---------- 1. 检查 Python ----------
Write-Step '检查 Python ...'
$python = $null
foreach ($cand in @('python', 'python3', 'py')) {
    $cmd = Get-Command $cand -ErrorAction SilentlyContinue
    if ($cmd) { $python = $cmd.Source; break }
}
if (-not $python) {
    Write-Err2 '找不到 Python，请先安装 Python 3.10 或更高版本'
    Write-Host '      下载地址: https://www.python.org/downloads/'
    exit 1
}

$ver = & $python --version 2>&1
Write-Ok "$ver"

# ---------- 2. 检查依赖 ----------
Write-Step '检查依赖 ...'
$depCheck = & $python -c "import flask, openai, openpyxl" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 '缺少依赖，正在安装 ...'
    & $python -m pip install -r (Join-Path $Root 'requirements.txt') --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Err2 '依赖安装失败，请手动执行：'
        Write-Host "      $python -m pip install -r requirements.txt"
        exit 1
    }
}
Write-Ok 'flask / openai / openpyxl 均已就绪'

# ---------- 3. 加载 API Key ----------
# 这一步最容易漏。忘了它服务能起来，但问诊时报「请求失败」。
Write-Step '加载 DEEPSEEK_API_KEY ...'
if ($env:DEEPSEEK_API_KEY) {
    Write-Ok "当前进程已有（$($env:DEEPSEEK_API_KEY.Length) 字符）"
} else {
    $key = $null
    foreach ($scope in @('User', 'Machine')) {
        $key = [Environment]::GetEnvironmentVariable('DEEPSEEK_API_KEY', $scope)
        if ($key) { break }
    }

    if ($key) {
        $env:DEEPSEEK_API_KEY = $key
        Write-Ok "已从环境变量读取（$($key.Length) 字符）"
    } else {
        Write-Warn2 '没有找到 API Key，AI 诊断会不可用'
        Write-Host '      设置方法（设置后需要新开一个终端）：'
        Write-Host '        [Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "你的key", "User")'
        Write-Host '      申请地址: https://platform.deepseek.com/'
        Write-Host ''
        $ans = Read-Host '      仍然继续启动吗？(y/N)'
        if ($ans -notmatch '^[Yy]') { exit 0 }
    }
}

# ---------- 4. 检查端口 ----------
Write-Step "检查端口 $Port ..."
$inUse = $null
try {
    $inUse = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
             Select-Object -First 1
} catch {
    # 老系统没有 Get-NetTCPConnection，退化成 netstat
    $line = netstat -ano | Select-String ":$Port\s+.*LISTENING" | Select-Object -First 1
    if ($line) { $inUse = @{ OwningProcess = ($line -split '\s+')[-1] } }
}

if ($inUse) {
    $procId = $inUse.OwningProcess
    Write-Warn2 "端口 $Port 已被占用（PID $procId）"
    Write-Step '看这样子服务已经在跑了，直接打开浏览器即可。'
    Write-Host ''
    Write-Host "      地址: $Url" -ForegroundColor Cyan
    if (-not $NoBrowser) { Start-Process $Url }
    Write-Host ''
    Write-Host '  如果想重启，先停掉占用端口的进程：' -ForegroundColor DarkGray
    Write-Host "      Stop-Process -Id $procId -Force" -ForegroundColor DarkGray
    exit 0
}
Write-Ok '端口空闲'

# ---------- 5. 启动 ----------
Write-Host ''
Write-Host "  启动中 ... 浏览器会自动打开 $Url" -ForegroundColor Cyan
Write-Host '  按 Ctrl+C 停止服务' -ForegroundColor DarkGray
Write-Host ''

# 延迟几秒再开浏览器，等服务真正起来
if (-not $NoBrowser) {
    Start-Job -ScriptBlock {
        param($u)
        Start-Sleep -Seconds 4
        Start-Process $u
    } -ArgumentList $Url | Out-Null
}

# 切到 src/ 再启动：app.py 里用的是相对路径（data/、web/）
Push-Location $SrcDir
try {
    & $python app.py
} finally {
    Pop-Location
    Get-Job | Remove-Job -Force -ErrorAction SilentlyContinue
}
