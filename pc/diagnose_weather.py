#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diagnose_weather.py -- pc-monitor 天气取数失败诊断工具（零依赖，只用标准库）

用法：
    python diagnose_weather.py
把本文件拷到「无法显示天气」的那台电脑上，装了 Python 的话直接双击/命令行跑。
它会分别测试天气链路每一个环节的多种网络出口，并直接告诉你卡在哪：

  [默认直连]  —— 让系统自己决定走 IPv4 还是 IPv6（monitor 现在的做法）
  [强制IPv4]  —— 只用 IPv4（解决「家庭宽带 IPv6 路由不通但被优先」）
  [系统代理]  —— 走 IE/系统设置里的代理（monitor 的回落逻辑）
  [本地代理]  —— 探测 Clash/v2ray 常见本地端口（解决「有代理没设系统」）

判读：
  · 默认直连 FAIL、强制IPv4 OK      -> 家庭宽带 IPv6 问题，软件需强制 IPv4
  · 三者都 FAIL                     -> 该网络确实连不上外网，需代理或换国内源
  · 仅 pconline/ipinfo FAIL         -> 定位源问题，可写死城市（auto_location=false）
"""
import socket
import http.client
import urllib.request
import urllib.parse
import time
import sys

TARGETS = [
    ("Open-Meteo 天气预报", "https://api.open-meteo.com/v1/forecast?latitude=39.9042&longitude=116.4074&current=temperature_2m"),
    ("Open-Meteo 地理编码", "https://geocoding-api.open-meteo.com/v1/search?name=Beijing&count=1&language=zh"),
    ("pconline 国内定位",   "https://whois.pconline.com.cn/ipJson.jsp"),
    ("ipinfo 兜底定位",     "https://ipinfo.io/geo"),
]

PROXY_PORTS = (7890, 7891, 10808, 10809, 1080, 8080)


def _fetch_default(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "pc-monitor-diag/1.0"})
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(req, timeout=timeout) as r:
        return len(r.read())


def _fetch_v4(url, timeout=8):
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    port = parsed.port or 443
    # 只用 IPv4 地址族，绕过系统优先 IPv6 导致的卡顿/超时
    addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
    ip = addrs[0][4][0]
    path = parsed.path + (("?" + parsed.query) if parsed.query else "")
    conn = http.client.HTTPSConnection(ip, port, timeout=timeout)
    try:
        conn.putrequest("GET", path)
        conn.putheader("Host", host)
        conn.putheader("User-Agent", "pc-monitor-diag/1.0")
        conn.endheaders()
        resp = conn.getresponse()
        data = resp.read()
        return len(data)
    finally:
        conn.close()


def _fetch_proxy(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "pc-monitor-diag/1.0"})
    with urllib.request.build_opener().open(req, timeout=timeout) as r:
        return len(r.read())


def _fetch_local_proxy(url, port, timeout=3):
    req = urllib.request.Request(url, headers={"User-Agent": "pc-monitor-diag/1.0"})
    ph = urllib.request.ProxyHandler({"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"})
    with urllib.request.build_opener(ph).open(req, timeout=timeout) as r:
        return len(r.read())


def _test(name, fn):
    try:
        t = time.time()
        n = fn()
        return f"OK  ({n}B, {time.time()-t:.2f}s)"
    except Exception as e:
        return f"FAIL  {type(e).__name__}: {e}"


def main():
    print("=" * 64)
    print(" pc-monitor 天气链路诊断  (零依赖 / 标准库)")
    print("=" * 64)
    for name, url in TARGETS:
        print(f"\n--- {name} ---")
        print(f"  {url[:72]}")
        print(f"  [默认直连] {_test('d', lambda: _fetch_default(url))}")
        print(f"  [强制IPv4] {_test('v', lambda: _fetch_v4(url))}")
        print(f"  [系统代理] {_test('p', lambda: _fetch_proxy(url))}")
        hit = None
        for p in PROXY_PORTS:
            try:
                _fetch_local_proxy(url, p)
                hit = p
                break
            except Exception:
                continue
        print(f"  [本地代理] {'OK 发现本地代理端口 :%d' % hit if hit else '未发现常见本地代理端口'}")

    print("\n" + "=" * 64)
    print(" 结论速查")
    print("=" * 64)
    print(" · 默认直连 FAIL、强制IPv4 OK  -> 家庭宽带 IPv6 路由不通，软件需强制 IPv4")
    print(" · 默认/IPv4/系统代理 三者都 FAIL -> 该网络连不上外网，需代理或换国内源")
    print(" · 仅 pconline/ipinfo FAIL      -> 定位源问题，可写死城市(auto_location=false)")
    print(" · 发现本地代理端口             -> 那台电脑有代理但没设系统，软件应自动探测")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    input("\n按回车退出...")
