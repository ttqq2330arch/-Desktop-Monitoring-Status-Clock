#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3D 打印机实时状态采集（Creality Moonraker / Anycubic Cloud）。

两台打印机各自独立后台轮询，统一成 p1_*/p2_* 字段，供 monitor.py 注入串口 JSON。
配置见 printers.json（含凭据，**不进仓库**，已被 .gitignore 排除）；模板见 printers.json.example。

后端：
  - creality_moonraker : Creality K1 / K1 Max / K1C / Ender-3 V3(KE/K1/SE) / Hi / K2 等
                        Klipper 系统，本地 Moonraker 端口 7125，无需账号。
  - anycubic_cloud    : 纵维立方 Kobra 2 / 2 Pro / X / 3 等，走 Anycubic Cloud 云端账号
                        （从浏览器 localStorage["XX-Token"] 或 Slicer Next 的 access_token 取）。

网络：强制 IPv4 直连优先（解决家庭宽带 IPv6 卡顿），失败再回落本地代理端口
（Clash/v2ray 装了但没设系统代理时）。Anycubic Cloud 走公网，复用天气模块的同一套逻辑。

用法：
  python printers.py --dump        # 独立测试：轮询一次，打印归一化快照 + 保存原始 JSON
"""
import json
import os
import sys
import socket
import ssl
import threading
import time
import http.client
import urllib.request
import urllib.error

def _app_dir():
    """配置文件所在目录。

    打包成 exe（PyInstaller 单文件）后 __file__ 指向临时解压目录 _MEIPASS，
    直接用它会导致读不到 exe 同级的 printers.json。frozen 时改用 sys.executable
    定位，与 monitor.py 的 app_dir() 保持一致。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


HERE = _app_dir()
CONFIG_FILE = os.path.join(HERE, "printers.json")
POLL_INTERVAL = 15  # 秒；打印机状态变化慢，不必 1Hz 轮询（也避免狂打 Anycubic Cloud）
PROXY_PORTS = [7890, 7891, 10808, 10809, 1080, 8080]  # 本地代理常见端口（Clash/v2ray 等）

# 调试：把原始响应 JSON 落盘，便于拿到真实字段后微调映射
DUMP_FILE = os.path.join(HERE, "printer_debug.json")


# ---------------------------------------------------------------- 强制 IPv4 通道
# 与 monitor.py 的天气通道同一思路：家庭宽带常把 IPv6 排前面，urllib 先连 IPv6 卡 8 秒超时。
# 这里用自定义 connection 类强制 AF_INET，只走 IPv4；并支持代理隧道。
class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        addrs = socket.getaddrinfo(
            self.host, self.port, socket.AF_INET, socket.SOCK_STREAM
        )
        ip = addrs[0][4][0]
        self.sock = socket.create_connection((ip, self.port), self.timeout)
        if self._tunnel_host:
            self._tunnel()
        ctx = self._context or ssl.create_default_context()
        self.sock = ctx.wrap_socket(self.sock, server_hostname=self.host)


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_IPv4HTTPSConnection, req)


def _open(url, headers, timeout, proxy_url=None):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "pc-monitor/1.0"})
    handlers = []
    if url.startswith("https"):
        handlers.append(_IPv4HTTPSHandler())
    if proxy_url:
        handlers.append(urllib.request.ProxyHandler(
            {"http": proxy_url, "https": proxy_url}))
    else:
        # 直连：显式清空代理，绕开注册表里的失效代理（与天气模块一致）
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(req, timeout=timeout)


def http_get(url, headers=None, timeout=10, allow_proxy=True):
    """强制 IPv4 直连优先；失败则探测本地代理端口回落。返回 (text, status)。"""
    headers = dict(headers or {})
    headers.setdefault("User-Agent", "pc-monitor/1.0")
    last = None
    # 1) 直连
    try:
        r = _open(url, headers, timeout)
        return r.read().decode("utf-8", "ignore"), r.status
    except Exception as e:  # noqa: BLE001
        last = e
    if not allow_proxy:
        raise last
    # 2) 本地代理端口回落（局域网目标不应走代理，调用方对 LAN 设 allow_proxy=False）
    for port in PROXY_PORTS:
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            probe.settimeout(1)
            if probe.connect_ex(("127.0.0.1", port)) != 0:
                probe.close()
                continue
            probe.close()
            r = _open(url, headers, timeout, proxy_url=f"http://127.0.0.1:{port}")
            return r.read().decode("utf-8", "ignore"), r.status
        except Exception:  # noqa: BLE001
            continue
    raise last


# ---------------------------------------------------------------- 后端
def _ascii(s):
    """设备端字库只认 ASCII，非 ASCII 直接丢弃（避免方块/乱码）。"""
    if not s:
        return ""
    return s.encode("ascii", "ignore").decode("ascii") or ""


class CrealityMoonraker:
    """Creality Klipper 系统：本地 Moonraker HTTP API（端口 7125），无账号。"""

    def __init__(self, cfg):
        self.ip = cfg.get("ip", "")
        self.port = int(cfg.get("port", 7125))
        self.name = _ascii(cfg.get("name", "Creality")) or "Creality"

    def poll(self):
        url = (f"http://{self.ip}:{self.port}/printer/objects/query"
               f"?extruder&heater_bed&print_stats&virtual_sdcard")
        text, _ = http_get(url, timeout=8, allow_proxy=False)  # 局域网，不走代理
        j = json.loads(text)
        s = j["result"]["status"]
        hot = float(s["extruder"]["temperature"])
        bed = float(s["heater_bed"]["temperature"])
        ps = s.get("print_stats", {}) or {}
        state = ps.get("state", "standby")
        prog = int(round(float(ps.get("progress") or 0) * 100))
        fname = _ascii(ps.get("filename", "") or "")
        # standby/ready/offline -> 1(idle)；printing/paused -> 2(打印中)
        code = 2 if state in ("printing", "paused") else 1
        return {"name": self.name[:15], "state": code, "hot": hot,
                "bed": bed, "prog": prog, "file": fname[:23]}


class AnycubicCloud:
    """纵维立方 Kobra 系列：Anycubic Cloud 云端账号（XX-Token）。

    字段映射基于开源集成 hass-anycubic_cloud 逆向所得，部分字段（parameter 内的温度、
    当前任务的 progress/filename）在不同固件版本可能有差异——若实机数据不对，把
    printer_debug.json 里的原始 JSON 发我，一行就能修。
    """
    BASE = "https://cloud-universe.anycubic.com/p/p/workbench/api"

    def __init__(self, cfg):
        self.token = cfg.get("token", "")
        self.name = _ascii(cfg.get("name", "Anycubic")) or "Anycubic"
        self.device_name = cfg.get("device_name", "")  # 云端有多台时按 name 选定
        self.headers = {
            "XX-Token": self.token,
            "Origin": "https://uc.makeronline.com",
        }

    def _status_list(self):
        text, _ = http_get(f"{self.BASE}/work/printer/printersStatus",
                           headers=self.headers, timeout=10)
        return json.loads(text).get("data") or []

    def poll(self):
        arr = self._status_list()
        dev = None
        if self.device_name:
            for d in arr:
                if (d.get("name") or "") == self.device_name:
                    dev = d
                    break
        if dev is None and arr:
            dev = arr[0]
        if dev is None:
            return {"name": self.name[:15], "state": 0, "hot": -1,
                    "bed": -1, "prog": -1, "file": ""}
        name = _ascii(dev.get("name") or self.name) or self.name
        offline = (dev.get("device_status") or "online") != "online"
        state = 0 if offline else (2 if dev.get("is_printing") else 1)
        # 温度在 parameter 字典里，键名与 MQTT 同源（curr_nozzle_temp / curr_hotbed_temp），做容错
        hot, bed = -1.0, -1.0
        param = dev.get("parameter") or {}
        if isinstance(param, dict):
            for k, v in param.items():
                kl = str(k).lower()
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if "nozzle" in kl and ("curr" in kl or "temp" in kl):
                    hot = fv
                elif "hotbed" in kl and ("curr" in kl or "temp" in kl):
                    bed = fv
        # 进度 + 文件名：打印中才去查当前任务（getProjects 取最近的任务）
        prog, fname = -1, ""
        if state == 2:
            try:
                text, _ = http_get(f"{self.BASE}/work/project/getProjects?page=1&limit=5",
                                   headers=self.headers, timeout=10)
                for p in (json.loads(text).get("data") or []):
                    ps = str(p.get("print_status") or p.get("status") or "")
                    if ps in ("1", "2") or "print" in ps.lower():
                        fname = _ascii(p.get("gcode_name") or p.get("name") or "")
                        try:
                            prog = int(round(float(p.get("progress") or 0)))
                        except (TypeError, ValueError):
                            prog = -1
                        break
            except Exception:  # noqa: BLE001
                pass
        return {"name": name[:15], "state": state, "hot": hot,
                "bed": bed, "prog": prog, "file": fname[:23]}


# ---------------------------------------------------------------- 管理器
class PrinterManager:
    """按 printers.json 启动多台打印机的后台轮询，对外暴露 snapshot()。"""

    def __init__(self, cfg):
        self.backends = []
        for key in ("printer1", "printer2"):
            c = cfg.get(key)
            if not c or not c.get("enabled", True):
                continue
            t = c.get("type")
            if t == "creality_moonraker":
                self.backends.append((key, CrealityMoonraker(c)))
            elif t == "anycubic_cloud":
                self.backends.append((key, AnycubicCloud(c)))
        self.snap = {}
        self.lock = threading.Lock()
        self.stop = False
        self._thread = None

    def _run(self):
        while not self.stop:
            for key, be in self.backends:
                idx = key[-1]  # '1' / '2'
                try:
                    r = be.poll()
                    with self.lock:
                        for fk, fv in r.items():
                            self.snap[f"p{idx}_{fk}"] = fv
                        self.snap[f"p{idx}_have"] = 1
                except Exception as e:  # noqa: BLE001
                    with self.lock:
                        self.snap[f"p{idx}_have"] = 0
                        self.snap[f"p{idx}_state"] = 0
                    print(f"[打印机{idx}] 轮询失败：{e}")
            time.sleep(POLL_INTERVAL)

    def start(self):
        if not self.backends:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        names = ", ".join(k for k, _ in self.backends)
        print(f"[打印机] 已启动（每 {POLL_INTERVAL}s 刷新）：{names}")

    def snapshot(self):
        with self.lock:
            return dict(self.snap)


def load_config():
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:  # noqa: BLE001
        print(f"[打印机] 配置读取失败（{e}），不启用打印机监控")
        return {}


# ---------------------------------------------------------------- 独立调试
def _dump():
    cfg = load_config()
    if not cfg:
        print("printers.json 不存在或为空，无法 dump")
        return
    pm = PrinterManager(cfg)
    raw = {}
    for key, be in pm.backends:
        idx = key[-1]
        try:
            if isinstance(be, CrealityMoonraker):
                url = (f"http://{be.ip}:{be.port}/printer/objects/query"
                       f"?extruder&heater_bed&print_stats&virtual_sdcard")
                text, _ = http_get(url, timeout=8, allow_proxy=False)
            else:
                arr = be._status_list()  # noqa: SLF001
                text = json.dumps(arr, ensure_ascii=False)
            raw[f"printer{idx}"] = json.loads(text)
        except Exception as e:  # noqa: BLE001
            raw[f"printer{idx}_error"] = str(e)
    try:
        with open(DUMP_FILE, "w", encoding="utf-8") as f:
            json.dump(raw, f, ensure_ascii=False, indent=2)
        print(f"原始 JSON 已存到 {DUMP_FILE}")
    except Exception:  # noqa: BLE001
        pass
    # 跑一次归一化快照（直接调用各后端 poll 的归一化结果，不走后台线程）
    snap = {}
    for key, be in pm.backends:
        idx = key[-1]
        try:
            r = be.poll()
            for fk, fv in r.items():
                snap[f"p{idx}_{fk}"] = fv
            snap[f"p{idx}_have"] = 1
        except Exception as e:  # noqa: BLE001
            snap[f"p{idx}_have"] = 0
            snap[f"p{idx}_state"] = 0
            print(f"[打印机{idx}] poll 失败：{e}")
    print("归一化快照：", json.dumps(snap, ensure_ascii=False))


if __name__ == "__main__":
    if "--dump" in sys.argv:
        _dump()
    else:
        print("用法：python printers.py --dump")
