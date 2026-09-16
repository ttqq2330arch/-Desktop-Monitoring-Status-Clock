#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
USB 看门狗：ESP32 插上 USB 就自动拉起采集脚本。

为什么要有它
    登录时自启的时机不可控——Windows 登录瞬间 CH340 常常还没枚举完，
    脚本起来了也白起。看门狗不看时机看硬件：只要 CH340 在，采集就得在。

设计取舍
- **轮询（3 秒）而不是 WMI 事件订阅**：WMI 订阅依赖 WMI 服务状态和权限，
  在这台机器上不可靠；轮询延迟几秒完全可接受，且不会漏事件。
- **只负责拉起，不负责杀死**：monitor.py 自己会等 USB 回来并重连，
  看门狗不插手，避免拔插抖动时误杀刚连上的实例。
- **pause.flag 暂停机制**：烧录固件前创建这个文件，看门狗就不再拉起，
  否则刚停掉的脚本会被立刻拉回来抢走 COM 口。
- **用端口锁判断采集在不在跑**，不扫进程——psutil 扫进程在 pythonw 下
  会把启动中的自己误判成目标，之前踩过。

用法
    python watcher.py           前台运行（调试用，有窗口）
    pythonw watcher.py          后台运行（计划任务用的方式）
"""

import os
import socket
import subprocess
import sys
import time
from datetime import datetime

def app_dir():
    """脚本所在目录。

    打包成 exe 后 __file__ 指向临时解压目录（_MEIPASS），直接用它会把日志
    和 pause.flag 放到临时目录去，重启一次就全丢了。frozen 时改用
    sys.executable 定位，保证日志落在 exe 旁边。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


HERE = app_dir()
LOG = os.path.join(HERE, "watcher.log")
PAUSE_FLAG = os.path.join(HERE, "pause.flag")

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    # 打包版：采集端是同目录的 monitor.exe，本身自带运行时，不需要解释器
    MONITOR = os.path.join(HERE, "monitor.exe")
else:
    MONITOR = os.path.join(HERE, "monitor.py")


def find_pythonw():
    """定位用来拉起采集脚本的解释器，优先无窗口的 pythonw。

    不能写死路径——换台电脑用户名/安装位置都变了。看门狗自己通常就是
    被 pythonw 拉起来的，那 sys.executable 直接可用；被 python.exe 跑时
    退而求其次找同目录的 pythonw.exe。
    """
    exe = sys.executable
    if os.path.basename(exe).lower().startswith("pythonw"):
        return exe
    cand = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.isfile(cand):
        return cand
    return exe


PYW = None if FROZEN else find_pythonw()

WATCH_LOCK_PORT = 47652      # 看门狗自己的单实例锁
MONITOR_LOCK_PORT = 47651    # 采集脚本的单实例锁（与 monitor.py 保持一致）
POLL = 3                     # 轮询间隔（秒）

CH340_VIDS = (0x1A86,)
CH340_PIDS = (0x7523, 0x7522, 0x5523, 0x55D4)

# 无窗口 + 脱离父进程控制台
CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008


def log(msg):
    """只写文件，不 print。

    pythonw 下 stdout 已被兜底重定向到同一个 watcher.log，
    再 print 一次会让每条日志写两遍。
    """
    line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def acquire_lock(port):
    """抢单实例锁，抢到返回持有中的 socket，失败返回 None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return s
    except OSError:
        try:
            s.close()
        except Exception:
            pass
        return None


def port_held(port):
    """端口被占 = 对应进程在跑。比扫进程可靠。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        try:
            s.close()
        except Exception:
            pass


def ch340_present():
    """扫到 CH340 返回 COM 口名（如 COM6），没扫到返回 None。"""
    try:
        import serial.tools.list_ports
        for p in serial.tools.list_ports.comports():
            if p.vid in CH340_VIDS and (p.pid in CH340_PIDS or p.pid is None):
                return p.device
            desc = "%s %s" % (p.description or "", p.manufacturer or "")
            if "CH340" in desc.upper() or "CH341" in desc.upper() or "USB-SERIAL" in desc.upper():
                return p.device
    except Exception as e:
        log("扫描串口异常: %s" % e)
    return None


def start_monitor():
    if not os.path.isfile(MONITOR):
        log("找不到采集端：%s" % MONITOR)
        return None
    try:
        # 打包版 monitor.exe 自带运行时，直接执行；脚本版需要解释器
        argv = [MONITOR] if FROZEN else [PYW, MONITOR]
        p = subprocess.Popen(
            argv,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            close_fds=True,
        )
        return p.pid
    except Exception as e:
        log("拉起采集端失败: %s" % e)
        return None


def main():
    lock = acquire_lock(WATCH_LOCK_PORT)
    if lock is None:
        log("已有看门狗实例在跑，本次退出")
        return

    log("看门狗启动，轮询间隔 %s 秒，脚本 %s" % (POLL, MONITOR))
    last = None

    while True:
        try:
            port = ch340_present()
            paused = os.path.exists(PAUSE_FLAG)
            running = port_held(MONITOR_LOCK_PORT)

            # 只在状态变化时记日志，否则 3 秒一条会刷爆
            state = (bool(port), paused, running)
            if state != last:
                log("CH340=%s 暂停=%s 采集=%s" % (
                    port or "未连接", "是" if paused else "否",
                    "运行中" if running else "未运行"))
                last = state

            if port and not paused and not running:
                log("检测到 %s，拉起采集脚本" % port)
                pid = start_monitor()
                if pid:
                    log("已拉起，pid=%s" % pid)
                time.sleep(2)  # 给它时间抢锁，避免同一轮重复拉起
        except KeyboardInterrupt:
            log("收到中断，退出")
            break
        except Exception as e:
            log("主循环异常: %s" % e)

        time.sleep(POLL)


if __name__ == "__main__":
    # pythonw 下 stdout 为 None，所有 print 会崩，先兜底
    if getattr(sys, "stdout", None) is None:
        try:
            sys.stdout = open(LOG, "a", encoding="utf-8", buffering=1)
            sys.stderr = sys.stdout
        except Exception:
            pass
    try:
        main()
    except Exception:
        import traceback
        log("崩溃:\n" + traceback.format_exc())
