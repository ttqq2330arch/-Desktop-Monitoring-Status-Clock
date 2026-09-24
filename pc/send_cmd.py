#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""串口配网小工具：给 ESP32 监控屏发 WiFi 凭据（WIFI:ssid,pass 命令）。

用法（两种）：
  send_cmd.exe                      交互式：自动选 CH340 → 输 WiFi 名/密码
  send_cmd.exe --ssid 名 --pass 密码 命令行直配
  send_cmd.exe --port COM5          手动指定串口

流程：找串口 → 打开 115200 → 发 WIFI:... → 等 [WEB] ip= 行（最长 30 秒）
→ 把手机访问地址大字打印出来（安卓不认 pcscreen.local，必须用 IP）。

注意：采集端 monitor.exe 会占串口，运行前须先暂停采集（配WiFi.bat 已编排）。
"""
import argparse
import re
import sys
import time

import serial
import serial.tools.list_ports

IP_RE = re.compile(r"ip=(\d{1,3}(?:\.\d{1,3}){3})")


def list_all_ports():
    return [(p.device, p.description or "") for p in serial.tools.list_ports.comports()]


def find_ch340():
    """优先自动选 CH340/CH341；找不到时列出全部串口让用户挑。

    Win11 有时把 CH340 显示成「USB 串行设备」而不带 CH340 字样，
    所以"找不到就让人挑"是必须的兜底，不能直接报错退出。
    """
    hits = [p for p in list_all_ports()
            if "CH340" in p[1] or "CH341" in p[1]]
    if len(hits) == 1:
        return hits[0][0]
    allp = list_all_ports()
    if not allp:
        return None
    if hits:
        print(f"自动选中串口: {hits[0][0]}  ({hits[0][1]})")
        return hits[0][0]
    print("没有一眼能认出的 CH340 串口（Win11 有时显示为「USB 串行设备」）。")
    print("可用串口：")
    for i, (dev, desc) in enumerate(allp):
        print(f"  [{i}] {dev}  {desc}")
    while True:
        try:
            k = input(f"屏幕盒子插在哪个口? [0-{len(allp)-1}] ").strip()
            return allp[int(k)][0]
        except (ValueError, IndexError):
            print("输入无效，重试")


def talk(port, baud=115200):
    print(f"\n打开 {port} @ {baud} ...")
    with serial.Serial(port, baud, timeout=0.5) as s:
        s.reset_input_buffer()
        s.write(b"WIFI:%s,%s\n" % (ARGS.ssid.encode(), ARGS.pass_.encode()))
        print("已发送 WiFi 凭据，等待设备连接（最长 30 秒）...\n")

        t0 = time.time()
        buf = b""
        ip = None
        while time.time() - t0 < 30:
            chunk = s.read(256)
            if chunk:
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    txt = line.decode("utf-8", "replace").strip()
                    if txt:
                        print("  设备>", txt[:120])
                    m = IP_RE.search(txt)
                    if m and "127." not in m.group(1):
                        ip = m.group(1)
            if ip:
                break

        if ip:
            print("\n" + "=" * 46)
            print("  配网成功！")
            print(f"  手机连同一个 WiFi，浏览器打开：  http://{ip}")
            print("  （苹果设备也可以用 http://pcscreen.local）")
            print("=" * 46)
            print("  建议在路由器里给这台屏幕绑定固定 IP，以后地址不会变。")
        else:
            print("\n警告：30 秒内没等到联网成功的标志。常见原因：")
            print("  · WiFi 名称或密码输错 → 重新运行再试一次")
            print("  · 这个 WiFi 是 5G → 换 2.4G 的（本设备不支持 5G）")
            print("  · 已发进设备，可能稍后才连上 → 看屏幕/稍后再打开手机试试")


def main():
    global ARGS
    ap = argparse.ArgumentParser(description="ESP32 监控屏 WiFi 配网工具")
    ap.add_argument("--ssid")
    ap.add_argument("--pass", dest="pass_")
    ap.add_argument("--port", help="手动指定串口，如 COM5")
    ARGS = ap.parse_args()

    print("=" * 46)
    print("  ESP32 监控屏 · WiFi 配网工具")
    print("=" * 46)

    port = ARGS.port or find_ch340()
    if not port:
        print("\n[错误] 电脑上没有任何串口。请检查：")
        print("  1) 监控屏的 USB 线已插到这台电脑（要用数据线，不是充电线）")
        print("  2) 驱动已装：双击 drivers\\CH340\\install_driver.bat")
        sys.exit(1)

    if not ARGS.ssid:
        ARGS.ssid = input("\n输入 WiFi 名称（2.4G）：").strip()
        ARGS.pass_ = input("输入 WiFi 密码：").strip()
    if not ARGS.ssid or ARGS.pass_ is None:
        print("[错误] WiFi 名称和密码不能为空")
        sys.exit(1)
    if len(ARGS.ssid) > 32 or len(ARGS.pass_) > 64:
        print("[错误] 名称超 32 字符或密码超 64 字符（设备限制）")
        sys.exit(1)

    try:
        talk(port)
    except serial.SerialException as e:
        print(f"\n[错误] 串口打不开：{e}")
        print("多半是被别的程序占着——请重新双击「配WiFi.bat」再试一次。")
        sys.exit(2)


if __name__ == "__main__":
    main()
