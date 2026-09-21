@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"

:: 检测管理员权限；没有就提权重启自身
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo 需要管理员权限，正在请求提权...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================
echo   CH340 / CH341 USB 转串口驱动 一键安装
echo ============================================
echo.
echo [步骤 1/2] 正在把驱动预注册到系统驱动库...
pnputil /add-driver "%~dp0raw\ch341ser.inf" /install >nul 2>&1
if %errorLevel% == 0 (
    echo   [OK] 驱动已预注册。今后任何 CH340 板子插上，Windows 会自动安装，无需再操作。
) else (
    echo   [提示] 系统无 pnputil（较老 Windows），改用官方安装程序静默安装...
    "CH341SER.EXE" /S
    echo   官方安装程序已运行，请按提示完成。
)

echo.
echo [步骤 2/2] 完成。请拔下板子再重新插入一次。
echo   设备管理器里应出现 "USB-SERIAL CH340 (COMx)" 端口。
echo.
pause
