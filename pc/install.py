#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键安装：在任何一台 Windows 电脑上把 PC 监控跑起来。

做四件事
    1. 找到可用的解释器（优先无窗口的 pythonw）
    2. 补齐依赖 psutil / pyserial（GPU 用的 nvidia-ml-py 是可选，装不上不拦）
    3. 注册计划任务 PCMonitorWatch，登录时拉起 USB 看门狗
    4. 立即启动并验证看门狗真的起来了

看门狗跑起来之后，插上 ESP32 就会自动开始采集，不用管开机时机。

用法
    python install.py              安装并启动
    python install.py --check      只体检，不改任何东西
    python install.py --uninstall  卸载计划任务
"""

import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHER = os.path.join(HERE, "watcher.py")
MONITOR = os.path.join(HERE, "monitor.py")
TASK_NAME = "PCMonitorWatch"

REQUIRED = (("psutil", "psutil"), ("serial", "pyserial"))


def say(msg=""):
    print(msg, flush=True)


def _fix_stdout_encoding():
    """被重定向/管道时用 UTF-8，交互终端保持系统默认（否则中文变乱码）。

    直接在控制台跑时 Windows 用 GBK，强改 UTF-8 会乱码；
    但输出被 PowerShell 管道接走时，GBK 字节又会被当 UTF-8 解而报错。
    所以只在非 tty 时切。
    """
    try:
        if hasattr(sys.stdout, "reconfigure") and not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def interpreters():
    """返回 (python.exe, pythonw.exe)。

    pythonw 用来跑常驻脚本（无窗口），python 用来跑 pip（要看到输出）。
    不能写死路径——换台电脑用户名和安装位置都变了。
    """
    exe = sys.executable
    d = os.path.dirname(exe)
    b = os.path.basename(exe).lower()

    if b.startswith("pythonw"):
        pyw, py = exe, os.path.join(d, "python.exe")
    else:
        py, pyw = exe, os.path.join(d, "pythonw.exe")

    if not os.path.isfile(pyw):
        found = shutil.which("pythonw")
        pyw = found or py
    if not os.path.isfile(py):
        found = shutil.which("python")
        py = found or pyw
    return py, pyw


def missing_deps(py):
    miss = []
    for mod, pkg in REQUIRED:
        r = subprocess.run([py, "-c", "import %s" % mod],
                           capture_output=True, text=True)
        if r.returncode != 0:
            miss.append(pkg)
    return miss


def install_deps(py, miss):
    say("  安装依赖：%s" % " ".join(miss))
    r = subprocess.run([py, "-m", "pip", "install", *miss],
                       capture_output=True, text=True)
    if r.returncode != 0:
        # 没有写权限时退回用户级安装
        r2 = subprocess.run([py, "-m", "pip", "install", "--user", *miss],
                            capture_output=True, text=True)
        if r2.returncode != 0:
            say("  安装失败，请手动执行：%s -m pip install %s" % (py, " ".join(miss)))
            say("  " + (r2.stderr or r.stderr or "").strip()[:500])
            return False
    say("  依赖已就绪")
    return True


def ps(cmd):
    r = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", cmd],
        capture_output=True, text=True, timeout=120,
    )
    return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()


def register_task(py, pyw):
    # 路径用单引号包住，PowerShell 单引号内是字面量，中文和空格都不会出问题
    cmd = r"""
$ErrorActionPreference = 'Stop'
$pyw = '{PYW}'
$scr = '{SCR}'
foreach ($old in @('PCMonitor', 'PCMonitorWatch')) {{
    Stop-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $old -Confirm:$false -ErrorAction SilentlyContinue
}}
$a = New-ScheduledTaskAction -Execute $pyw -Argument ('"' + $scr + '"')
$t = New-ScheduledTaskTrigger -AtLogOn
$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Hours 0)
Register-ScheduledTask -TaskName '{TASK}' -Action $a -Trigger $t -Settings $s -Force | Out-Null
Start-ScheduledTask -TaskName '{TASK}'
Start-Sleep -Seconds 5
(Get-ScheduledTask -TaskName '{TASK}').State
""".replace("{PYW}", pyw).replace("{SCR}", WATCHER).replace("{TASK}", TASK_NAME)

    rc, out, err = ps(cmd)
    if rc != 0:
        say("  注册失败：%s" % (err[:400] or out[:400]))
        return None
    return out.strip().splitlines()[-1] if out.strip() else "Unknown"


def uninstall():
    cmd = r"""
foreach ($n in @('PCMonitorWatch', 'PCMonitor')) {
    Stop-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $n -Confirm:$false -ErrorAction SilentlyContinue
}
'removed'
"""
    rc, out, err = ps(cmd)
    say("已卸载计划任务" if rc == 0 else "卸载失败：%s" % (err[:300] or out[:300]))


def check():
    py, pyw = interpreters()
    say("环境体检")
    say("  python.exe : %s %s" % (py, "存在" if os.path.isfile(py) else "缺失"))
    say("  pythonw.exe: %s %s" % (pyw, "存在" if os.path.isfile(pyw) else "缺失"))
    say("  watcher.py : %s" % ("存在" if os.path.isfile(WATCHER) else "缺失"))
    say("  monitor.py : %s" % ("存在" if os.path.isfile(MONITOR) else "缺失"))

    miss = missing_deps(py)
    say("  依赖       : %s" % ("全部就绪" if not miss else "缺少 %s" % ", ".join(miss)))

    rc, out, err = ps("(Get-ScheduledTask -TaskName '%s' -ErrorAction SilentlyContinue).State" % TASK_NAME)
    state = out.strip() if rc == 0 and out.strip() else "未安装"
    say("  计划任务   : %s" % state)

    import serial.tools.list_ports
    ports = list(serial.tools.list_ports.comports())
    ch340 = [p.device for p in ports if (p.vid == 0x1A86) or "CH340" in (p.description or "").upper()]
    say("  CH340      : %s" % (", ".join(ch340) if ch340 else "未检测到（开发板没插？）"))
    return not miss and os.path.isfile(pyw)


def main():
    if "--uninstall" in sys.argv:
        uninstall()
        return

    if "--check" in sys.argv:
        check()
        return

    say("== PC 监控 安装 ==")
    py, pyw = interpreters()
    if not os.path.isfile(pyw):
        say("找不到 pythonw.exe，请先安装 Python：https://www.python.org/downloads/")
        return
    if not os.path.isfile(WATCHER):
        say("找不到 watcher.py，安装脚本必须和它放在同一目录")
        return

    say("[1/4] 解释器：%s" % pyw)

    say("[2/4] 检查依赖")
    miss = missing_deps(py)
    if miss:
        if not install_deps(py, miss):
            return
    else:
        say("  依赖已就绪")

    say("[3/4] 注册计划任务 %s" % TASK_NAME)
    state = register_task(py, pyw)
    if state is None:
        return
    say("  任务状态：%s" % state)

    say("[4/4] 验证")
    if state == "Running":
        say("  看门狗已运行。插上 ESP32，几秒内屏幕就会离开 PC MONITOR。")
    else:
        say("  任务状态异常（%s），看 watcher.log" % state)

    say("")
    say("完成。日志：watcher.log / monitor.log")


if __name__ == "__main__":
    _fix_stdout_encoding()
    main()
