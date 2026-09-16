#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ESP32 端到端自检：硬复位抓启动跟踪 -> 注入数据帧 -> 读心跳里的收帧计数。

判定依据（固件已带 [BOOT]/[HB] 打印）：
  [BOOT] render done            -> setup() 跑完，应用活着
  [HB] rx=N (N 增长)            -> 串口接收 + JSON 解析链路通
  [HB] rx=0 且 boot 完成        -> 收到帧但没解析成功
  boot 跟踪中途断掉             -> 卡死在那一行对应的步骤
"""
import json
import sys
import time

import serial


def frame(i):
    d = {
        "c": 7, "m": 41, "mf": 6.6, "t": -999, "g": 12, "gt": 45,
        "u": 0.3, "d": 1.2, "dk": 62, "df": 118,
        "tm": "13:%02d" % (i % 60), "dt": "09-11", "up": "3h20m",
        "yr": 2026, "mo": 9, "dy": 11, "ss": i % 60,
        "do": 0, "ds": 100,   # 与 clock_tune.json 默认一致，避免注帧把数字拉伸改掉
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
    buf = bytearray()

    def drain(sec):
        t0 = time.time()
        while time.time() - t0 < sec:
            n = s.in_waiting
            if n:
                buf.extend(s.read(n))
            else:
                buf.extend(s.read(32))

    # 1) 硬复位，抓启动跟踪
    s.setDTR(False)
    s.setRTS(True)
    time.sleep(0.15)
    s.setRTS(False)
    drain(3.5)

    print("=== phase1: boot trace ===")
    print(bytes(buf).decode("utf-8", "replace").strip() or "(nothing)")

    # 2) 注入数据帧，看心跳 rx 是否增长
    mark = len(buf)
    for i in range(8):
        s.write(frame(i).encode("ascii"))
        drain(1.0)
    s.close()

    tail = bytes(buf[mark:]).decode("utf-8", "replace")
    print("=== phase2: while sending (heartbeats) ===")
    print(tail.strip() or "(nothing)")

    allt = bytes(buf).decode("utf-8", "replace")
    print("=== VERDICT ===")
    if "[BOOT] render done" not in allt:
        print("!!! setup() 未跑完 -> 板子在启动阶段卡住/崩溃（看上面停在哪一行）")
    else:
        print("OK: setup() 跑完，应用在运行")
    hbs = [l for l in tail.splitlines() if "[HB]" in l]
    if hbs:
        try:
            rx = int(hbs[-1].split("rx=")[1].split()[0])
            print("OK: 收到帧并解析成功，rx=%d" % rx if rx > 0 else
                  "!!! rx=0 -> 串口有数据但 JSON 没解析成功")
            if rx == 0:
                print("!!! rx=0 -> 收到帧但解析失败/没收到")
        except Exception as e:
            print("heartbeat parse err:", e)
    else:
        print("!!! 没有心跳输出 -> loop() 没在跑")


if __name__ == "__main__":
    main()
