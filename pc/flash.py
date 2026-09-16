#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一键烧录 ESP32 固件。

为什么单独做一个
    便携版要给没装 Python 的电脑用，那边没有 PlatformIO、没有 esptool，
    固件改了就没法重烧。这个脚本连同 esptool 一起被打进 flash.exe，
    双击「烧录固件.bat」就能刷机，不需要任何环境。

用法
    python flash.py           自动扫描 CH340 串口后烧录
    python flash.py COM9      指定串口

烧录布局（ESP32 · Arduino 框架 · 4MB flash 的标准偏移）
    0x1000   bootloader.bin
    0x8000   partitions.bin
    0xe000   boot_app0.bin      OTA 数据区初始内容，漏了会卡在启动循环
    0x10000  firmware.bin       主程序

注意：烧录前必须让采集端让出 COM 口，否则串口被占，esptool 连不上。
      「烧录固件.bat」已经处理好（建 pause.flag + 结束 monitor.exe）。
"""

import os
import sys
import time
from datetime import datetime

try:
    import serial.tools.list_ports
except ImportError:
    sys.exit("缺少 pyserial，先执行：pip install pyserial")


def app_dir():
    """打包成 exe 后 __file__ 指向临时解压目录，必须用 sys.executable 定位。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


HERE = app_dir()
FW_DIR = os.path.join(HERE, "firmware")


def _fix_encoding():
    """让中文在「烧录固件.bat」里正常显示。

    bat 开头执行了 chcp 65001（控制台切成 UTF-8），而 Python 默认按 GBK 输出，
    两边不一致中文就是乱码。所以控制台代码页是 65001 时才把 stdout 切成 UTF-8；
    用户在普通 GBK 窗口里手动跑时保持系统默认，同样是正常的。
    """
    try:
        import ctypes
        if ctypes.windll.kernel32.GetConsoleOutputCP() != 65001:
            return
    except Exception:
        return
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# (偏移, 文件名)
IMAGES = (
    ("0x1000", "bootloader.bin"),
    ("0x8000", "partitions.bin"),
    ("0xe000", "boot_app0.bin"),
    ("0x10000", "firmware.bin"),
)

CH340_VIDS = (0x1A86,)
CH340_PIDS = (0x7523, 0x7522, 0x5523, 0x55D4)

BAUD = 460800       # CH340 上 921600 有时不稳，460800 是稳妥值
WAIT_DEVICE = 60    # 等设备出现的最长秒数


def find_ch340():
    """扫到 CH340 返回 COM 口名，没扫到返回 None。"""
    for p in serial.tools.list_ports.comports():
        if p.vid in CH340_VIDS and (p.pid in CH340_PIDS or p.pid is None):
            return p.device
        desc = "%s %s" % (p.description or "", p.manufacturer or "")
        if "CH340" in desc.upper() or "CH341" in desc.upper() or "USB-SERIAL" in desc.upper():
            return p.device
    return None


def wait_for_device(seconds):
    """刚插上 USB 时设备可能还没枚举完，边等边提示。"""
    deadline = time.time() + seconds
    waited = 0
    while time.time() < deadline:
        port = find_ch340()
        if port:
            if waited:
                print("  等了 %d 秒，设备出现在 %s" % (waited, port))
            return port
        time.sleep(2)
        waited += 2
        if waited % 10 == 0:
            print("  还没看到开发板（已等 %d 秒），检查 USB 线..." % waited)
    return None


def main():
    print("=" * 46)
    print("  ESP32 固件烧录  %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 46)

    missing = [f for _, f in IMAGES if not os.path.isfile(os.path.join(FW_DIR, f))]
    if missing:
        print("\n[错误] firmware 目录缺少文件：%s" % ", ".join(missing))
        print("       目录：%s" % FW_DIR)
        return 2
    print("固件目录：%s" % FW_DIR)

    port = sys.argv[1] if len(sys.argv) > 1 else None
    if port:
        print("指定串口：%s" % port)
    else:
        print("扫描 CH340 ...")
        port = wait_for_device(WAIT_DEVICE)

    if not port:
        print("\n[错误] 没找到开发板。")
        print("       1. USB 线插紧了吗（有些线只能充电不能传数据）")
        print("       2. 设备管理器里有没有 COM 口 / CH340 驱动装了吗")
        print("       3. 采集端是不是还占着串口（先双击「暂停采集.bat」）")
        return 3

    print("目标串口：%s  波特率：%d" % (port, BAUD))
    print("")

    # esptool 5.x 起用连字符写法（--flash-mode 而不是 --flash_mode），
    # 下划线写法还能用但刷一堆弃用警告，看着像出错。
    args = [
        "--chip", "esp32",
        "--port", port,
        "--baud", str(BAUD),
        "--before", "default-reset",
        "--after", "hard-reset",
        "write-flash", "-z",
        "--flash-mode", "dio",
        "--flash-freq", "40m",
        "--flash-size", "detect",
    ]
    for off, name in IMAGES:
        args += [off, os.path.join(FW_DIR, name)]

    import esptool

    try:
        # esptool 不同版本签名不一样：新版 main(argv)，旧版读 sys.argv
        try:
            esptool.main(args)
        except TypeError:
            sys.argv = ["esptool"] + args
            esptool.main()
        return 0
    except SystemExit as e:
        # esptool 用 sys.exit 报失败，退出码即错误码
        return int(e.code) if e.code else 0
    except Exception as e:
        print("\n[错误] 烧录异常：%s" % e)
        return 4


if __name__ == "__main__":
    _fix_encoding()
    rc = main()
    print("")
    if rc == 0:
        print("烧录完成。开发板会自动重启，几秒后屏幕离开 PC MONITOR。")
    else:
        print("烧录失败（错误码 %s）。" % rc)
        print("常见原因：串口被占用、波特率太高、线接触不良。")
    sys.exit(rc)
