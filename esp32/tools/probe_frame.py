#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""向 ESP32 注入一帧 monitor 同格式 JSON，同时监听串口。

判定:
  - 收到 "ets Jul" / "rst:" 等 ROM 启动日志 -> 设备收到帧后崩溃重启(致命)
  - 全程无输出                              -> 设备稳定接收(正常，正式固件不打印)
"""
import json
import sys
import time

import serial


def frame(i):
    # 与 monitor.py collect() 输出字段一致（含中文城市 + 完整天气）
    d = {
        "c": 7, "m": 41, "mf": 6.6, "t": -999, "g": 12, "gt": 45,
        "u": 0.3, "d": 1.2, "dk": 62, "df": 118,
        "tm": "13:%02d" % (i % 60), "dt": "09-11", "up": "3h20m",
        "yr": 2026, "mo": 9, "dy": 11, "ss": i % 60,
        "do": 0, "ds": 190,
        "wt": 19.1, "wc": 3, "wf": 19.4, "wh": 63, "ww": 3.0,
        "whi": 21.0, "wlo": 16.0,
        "wct": "\u897f\u5b89", "wce": "Xi'an",
    }
    return json.dumps(d, separators=(",", ":")) + "\n"


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM6"
    s = serial.Serial()
    s.port = port
    s.baudrate = 115200
    s.timeout = 0.1
    s.dtr = False
    s.rts = False
    s.open()

    got = bytearray()

    def drain(sec):
        t0 = time.time()
        while time.time() - t0 < sec:
            n = s.in_waiting
            if n:
                got.extend(s.read(n))
            else:
                got.extend(s.read(32))

    drain(1.0)                       # 基线
    base_n = len(got)
    print("baseline bytes:", base_n)

    for i in range(12):
        s.write(frame(i).encode("ascii"))
        drain(0.85)
    s.close()

    new = bytes(got[base_n:])
    print("=== bytes received while sending:", len(new), "===")
    txt = new.decode("utf-8", "replace")
    print(txt[-3000:] if txt.strip() else "(silent - no output)")

    if "ets Jul" in txt or "rst:" in txt or "Guru" in txt or "abort" in txt.lower():
        print(">>> VERDICT: DEVICE CRASHED/REBOOTED on receiving frames")
    else:
        print(">>> VERDICT: device accepted frames and stayed silent (OK)")


if __name__ == "__main__":
    main()
