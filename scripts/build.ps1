param([string]$Python = "python")
$ErrorActionPreference = "Stop"
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
    & $Python -m pytest -q --junitxml=test-results.xml
    if ($LASTEXITCODE -ne 0) { throw "自动化测试未通过，停止构建。" }
    & $Python -m PyInstaller --noconfirm --onefile --windowed --name FolderPilot --version-file scripts/version_info.txt --manifest scripts/FolderPilot.manifest run_folderpilot.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败。" }
    if (!(Test-Path -LiteralPath dist/FolderPilot.exe)) { throw "EXE 未生成。" }
    $resultPath = Join-Path (Get-Location) "dist/smoke-result.json"
    $process = Start-Process -FilePath (Join-Path (Get-Location) "dist/FolderPilot.exe") -ArgumentList @("--smoke-test", "`"$resultPath`"") -WindowStyle Hidden -PassThru
    if (!$process.WaitForExit(60000)) { throw "EXE 启动检查超时，请人工检查进程。" }
    if ($process.ExitCode -ne 0) { throw "EXE 检查退出码：$($process.ExitCode)" }
    if (!(Test-Path -LiteralPath $resultPath)) { throw "EXE 未生成检查结果。" }
    $result = Get-Content -LiteralPath $resultPath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($result.status -ne "passed") { throw "EXE 自检失败。" }
    Copy-Item -LiteralPath README.md -Destination dist/README.md
    Copy-Item -LiteralPath docs/USER_GUIDE.md -Destination dist/USER_GUIDE.md
    Copy-Item -LiteralPath LICENSE -Destination dist/LICENSE
    Copy-Item -LiteralPath docs/RELEASE_NOTES.md -Destination dist/RELEASE_NOTES.md
    & $Python scripts/checksums.py
    if ($LASTEXITCODE -ne 0) { throw "校验信息生成失败。" }
    Write-Host "构建与 EXE 自检完成：dist/FolderPilot.exe"
} finally {
    Pop-Location
}
