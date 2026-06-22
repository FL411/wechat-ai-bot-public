@echo off
setlocal
echo 停止微信监听服务...

:: 方法1: 通过端口5678
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 5678 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Output ('已停止进程: ' + $_.OwningProcess) }"

:: 方法2: 通过端口5679
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 5679 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue; Write-Output ('已停止进程: ' + $_.OwningProcess) }"

:: 方法3: 查找Python进程中的wechat-decrypt
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process python* -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*wechat-decrypt*' -or $_.CommandLine -like '*main.py*' } | ForEach-Object { Stop-Process -Id $_.Id -Force; Write-Output ('已停止Python进程: ' + $_.Id) }"

echo 完成
endlocal
