#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""硬复位 ESP32 并抓启动串口输出，判定固件是否真的在跑。

用法:  python probe_boot.py COM6
预期:  正常固件启动会打印 "CFG ... mem ..." 一行。
       无输出 -> 板子停在 bootloader / 没运行 / 串口不通。
"""
import sys
import time

import serial


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM6"
    s = serial.Serial()
    s.port = port
    s.baudrate = 115200
    s.timeout = 0.2
    # 打开前先摆好电平，避免一开就误进下载模式
    s.dtr = False   # IO0 = 1 -> 正常启动
    s.rts = False   # EN  = 1 -> 不复位
    s.open()

    # 硬复位：拉低 EN 再放开，同时保持 IO0 高（正常 boot）
    s.setDTR(False)
    s.setRTS(True)
    time.sleep(0.15)
    s.setRTS(False)
    time.sleep(0.05)

    buf = bytearray()
    t0 = time.time()
    while time.time() - t0 < 4.0:
        n = s.in_waiting
        if n:
            buf += s.read(n)
        else:
            buf += s.read(64)
    s.close()

    text = buf.decode("utf-8", "replace")
    print("=== raw bytes:", len(buf), "===")
    print(text[-4000:] if text else "(no serial output)")

    low = text
    if "CFG" in low:
        print(">>> VERDICT: firmware RUNNING (found CFG boot line)")
    elif text.strip():
        print(">>> VERDICT: got output but no CFG - check above (boot ROM / crash?)")
    else:
        print(">>> VERDICT: SILENT - board not running app (stuck in bootloader?)")


if __name__ == "__main__":
    main()
