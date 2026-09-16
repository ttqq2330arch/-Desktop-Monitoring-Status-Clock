#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把采集端和看门狗打包成免 Python 的 exe，给没装 Python 的电脑用。

产物
    dist/pc-monitor-portable/
        monitor.exe     采集端（无窗口）
        watcher.exe     USB 看门狗（无窗口）
        安装.bat        注册计划任务并立即启动
        卸载.bat        删除计划任务
        暂停采集.bat    建 pause.flag，看门狗让路（烧录固件前用）
        恢复采集.bat    删 pause.flag
        使用说明.txt

为什么要这套东西
    另一台电脑没装 Python 时，脚本版跑不起来，也装不了依赖。
    PyInstaller 把解释器 + 依赖 + 脚本打进单个 exe，拷过去就能用。

两个必须注意的点
    1. 用 --windowed：常驻程序不能有控制台窗口，否则桌面上一直挂着黑框。
       windowed 模式下 sys.stdout 为 None，脚本已内置兜底把输出写进日志文件。
    2. 打包后 __file__ 指向临时解压目录（_MEIPASS），日志会写进去然后随进程
       退出丢失。所以 monitor.py / watcher.py 里统一用 app_dir() 定位目录。

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
#   常驻的 monitor/watcher 必须 windowed，否则桌面一直挂黑框；
#   flash 反过来要 console——烧录时得让用户在窗口里看到进度和报错。
TARGETS = (
    ("monitor.py", "monitor", "windowed", []),
    ("watcher.py", "watcher", "windowed", []),
    ("flash.py", "flash", "console",
     # esptool 用 importlib 动态加载各芯片 target，静态分析扫不到，必须整个收进来
     ["--collect-submodules", "esptool", "--collect-data", "esptool"]),
)

TASK_NAME = "PCMonitorWatch"


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
    """打包杀掉了实例，装完顺手把看门狗拉回来。起不来也不拦，提示手动恢复。"""
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "Start-ScheduledTask -TaskName '%s' -ErrorAction Stop;"
             "(Get-ScheduledTask -TaskName '%s').State" % (TASK_NAME, TASK_NAME)],
            capture_output=True, text=True, timeout=60)
        out = (r.stdout or "").strip()
        state = out.splitlines()[-1] if out else ""
        if state:
            say("  看门狗已重新拉起：%s" % state)
            return
    except Exception:
        pass
    say("  看门狗没能自动拉起，双击「安装.bat」恢复")


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
    "foreach($n in @('PCMonitor','{TASK}')){{"
    "Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue;"
    "Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue}};"
    "$a=New-ScheduledTaskAction -Execute '{EXE}';"
    "$t=New-ScheduledTaskTrigger -AtLogOn;"
    "$s=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries"
    " -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)"
    " -ExecutionTimeLimit (New-TimeSpan -Hours 0);"
    "Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s -Force | Out-Null;"
    "Start-ScheduledTask -TaskName '{TASK}';"
    "Start-Sleep -Seconds 4;"
    "(Get-ScheduledTask -TaskName '{TASK}').State"
).replace("{TASK}", TASK_NAME)


def write_bats():
    """bat 里全是 % 开头的变量（%~dp0 / %TASKSTATE%），用 % 格式化会把它们
    当格式符直接报错，所以统一用占位符 replace。"""
    ps_install = PS_INSTALL.replace("{EXE}", os.path.join(OUT_DIR, "watcher.exe"))

    install_body = (
        'cd /d "%~dp0"\n'
        "echo.\n"
        "echo   PC 状态监控 · 安装\n"
        "echo   ------------------------------\n"
        'if not exist "watcher.exe" (\n'
        "  echo   [错误] 当前目录找不到 watcher.exe\n"
        "  pause & exit /b 1\n"
        ")\n"
        "echo   [1/2] 注册计划任务（登录后自动运行，无窗口）\n"
        "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "
        '"{PS}" > _taskstate.txt 2>&1\n'
        "set /p TASKSTATE=<_taskstate.txt\n"
        'if not "%TASKSTATE%"=="Running" (\n'
        "  echo   PowerShell 方式没成功，改用 schtasks 重试...\n"
        '  schtasks /create /tn "{TASK}" /tr "\'%~dp0watcher.exe\'" /sc onlogon /f >nul 2>&1\n'
        '  schtasks /run /tn "{TASK}" >nul 2>&1\n'
        ")\n"
        "echo   [2/2] 检查看门狗\n"
        "timeout /t 6 /nobreak >nul\n"
        'if exist "watcher.log" (\n'
        "  echo   看门狗日志最后几行：\n"
        "  powershell -NoProfile -Command \"Get-Content 'watcher.log' -Tail 4\"\n"
        ") else (\n"
        "  echo   [警告] 没有生成 watcher.log，看门狗可能没起来\n"
        ")\n"
        "echo.\n"
        "echo   完成。现在插上开发板，几秒内屏幕应该离开 PC MONITOR。\n"
        "echo   不亮就看 watcher.log / monitor.log\n"
        "echo.\n"
        "pause\n"
    ).replace("{PS}", ps_install).replace("{TASK}", TASK_NAME)

    uninstall_body = (
        'cd /d "%~dp0"\n'
        "echo   卸载计划任务并停止采集...\n"
        "powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "
        '"foreach($n in @(\'{TASK}\',\'PCMonitor\')){Stop-ScheduledTask -TaskName $n '
        "-ErrorAction SilentlyContinue;Unregister-ScheduledTask -TaskName $n "
        "-Confirm:$false -ErrorAction SilentlyContinue};'ok'\" >nul 2>&1\n"
        'schtasks /delete /tn "{TASK}" /f >nul 2>&1\n'
        "taskkill /f /im monitor.exe >nul 2>&1\n"
        "taskkill /f /im watcher.exe >nul 2>&1\n"
        "echo   已卸载。\n"
        "pause\n"
    ).replace("{TASK}", TASK_NAME)

    pause_body = (
        'cd /d "%~dp0"\n'
        "echo burn> pause.flag\n"
        "taskkill /f /im monitor.exe >nul 2>&1\n"
        "echo   已暂停：看门狗不会再拉起采集，COM 口已释放。\n"
        "echo   烧完固件记得双击「恢复采集.bat」\n"
        "pause\n"
    )

    resume_body = (
        'cd /d "%~dp0"\n'
        "if exist pause.flag del pause.flag\n"
        "echo   已恢复：几秒内看门狗会重新拉起采集。\n"
        "timeout /t 4 /nobreak >nul\n"
        "if exist watcher.log powershell -NoProfile -Command \"Get-Content 'watcher.log' -Tail 3\"\n"
        "pause\n"
    )

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
        "echo burn> pause.flag\n"
        "taskkill /f /im monitor.exe >nul 2>&1\n"
        "timeout /t 2 /nobreak >nul\n"
        "echo   [2/3] 烧录（请确认开发板已接好 USB）\n"
        "echo.\n"
        "flash.exe\n"
        "set RC=%ERRORLEVEL%\n"
        "echo.\n"
        "echo   [3/3] 恢复采集\n"
        "if exist pause.flag del pause.flag\n"
        'if "%RC%"=="0" (\n'
        "  echo   烧录完成。板子已重启，几秒内屏幕离开 PC MONITOR。\n"
        ") else (\n"
        "  echo   烧录失败，错误码 %RC%。看上面 esptool 的输出。\n"
        "  echo   常见原因：串口被别的程序占了 / 线接触不良 / 波特率太高\n"
        ")\n"
        "echo.\n"
        "pause\n"
    )

    make_bat("安装.bat", install_body)
    make_bat("卸载.bat", uninstall_body)
    make_bat("烧录固件.bat", flash_body)
    make_bat("暂停采集.bat", pause_body)
    make_bat("恢复采集.bat", resume_body)


def write_readme():
    txt = """PC 状态监控 · 免 Python 便携版
=====================================

用法
  1. 把整个文件夹拷到目标电脑任意位置（别放需要管理员权限的目录）
  2. 双击「安装.bat」
  3. 插上开发板，几秒内屏幕离开 PC MONITOR

需要重烧固件时（固件已随包附带，不用装 PlatformIO、不用装 Python）
  双击「烧录固件.bat」
  它会自动：暂停采集让出 COM 口 → 烧录 → 恢复采集
  手动分步的话：暂停采集.bat → 烧 → 恢复采集.bat。不暂停的话采集端
  占着 COM 口，烧录必然失败；只杀进程也没用，看门狗 3 秒内就拉回来了。

不再用了
  双击「卸载.bat」

-------------------------------------
文件说明
  monitor.exe    采集端：每 1 秒采集 CPU/内存/网络/GPU/磁盘，经 USB 推给小屏
  watcher.exe    看门狗：每 3 秒扫串口，见到 CH340 就把采集端拉起来
                 拔了再插、开机时已插着、采集端崩了，三种情况都会自愈
  watcher.log    看门狗日志：硬件在不在、有没有拉起、是不是被暂停了
  monitor.log    采集端日志：串口连上没、推了什么数据、崩了没
  flash.exe      烧录器：内含 esptool，自动扫串口，460800 波特率
  firmware\\      固件四个文件：bootloader / partitions / boot_app0 / firmware

屏停在 PC MONITOR 怎么查
  1. 先翻 watcher.log：
     - 没有内容             → 看门狗没跑，重双击「安装.bat」
     - CH340=未连接         → 线没插好或驱动没装
     - 暂停=是              → pause.flag 忘了删，双击「恢复采集.bat」
     - CH340=COMx 采集=运行中 → 看门狗没问题，去翻 monitor.log
  2. monitor.log 里没有 [串口] 已连接 → COM 口被别的程序占了

-------------------------------------
常见问题
  Q: 杀毒软件报毒？
     PyInstaller 打包的程序常被误报。加白名单即可，代码就是本目录下的脚本。

  Q: 想改采集频率 / 串口号？
     便携版改不了，需要用 Python 版（monitor.py），那台电脑得装 Python。

  Q: 烧录失败怎么办？
     先确认采集已暂停（暂停采集.bat），串口被占是最常见原因。
     还不行就把波特率调低：在 flash.py 里把 BAUD 改成 115200 后重新打包。
     线的问题也很多——有些 USB 线只能充电不能传数据。

  Q: 想换回自己编译的固件？
     把新编译的 firmware.bin 覆盖 firmware\\firmware.bin 即可，
     其余三个文件（bootloader/partitions/boot_app0）一般不用动。

  Q: 任务计划没注册成功？
     安装.bat 会先试 PowerShell，失败自动退回 schtasks。两条都失败的话，
     手动执行：schtasks /create /tn PCMonitorWatch /tr "'完整路径\\watcher.exe'" /sc onlogon /f

  Q: 任务管理器里 watcher.exe / monitor.exe 各有两个？
     正常，不是双开。单文件 exe 是「bootloader 父进程 + 真子进程」结构，
     杀的时候两个会一起没。只要日志里没有「已有实例在跑」，就没有重复启动。
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
