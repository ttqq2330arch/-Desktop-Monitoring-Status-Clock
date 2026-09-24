#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把采集端和看门狗打包成免 Python 的 exe，给没装 Python 的电脑用。

产物
    dist/pc-monitor-portable/
        monitor.exe     采集端（无窗口，登录自启、常驻、自连自重）
        flash.exe       烧录器（console 窗口）
        安装.bat        注册 monitor.exe 的登录自启任务并立即启动
        卸载.bat        删除计划任务并结束采集
        暂停采集.bat    停任务+结束采集，把 COM 口让出来（烧录固件前用）
        恢复采集.bat    恢复任务并重新拉起采集
        烧录固件.bat    暂停→烧录→恢复
        使用说明.txt

说明（2026-09-19 改）
    已去掉 watcher 看门狗。monitor 自身就会常驻等待板子、自动连、断线重连、
    串口号变了重扫；看门狗唯一不可替代的作用「开机把它拉起来」改由任务计划的
    登录自启（AtLogOn + 崩溃自动重启）承担，少一个常驻进程。

为什么要这套东西
    另一台电脑没装 Python 时，脚本版跑不起来，也装不了依赖。
    PyInstaller 把解释器 + 依赖 + 脚本打进单个 exe，拷过去就能用。

两个必须注意的点
    1. 用 --windowed：常驻程序不能有控制台窗口，否则桌面上一直挂着黑框。
       windowed 模式下 sys.stdout 为 None，脚本已内置兜底把输出写进日志文件。
    2. 打包后 __file__ 指向临时解压目录（_MEIPASS），日志会写进去然后随进程
       退出丢失。所以 monitor.py / flash.py 里统一用 app_dir() 定位目录。

依赖（打包机必须装全，缺一会打出坏 exe）
    pip install pyinstaller esptool psutil pyserial nvidia-ml-py
    - esptool   → flash.exe 的运行时依赖（动态 import，静态分析扫不到）
    - pynvml(nvidia-ml-py) → monitor.exe 读 GPU（monitor.py 里 try import）

用法
    python build_portable.py
"""

import glob
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "dist", "pc-monitor-portable")

# PyInstaller 对中文路径不总是友好（踩过链接器打不开文件的问题），
# 中间产物一律放纯 ASCII 目录，打完再拷回来。
BUILD_ROOT = os.path.join(os.environ.get("TEMP", r"C:\Windows\Temp"), "pcmonitor_build")

# (脚本, 产物名, 窗口模式, 额外参数)
#   常驻的 monitor 必须 windowed，否则桌面一直挂黑框；
#   flash 反过来要 console——烧录时得让用户在窗口里看到进度和报错。
TARGETS = (
    # monitor 里 printers 走 try-import（可选功能），显式声明避免被静态分析漏掉，
    # 否则打包出来的 exe 会缺 printers 模块、打印机页永远「无数据」。
    # paho.mqtt.client 在 printers.py 的 AnycubicLAN._session() 函数内 import，
    # 静态分析同样扫不到，必须一并 hidden-import（2026-09-24 加局域网 MQTT 后端）。
    ("monitor.py", "monitor", "windowed",
     ["--hidden-import", "printers", "--hidden-import", "paho.mqtt.client",
      "--hidden-import", "paho.mqtt.properties", "--hidden-import",
      "paho.mqtt.subscribeoptions"]),
    ("flash.py", "flash", "console",
     # esptool 用 importlib 动态加载各芯片 target，静态分析扫不到，必须整个收进来
     ["--collect-submodules", "esptool", "--collect-data", "esptool"]),
)

# 任务名。旧版是 PCMonitorWatch（看门狗），新版只跑 monitor.exe。
# 安装/卸载脚本的清理列表同时覆盖两个名字，方便从旧版平滑迁移。
TASK_NAME = "PCMonitor"
LEGACY_TASK_NAME = "PCMonitorWatch"


def say(msg=""):
    print(msg, flush=True)


def build_one(script, name, mode="windowed", extra=None):
    """打一个 exe，返回是否成功。"""
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
    ]
    if mode == "windowed":
        cmd.append("--windowed")
    cmd += [
        "--clean",
        "--noconfirm",
        "--name", name,
        "--distpath", os.path.join(BUILD_ROOT, "dist"),
        "--workpath", os.path.join(BUILD_ROOT, "work"),
        "--specpath", os.path.join(BUILD_ROOT, "spec"),
        # monitor.py 里 pynvml 是在函数内 try import，静态分析可能扫不到
        "--hidden-import", "pynvml",
        "--hidden-import", "serial.tools.list_ports",
        "--exclude-module", "tkinter",
        "--log-level", "WARN",
    ]
    cmd += list(extra or [])
    cmd.append(script)
    say("  打包 %s ..." % name)
    r = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True)
    if r.returncode != 0:
        say("  失败：")
        say((r.stdout or "")[-2000:])
        say((r.stderr or "")[-2000:])
        return False
    return True


def stop_running():
    """结束产物目录里正在跑的实例。

    Windows 上 exe 运行期间文件被锁，覆盖复制会 PermissionError，
    rmtree 也会失败。重打包前必须先停掉。
    """
    killed = []
    try:
        import psutil
        for p in psutil.process_iter(["pid", "name"]):
            try:
                if (p.info.get("name") or "").lower() in ("monitor.exe", "watcher.exe"):
                    p.kill()
                    killed.append(p.info["name"])
            except Exception:
                pass
    except ImportError:
        for n in ("monitor.exe", "watcher.exe"):
            subprocess.run(["taskkill", "/f", "/im", n], capture_output=True)

    if killed:
        say("  已结束运行中的 %s（否则文件被锁，覆盖不了）" % ", ".join(sorted(set(killed))))
        time.sleep(2)


def restart_task():
    """打包杀掉了实例，装完顺手把采集任务拉回来。起不来也不拦，提示手动恢复。"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Start-ScheduledTask -TaskName '%s' -ErrorAction Stop;"
             "(Get-ScheduledTask -TaskName '%s').State" % (TASK_NAME, TASK_NAME)],
            capture_output=True, text=True, timeout=60)
        out = (r.stdout or "").strip()
        state = out.splitlines()[-1] if out else ""
        if state:
            say("  采集任务已重新拉起：%s" % state)
            return
    except Exception:
        pass
    say("  采集任务没能自动拉起，双击「安装.bat」恢复")


def copy_firmware():
    """把编译产物和 boot_app0 拷进 firmware/。

    boot_app0.bin 不在工程目录里，在 Arduino 框架包里，得单独找——
    它是 OTA 数据区的初始内容，漏烧会让板子卡在启动循环。
    """
    build = os.path.normpath(os.path.join(HERE, "..", "esp32", ".pio", "build", "esp32dev"))
    out = os.path.join(OUT_DIR, "firmware")
    os.makedirs(out, exist_ok=True)

    cands = sorted(glob.glob(os.path.join(
        os.path.expanduser("~"), ".platformio", "packages",
        "framework-arduinoespressif32*", "tools", "partitions", "boot_app0.bin")))

    pairs = (
        (os.path.join(build, "bootloader.bin"), "bootloader.bin"),
        (os.path.join(build, "partitions.bin"), "partitions.bin"),
        (os.path.join(build, "firmware.bin"), "firmware.bin"),
        (cands[0] if cands else None, "boot_app0.bin"),
    )

    ok = True
    for src, name in pairs:
        if not src or not os.path.isfile(src):
            say("  缺 %s（%s）" % (name, src or "没找到路径"))
            ok = False
            continue
        dst = os.path.join(out, name)
        shutil.copy2(src, dst)
        say("  firmware\\%s  %.0f KB" % (name, os.path.getsize(dst) / 1024))
    return ok


def make_bat(name, body):
    """bat 用 UTF-8 存，开头 chcp 65001 切代码页，中文才不会乱码。"""
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\ufeff@echo off\nchcp 65001 >nul\n" + body)
    return path


PS_INSTALL = (
    "$ErrorActionPreference='Stop';"
    "foreach($n in @('{LEGACY}','{TASK}')){"
    "Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue;"
    "Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue};"
    "$a=New-ScheduledTaskAction -Execute '{EXE}';"
    "$t=New-ScheduledTaskTrigger -AtLogOn;"
    "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
    " -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)"
    " -ExecutionTimeLimit (New-TimeSpan -Hours 0);"
    "Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s -Force | Out-Null;"
    "Start-ScheduledTask -TaskName '{TASK}';"
    "Start-Sleep -Seconds 4;"
    "(Get-ScheduledTask -TaskName '{TASK}').State"
).replace("{TASK}", TASK_NAME).replace("{LEGACY}", LEGACY_TASK_NAME)


def write_bats():
    """bat 里全是 % 开头的变量（%~dp0 / %TASKSTATE%），用 % 格式化会把它们
    当格式符直接报错，所以统一用占位符 replace。"""
    ps_install = PS_INSTALL.replace("{EXE}", "%~dp0monitor.exe")

    install_body = (
        'cd /d "%~dp0"\n'
        "echo.\n"
        "echo   PC 状态监控 · 安装（免看门狗版）\n"
        "echo   ------------------------------\n"
        'if not exist "monitor.exe" (\n'
        "  echo   [错误] 当前目录找不到 monitor.exe\n"
        "  pause & exit /b 1\n"
        ")\n"
        "echo   [1/2] 注册计划任务（登录后自动运行 monitor.exe，无窗口）\n"
        "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "
        '"{PS}" > _taskstate.txt 2>&1\n'
        "set /p TASKSTATE=<_taskstate.txt\n"
        'if not "%TASKSTATE%"=="Running" (\n'
        "  echo   PowerShell 方式没成功，改用 schtasks 重试...\n"
        '  schtasks /create /tn "{TASK}" /tr "\'%~dp0monitor.exe\'" /sc onlogon /f >nul 2>&1\n'
        '  schtasks /run /tn "{TASK}" >nul 2>&1\n'
        ")\n"
        "echo   [2/2] 检查采集端\n"
        "timeout /t 6 /nobreak >nul\n"
        'if exist "monitor.log" (\n'
        "  echo   采集端日志最后几行：\n"
        "  powershell -NoProfile -Command \"Get-Content 'monitor.log' -Tail 4\"\n"
        ") else (\n"
        "  echo   [警告] 没有生成 monitor.log，采集端可能没起来\n"
        ")\n"
        "echo.\n"
        "echo   完成。现在插上开发板，几秒内屏幕应该离开 PC MONITOR。\n"
        "echo   不亮就看 monitor.log\n"
        "echo.\n"
        "pause\n"
    ).replace("{PS}", ps_install).replace("{TASK}", TASK_NAME)

    uninstall_body = (
        'cd /d "%~dp0"\n'
        "echo   卸载计划任务并停止采集...\n"
        "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "
        '"foreach($n in @(\'{TASK}\',\'{LEGACY}\')){Stop-ScheduledTask -TaskName $n '
        "-ErrorAction SilentlyContinue;Unregister-ScheduledTask -TaskName $n "
        "-Confirm:$false -ErrorAction SilentlyContinue};'ok'\" >nul 2>&1\n"
        'schtasks /delete /tn "{TASK}" /f >nul 2>&1\n'
        'schtasks /delete /tn "{LEGACY}" /f >nul 2>&1\n'
        "taskkill /f /im monitor.exe >nul 2>&1\n"
        "taskkill /f /im watcher.exe >nul 2>&1\n"
        "echo   已卸载。\n"
        "pause\n"
    ).replace("{TASK}", TASK_NAME).replace("{LEGACY}", LEGACY_TASK_NAME)

    pause_body = (
        'cd /d "%~dp0"\n'
        "echo   暂停采集：停任务 + 结束采集端，把 COM 口让出来...\n"
        'schtasks /change /tn "{TASK}" /disable >nul 2>&1\n'
        'schtasks /end /tn "{TASK}" >nul 2>&1\n'
        "taskkill /f /im monitor.exe >nul 2>&1\n"
        "echo   已暂停：采集端已停、COM 口已释放，登录自启任务也已禁用。\n"
        "echo   烧完固件记得双击「恢复采集.bat」\n"
        "pause\n"
    ).replace("{TASK}", TASK_NAME)

    resume_body = (
        'cd /d "%~dp0"\n'
        "echo   恢复采集...\n"
        'schtasks /query /tn "{TASK}" >nul 2>&1\n'
        "if errorlevel 1 (\n"
        "  echo   计划任务不存在，直接启动采集端...\n"
        '  start "" "%~dp0monitor.exe"\n'
        ") else (\n"
        '  schtasks /change /tn "{TASK}" /enable >nul 2>&1\n'
        '  schtasks /run /tn "{TASK}" >nul 2>&1\n'
        ")\n"
        "timeout /t 4 /nobreak >nul\n"
        "if exist monitor.log powershell -NoProfile -Command \"Get-Content 'monitor.log' -Tail 3\"\n"
        "pause\n"
    ).replace("{TASK}", TASK_NAME)

    flash_body = (
        'cd /d "%~dp0"\n'
        "echo.\n"
        "echo   ESP32 固件烧录\n"
        "echo   ------------------------------\n"
        'if not exist "flash.exe" (\n'
        "  echo   [错误] 当前目录找不到 flash.exe\n"
        "  pause & exit /b 1\n"
        ")\n"
        'if not exist "firmware\\firmware.bin" (\n'
        "  echo   [错误] firmware 目录里没有固件\n"
        "  pause & exit /b 1\n"
        ")\n"
        "echo   [1/3] 暂停采集，把 COM 口让出来\n"
        'schtasks /change /tn "{TASK}" /disable >nul 2>&1\n'
        'schtasks /end /tn "{TASK}" >nul 2>&1\n'
        "taskkill /f /im monitor.exe >nul 2>&1\n"
        "timeout /t 2 /nobreak >nul\n"
        "echo   [2/3] 烧录（请确认开发板已接好 USB）\n"
        "echo.\n"
        "flash.exe\n"
        "set RC=%ERRORLEVEL%\n"
        "echo.\n"
        "echo   [3/3] 恢复采集\n"
        'schtasks /change /tn "{TASK}" /enable >nul 2>&1\n'
        'schtasks /run /tn "{TASK}" >nul 2>&1\n'
        'if "%RC%"=="0" (\n'
        "  echo   烧录完成。板子已重启，几秒内屏幕离开 PC MONITOR。\n"
        ") else (\n"
        "  echo   烧录失败，错误码 %RC%。看上面 esptool 的输出。\n"
        "  echo   常见原因：串口被别的程序占了 / 线接触不良 / 波特率太高\n"
        ")\n"
        "echo.\n"
        "pause\n"
    ).replace("{TASK}", TASK_NAME)

    make_bat("安装.bat", install_body)
    make_bat("卸载.bat", uninstall_body)
    make_bat("烧录固件.bat", flash_body)
    make_bat("暂停采集.bat", pause_body)
    make_bat("恢复采集.bat", resume_body)


def write_readme():
    txt = """PC 状态监控 · 免 Python 便携版（免看门狗版）
=====================================

用法
  1. 把整个文件夹拷到目标电脑任意位置（别放需要管理员权限的目录，
     也别放 U 盘/网络盘里直接运行）
  2. 双击「安装.bat」——注册登录自启任务并立刻启动采集端
  3. 插上开发板，几秒内屏幕离开 PC MONITOR

装一次就够。之后每次开机，采集端会自动运行；插上板子它自己连、
自己推数据、拔了静默等、再插再连，不需要再管。
包里没有看门狗进程，也没有常驻轮询——采集端本身就是自连自重的。

运行环境要求（拿到别的电脑前先看这段）
  · 系统：Windows 8.1 / 10 / 11。Windows 7 跑不起来（内核依赖不支持）。
  · 位数：必须是 64 位 Windows。本包是 64 位程序，32 位系统跑不了。
  · USB 串口驱动：目标电脑必须能识别开发板上的 CH340 串口芯片。
    多数 Win10/11 会自动装；没装的话设备管理器里会出现「未知设备」，
    屏幕会一直停在 PC MONITOR。装一下 WCH 官方 CH341SER 驱动即可。
  · 杀毒软件：包里的 exe 由 PyInstaller 打包，常被杀软/Defender 误报，
    首次运行可能被拦或弹 SmartScreen 警告。加白名单 / 选「仍要运行」。
  · 网络：天气功能需要联网（自动按 IP 定位）。没网也能用，天气显示 NO DATA。

需要重烧固件时（固件已随包附带，不用装 PlatformIO、不用装 Python）
  双击「烧录固件.bat」
  它会自动：暂停采集让出 COM 口 → 烧录 → 恢复采集
  手动分步：暂停采集.bat → 烧 → 恢复采集.bat。不暂停的话采集端占着
  COM 口，烧录必然失败。

不再用了
  双击「卸载.bat」

-------------------------------------
文件说明
  monitor.exe    采集端：每 1 秒采集 CPU/内存/网络/GPU/磁盘，经 USB 推给小屏
                 登录自启、常驻运行、自动扫 CH340、断线自愈
  monitor.log    采集端日志：串口连上没、推了什么数据、崩了没
  flash.exe      烧录器：内含 esptool，自动扫串口，460800 波特率
  firmware\\      固件四个文件：bootloader / partitions / boot_app0 / firmware
  printers.json.example   3D 打印机配置模板（可选）
                 复制成 printers.json（同目录）填好即可：小屏第 4、5 页会显示
                 两台打印机的热端/热床温度与打印进度。
                 支持 Creality Moonraker（局域网，填 IP）与纵维立方 Anycubic Cloud
                 （填 XX-Token）。不填也没关系，其它页面照常，这两页显示「无数据」。

屏停在 PC MONITOR 怎么查
  1. 先看设备管理器有没有「未知设备 / USB-SERIAL CH340」——有黄色感叹号
     就是驱动没装，装 CH341SER 驱动。
  2. 再翻 monitor.log：
     - 没有 [串口] 已连接 → CH340 没被识别（驱动/线/接触问题），或被别的程序占了
     - 有 [串口] 已连接但屏幕不亮 → 固件问题，重烧固件
  3. 日志整个没有 → 任务没跑起来，重双击「安装.bat」

-------------------------------------
常见问题
  Q: 杀毒软件报毒 / SmartScreen 拦截？
     PyInstaller 打包的程序常被误报，代码就是本目录的脚本。加白名单即可。

  Q: 任务计划没注册成功？
     安装.bat 会先试 PowerShell，失败自动退回 schtasks。都失败的话手动执行：
     schtasks /create /tn PCMonitor /tr "'完整路径\\monitor.exe'" /sc onlogon /f

  Q: 想改采集频率 / 串口号？
     便携版改不了，需要用 Python 版（monitor.py），那台电脑得装 Python。

  Q: 烧录失败怎么办？
     先确认采集已暂停（暂停采集.bat），串口被占是最常见原因。
     线的问题也很多——有些 USB 线只能充电不能传数据。
     换 USB 2.0 口试试，个别 USB3.0 口/前置口对 CH340 不稳。

  Q: 想换回自己编译的固件？
     把新编译的 firmware.bin 覆盖 firmware\\firmware.bin 即可，
     其余三个文件（bootloader/partitions/boot_app0）一般不用动。

  Q: 任务管理器里 monitor.exe 有两个？
     正常，不是双开。单文件 exe 是「bootloader 父进程 + 真子进程」结构，
     杀的时候两个会一起没。只要日志里没有「已有实例在运行」，就没有重复启动。
"""
    with open(os.path.join(OUT_DIR, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(txt)


def main():
    say("== 打包免 Python 便携版 ==")

    pyi = subprocess.run([sys.executable, "-c", "import PyInstaller; print(PyInstaller.__version__)"],
                         capture_output=True, text=True)
    if pyi.returncode != 0:
        say("没装 PyInstaller，先执行：pip install pyinstaller")
        return
    say("PyInstaller %s" % pyi.stdout.strip())

    # ★ flash.exe 依赖 esptool：flash.py 里是 importlib 动态加载，静态分析扫不到，
    #   靠 --collect-submodules esptool 收集。若打包环境没装 esptool，打出来的
    #   flash.exe 一运行就 ModuleNotFoundError: No module named 'esptool'。
    #   （曾经因为打包用的 venv 缺 esptool，导致新 flash.exe 直接不可用。）
    es = subprocess.run([sys.executable, "-c", "import esptool; print(getattr(esptool, '__version__', 'ok'))"],
                        capture_output=True, text=True)
    if es.returncode != 0:
        say("没装 esptool，flash.exe 将不可用，先执行：pip install esptool")
        return
    say("esptool %s" % (es.stdout or "").strip())

    if os.path.isdir(BUILD_ROOT):
        shutil.rmtree(BUILD_ROOT, ignore_errors=True)
    os.makedirs(BUILD_ROOT, exist_ok=True)

    ok = True
    for script, name, mode, extra in TARGETS:
        if not build_one(script, name, mode, extra):
            ok = False
            break

    if not ok:
        say("打包失败")
        return

    built = os.path.join(BUILD_ROOT, "dist")
    stop_running()
    if os.path.isdir(OUT_DIR):
        shutil.rmtree(OUT_DIR, ignore_errors=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    for _, name, _, _ in TARGETS:
        src = os.path.join(built, name + ".exe")
        if not os.path.isfile(src):
            say("找不到产物 %s" % src)
            return
        dst = os.path.join(OUT_DIR, name + ".exe")
        shutil.copy2(src, dst)
        say("  %s.exe  %.1f MB" % (name, os.path.getsize(dst) / 1024 / 1024))

    say("  拷固件")
    if not copy_firmware():
        say("  固件不全，烧录功能不可用（其余功能不受影响）")

    # 打印机配置模板：用户复制成 printers.json 填 IP / token（真实文件不入库、也不随包）
    ex = os.path.join(HERE, "printers.json.example")
    if os.path.isfile(ex):
        shutil.copy2(ex, os.path.join(OUT_DIR, "printers.json.example"))
        say("  printers.json.example")
    else:
        say("  缺 pc/printers.json.example（打印机配置模板未随包）")

    # 本机真实配置（含内网 IP，不入库）：存在就随包带上，装好即用
    real = os.path.join(HERE, "printers.json")
    if os.path.isfile(real):
        shutil.copy2(real, os.path.join(OUT_DIR, "printers.json"))
        say("  printers.json（本机配置随包）")

    write_bats()
    write_readme()

    # 安装脚本里用的临时状态文件，别留在产物里
    tmp_state = os.path.join(OUT_DIR, "_taskstate.txt")
    if os.path.isfile(tmp_state):
        os.remove(tmp_state)

    restart_task()

    say("")
    say("产物目录：%s" % OUT_DIR)
    say("整个目录拷到目标电脑，双击「安装.bat」即可。")


if __name__ == "__main__":
    main()
