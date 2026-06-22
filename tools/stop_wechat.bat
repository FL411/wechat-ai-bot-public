@echo off
powershell -NoProfile -Command "Get-Process python* | Stop-Process -Force"
echo 已停止所有Python进程
pause
