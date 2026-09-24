#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3D 打印机实时状态采集（Creality Moonraker / Anycubic 局域网 MQTT）。

两台打印机各自独立后台轮询，统一成 p1_*/p2_* 字段，供 monitor.py 注入串口 JSON。
配置见 printers.json（含凭据，**不进仓库**，已被 .gitignore 排除）；模板见 printers.json.example。

后端：
  - creality_moonraker : Creality K1 / K1 Max / K1C / Ender-3 V3(KE/K1/SE) / Hi / K2 等
                        Klipper 系统，本地 Moonraker 端口 7125，无需账号。
  - anycubic_lan      : 纵维立方 Kobra（须在打印机屏幕上开启「局域网模式」）。
                        免配置凭据：HTTP :18910 /info→/ctrl 现场发现 MQTT 账号+客户端证书，
                        连打印机本地 MQTTS :9883 订阅 print/report 事件（2026-09-24 全链路实测）。
                        （旧 anycubic_cloud 云端路线因国内/国际站账号隔离已判死，保留类但别用。）

网络：打印机是局域网设备，一律强制 IPv4 直连、不走代理（allow_proxy=False）。

用法：
  python printers.py --dump        # 独立测试：轮询一次，打印归一化快照 + 保存原始 JSON
"""
import hashlib
import json
import os
import sys
import socket
import ssl
import threading
import time
import uuid
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


def _proxy_ports():
    """本地代理候选端口：环境变量里实际配的端口 + 常见 Clash/v2ray 端口。

    端口是动态的，写死一份列表会漏。实测本机 HTTP(S)_PROXY 指向 61568，
    而常用的 7890 反而不通 —— 所以必须把 env 里的真实端口排在前面。
    """
    ports = []
    for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
        v = os.environ.get(var, "")
        if not v:
            continue
        tail = v.rstrip("/").rsplit(":", 1)[-1]
        if tail.isdigit():
            ports.append(int(tail))
    ports += [7890, 7891, 10808, 10809, 1080, 8080]
    seen, out = set(), []
    for p in ports:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out

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
    for port in _proxy_ports():
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


def _deep(obj, pred, depth=0):
    """在嵌套 dict/list 里深度优先找第一个满足 pred(小写键名, 值) 的标量。

    Anycubic 各固件的响应层级不一致（有的字段在顶层、有的裹在 machine_data /
    parameter 里），逐个写死路径很容易踩空，这里做结构无关的容错查找。
    """
    if depth > 6:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(v, (dict, list)) and pred(str(k).lower(), v):
                return v
        for v in obj.values():
            if isinstance(v, (dict, list)):
                r = _deep(v, pred, depth + 1)
                if r is not None:
                    return r
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                r = _deep(v, pred, depth + 1)
                if r is not None:
                    return r
    return None


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

    鉴权需要「公参」：服务端要求每个请求带足 Xx-* 头，其中签名算法为
        MD5(APP_ID + 时间戳ms + 版本 + APP_SECRET + nonce + APP_ID)
    少任何一项都返回 {"code":51000,"msg":"请求公参异常,缺少必传的公参"}。
    （已实测：补齐后同一 token 的报错变为 code 10001「登录信息失效」，
    证明公参已被服务端接受，只差有效 token。）

    APP_ID / APP_SECRET 是 Anycubic 官方客户端的公开常量（与开源集成
    hass-anycubic_cloud、MMM-Anycubic 一致），不是用户私密信息。

    字段映射做结构无关的容错查找；若实机数据不对，把 printer_debug.json
    里的原始响应发来，一行就能修。
    """
    BASE = "https://cloud-universe.anycubic.com/p/p/workbench/api"
    APP_ID = "f9b3528877c94d5c9c5af32245db46ef"
    APP_SECRET = "0cf75926606049a3937f56b0373b99fb"
    APP_VERSION = "1.0.0"

    def __init__(self, cfg):
        self.token = cfg.get("token", "")
        self.name = _ascii(cfg.get("name", "Anycubic")) or "Anycubic"
        self.device_name = cfg.get("device_name", "")  # 云端有多台时按 name 选定
        self.raw = {}  # 最近一次原始响应，供排错

    # -- 鉴权 ---------------------------------------------------------------
    def _headers(self):
        """签名含时间戳与随机 nonce，每次请求都要重新生成，不能缓存复用。"""
        nonce = str(uuid.uuid1())
        ts = str(int(time.time() * 1000))
        sign = hashlib.md5(
            (self.APP_ID + ts + self.APP_VERSION + self.APP_SECRET
             + nonce + self.APP_ID).encode("utf-8")
        ).hexdigest()
        return {
            "Xx-Device-Type": "web",
            "Xx-Is-Cn": "1",
            "Xx-Nonce": nonce,
            "Xx-Token": self.token,
            "Xx-Signature": sign,
            "Xx-Timestamp": ts,
            "Xx-Version": self.APP_VERSION,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, path):
        text, _ = http_get(f"{self.BASE}{path}", headers=self._headers(), timeout=12)
        j = json.loads(text)
        code = j.get("code")
        if code not in (None, 0, 200):
            raise RuntimeError(f"Anycubic API code={code} msg={j.get('msg')}")
        return j

    def _status_list(self):
        # 注意：不是 printersStatus —— 官方 web 端用的是 work/printer/getPrinters
        return self._get("/work/printer/getPrinters").get("data") or []

    # -- 取数 ---------------------------------------------------------------
    @staticmethod
    def _dev_name(d):
        md = d.get("machine_data")
        md = md if isinstance(md, dict) else {}
        return _ascii(d.get("name") or md.get("name") or "")

    def poll(self):
        arr = self._status_list()
        self.raw = {"getPrinters": arr}

        dev = None
        if self.device_name:
            for d in arr:
                if self._dev_name(d) == self.device_name:
                    dev = d
                    break
        if dev is None and arr:
            dev = arr[0]
        if dev is None:
            return {"name": self.name[:15], "state": 0, "hot": -1,
                    "bed": -1, "prog": -1, "file": ""}

        # machine_data 里放的是实时状态，优先于顶层字段（层级随固件而异）
        md = dev.get("machine_data")
        flat = dict(dev)
        if isinstance(md, dict):
            flat.update(md)

        name = self._dev_name(dev) or self.name
        dstat = str(flat.get("device_status") or flat.get("status") or "online").lower()
        offline = dstat not in ("online", "1", "true", "idle", "")
        printing = str(flat.get("is_printing") or "").lower() in ("1", "true", "yes")
        state = 0 if offline else (2 if printing else 1)

        def _num(*key_parts):
            """按 key_parts 顺序找第一个能转成数字的字段（curr_* 优先于 target）。"""
            for kp in key_parts:
                v = _deep(flat, lambda k, val, _kp=kp: _kp in k
                          and isinstance(val, (int, float, str)))
                try:
                    return float(v)
                except (TypeError, ValueError):
                    continue
            return -1.0

        hot = _num("curr_nozzle", "nozzle")
        bed = _num("curr_hotbed", "hotbed", "bed_temp")

        # 进度 + 文件名：打印中才去查当前任务（getProjects 返回最近的任务）
        prog, fname = -1, ""
        if state == 2:
            try:
                pj = self._get("/work/project/getProjects?page=1&limit=5")
                self.raw["getProjects"] = pj.get("data") or []
                for p in (pj.get("data") or []):
                    ps = str(p.get("print_status") or p.get("status") or "").lower()
                    if ps in ("1", "2") or "printing" in ps or "print" in ps:
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


# ---------------------------------------------------------------- 纯 Python AES-128-CBC
# 打包成 exe 时不想拖 cryptography 这个大依赖（C 扩展，PyInstaller 体积+易踩坑），
# 这里内嵌一份紧凑的 AES-128 解密实现。S 盒用「GF(2^8) 求逆 + 仿射变换」现场生成，
# 避免手抄 256 个常量出 typo。只解 ~2KB 的凭据包，性能完全无感。
def _gmul(a, b):
    """GF(2^8) 乘法（模 x^8+x^4+x^3+x+1）。"""
    r = 0
    for _ in range(8):
        if b & 1:
            r ^= a
        a = ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else (a << 1)
        b >>= 1
    return r


_AES_SBOX = None
_AES_ISBOX = None


def _aes_tables():
    global _AES_SBOX, _AES_ISBOX
    if _AES_SBOX is not None:
        return _AES_SBOX, _AES_ISBOX
    inv = [0] * 256
    for x in range(1, 256):
        for y in range(1, 256):
            if _gmul(x, y) == 1:
                inv[x] = y
                break
    sbox = [0] * 256
    for x in range(256):
        b = inv[x]
        s = b
        for _ in range(4):
            b = ((b << 1) | (b >> 7)) & 0xFF
            s ^= b
        sbox[x] = s ^ 0x63
    isbox = [0] * 256
    for x, v in enumerate(sbox):
        isbox[v] = x
    _AES_SBOX, _AES_ISBOX = sbox, isbox
    return _AES_SBOX, _AES_ISBOX


def _aes128_expand_key(key):
    """AES-128 密钥扩展：44 个 32 位字。"""
    sbox, _ = _aes_tables()
    rcon = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)
    w = [list(key[i * 4:i * 4 + 4]) for i in range(4)]
    for i in range(4, 44):
        t = list(w[i - 1])
        if i % 4 == 0:
            t = t[1:] + t[:1]
            t = [sbox[b] for b in t]
            t[0] ^= rcon[i // 4]
        w.append([w[i - 4][j] ^ t[j] for j in range(4)])
    return w


def _aes128_decrypt_block(block, w):
    """解密单个 16 字节块（state 按列主序铺平，与 FIPS-197 一致）。"""
    _, isbox = _aes_tables()

    def add_rk(s, rnd):
        for c in range(4):
            for r in range(4):
                s[r + 4 * c] ^= w[rnd * 4 + c][r]

    s = list(block)
    add_rk(s, 10)
    for rnd in range(9, 0, -1):
        # InvShiftRows：行 r 循环右移 r（state 行 = s[r::4]）
        for r in range(1, 4):
            row = s[r::4]
            row = row[-r:] + row[:-r]
            s[r::4] = row
        for i in range(16):
            s[i] = isbox[s[i]]
        add_rk(s, rnd)
        # InvMixColumns：每列乘 {0e,0b,0d,09}
        for c in range(4):
            a = s[4 * c:4 * c + 4]
            s[4 * c + 0] = _gmul(a[0], 14) ^ _gmul(a[1], 11) ^ _gmul(a[2], 13) ^ _gmul(a[3], 9)
            s[4 * c + 1] = _gmul(a[0], 9) ^ _gmul(a[1], 14) ^ _gmul(a[2], 11) ^ _gmul(a[3], 13)
            s[4 * c + 2] = _gmul(a[0], 13) ^ _gmul(a[1], 9) ^ _gmul(a[2], 14) ^ _gmul(a[3], 11)
            s[4 * c + 3] = _gmul(a[0], 11) ^ _gmul(a[1], 13) ^ _gmul(a[2], 9) ^ _gmul(a[3], 14)
    for r in range(1, 4):
        row = s[r::4]
        row = row[-r:] + row[:-r]
        s[r::4] = row
    for i in range(16):
        s[i] = isbox[s[i]]
    add_rk(s, 0)
    return bytes(s)


def _aes_cbc_decrypt(data, key, iv):
    """AES-128-CBC 解密 + 去 PKCS7 填充。"""
    if len(key) != 16:
        raise ValueError(f"AES-128 密钥须 16 字节，得到 {len(key)}")
    if len(data) == 0 or len(data) % 16:
        raise ValueError(f"密文长度非 16 的倍数：{len(data)}")
    w = _aes128_expand_key(key)
    out = bytearray()
    prev = iv
    for off in range(0, len(data), 16):
        blk = _aes128_decrypt_block(data[off:off + 16], w)
        out.extend(b ^ p for b, p in zip(blk, prev))
        prev = data[off:off + 16]
    pad = out[-1]
    if not 1 <= pad <= 16:
        raise ValueError(f"PKCS7 填充非法: {pad}")
    return bytes(out[:-pad])


class AnycubicLAN:
    """纵维立方 Kobra（打印机屏幕已开启「局域网模式」）。

    完全免配置凭据：
      1. GET  http://{ip}:18910/info            → 拿 token + ctrlInfoUrl（明文 HTTP）
      2. POST {ctrlInfoUrl}?ts=&nonce=&sign=&did → AES-CBC 密文
         sign = MD5( MD5(token[:16]) + ts + nonce )
         密钥 = token[16:32]，IV = 响应里的 data.token
      3. 解出 MQTT 账号密码 + 客户端证书 → 连 mqtts://{ip}:9883
      4. 订阅 anycubic/#：
         - print/report 事件推送（打印开始/进度变化）
         - 每 30s 主动发 info 查询（Rinkhals 社区逆向的协议，2026-09-24 实测通过）：
           发布 anycubic/anycubicCloud/v1/slicer/printer/{model}/{dev}/info
             payload {"type":"info","action":"query","msgid":uuid,"timestamp":ms}
           打印机回复 .../printer/public/{model}/{dev}/info/report，
           data.temp = {curr_nozzle_temp, curr_hotbed_temp, target_*}（温度只有这里有）
    """

    INFO_QUERY_PERIOD = 30  # 主动查询周期（秒）；温度/状态权威来源

    def __init__(self, cfg):
        self.ip = cfg.get("ip", "")
        self.http_port = int(cfg.get("http_port", 18910))
        self.mqtt_port = int(cfg.get("mqtt_port", 9883))
        self.name = _ascii(cfg.get("name", "Anycubic")) or "Anycubic"
        self.raw = {}  # 最近一次事件原文，供排错
        self._lock = threading.Lock()
        self._snap = {"name": self.name[:15], "state": 0, "hot": -1.0,
                      "bed": -1.0, "prog": -1, "file": ""}
        self._thread = None
        self._stop = False
        self._cli = None      # 当前 MQTT 客户端（查询线程用来发命令）
        self._model = ""      # info 查询话题用的 modelId/deviceId
        self._devid = ""

    # -- 凭据发现 -----------------------------------------------------------
    def _discover(self):
        text, _ = http_get(f"http://{self.ip}:{self.http_port}/info",
                           timeout=6, allow_proxy=False)
        info = json.loads(text)
        tok = info["token"]
        ctrl_url = info["ctrlInfoUrl"]
        ts = str(int(time.time() * 1000))
        alpha = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        nc = "".join(alpha[uuid.uuid4().int % 62] for _ in range(6))
        sign = hashlib.md5(
            (hashlib.md5(tok[:16].encode()).hexdigest() + ts + nc).encode()
        ).hexdigest()
        did = hashlib.md5(socket.gethostname().encode()).hexdigest()[:16]
        sep = "&" if "?" in ctrl_url else "?"
        req = urllib.request.Request(
            f"{ctrl_url}{sep}ts={ts}&nonce={nc}&sign={sign}&did={did}", method="POST")
        # urllib 默认会读环境代理，局域网地址必须显式清空
        with urllib.request.build_opener(
                urllib.request.ProxyHandler({})).open(req, timeout=8) as r:
            ctrl = json.loads(r.read().decode("utf-8"))
        if ctrl.get("code") != 200:
            raise RuntimeError(f"/ctrl code={ctrl.get('code')}")
        import base64
        cipher = base64.b64decode(ctrl["data"]["info"])
        key = tok[16:32].encode("ascii")
        iv = ctrl["data"]["token"].encode("ascii")
        return json.loads(_aes_cbc_decrypt(cipher, key, iv).decode("utf-8"))

    # -- 事件 ingestion -----------------------------------------------------
    def _ingest(self, topic, payload):
        try:
            j = json.loads(payload)
        except Exception:  # noqa: BLE001
            return
        act = str(j.get("action", "")).lower()
        d = j.get("data") if isinstance(j.get("data"), dict) else {}
        self.raw = {"topic": topic, "action": act, "data": d}

        # info/report：主动查询的回复，权威状态 + 温度（唯一温度来源）
        if topic.endswith("/info/report"):
            with self._lock:
                temp = d.get("temp") if isinstance(d.get("temp"), dict) else {}
                try:
                    self._snap["hot"] = float(temp["curr_nozzle_temp"])
                except (KeyError, TypeError, ValueError):
                    pass
                try:
                    self._snap["bed"] = float(temp["curr_hotbed_temp"])
                except (KeyError, TypeError, ValueError):
                    pass
                st = str(d.get("state", "")).lower()
                if st in ("printing", "resuming", "pausing"):
                    self._snap["state"] = 2
                elif st in ("free", "idle", "done", "paused", "stopped",
                            "finished", "success", "failed", "error"):
                    # 空闲/完成类；failed/error 仍按"空闲"展示（没有更细的档位）
                    self._snap["state"] = 1
            return

        if act in ("start", "resume", "report", "progress", "printing", "reprint"):
            state = 2
        elif act in ("stop", "end", "finish", "completed", "complete",
                     "pause", "paused", "error", "abort", "cancel"):
            state = 1
        else:
            state = None  # 未知的 action 不动状态，raw 里留档观察
        with self._lock:
            if state is not None:
                self._snap["state"] = state
            try:
                prog = int(round(float(d.get("progress"))))
                if 0 <= prog <= 100:
                    self._snap["prog"] = prog
            except (TypeError, ValueError):
                pass
            fname = _ascii(str(d.get("filename") or d.get("file_root_path") or ""))
            if fname:
                self._snap["file"] = fname[:23]

    # -- MQTT 会话线程 --------------------------------------------------------
    def _session(self):
        import paho.mqtt.client as mqtt
        cred = self._discover()
        user = str(cred.get("username", ""))
        pwd = str(cred.get("password", ""))
        self._model = str(cred.get("modelId", ""))
        self._devid = str(cred.get("deviceId", ""))
        crt = os.path.join(HERE, "_kx_client.crt")
        key = os.path.join(HERE, "_kx_client.key")
        with open(crt, "w", encoding="ascii") as f:
            f.write(str(cred.get("devicecrt", "")))
        with open(key, "w", encoding="ascii") as f:
            f.write(str(cred.get("devicepk", "")))

        def on_conn(client, userdata, flags, rc, properties=None):
            if rc == 0:
                print(f"[{self.name}] 局域网 MQTT 已连接 {self.ip}:{self.mqtt_port}")
                client.subscribe("anycubic/#", qos=1)
            else:
                print(f"[{self.name}] MQTT 连接被拒 rc={rc}")

        def on_msg(client, userdata, msg):
            self._ingest(msg.topic, msg.payload.decode("utf-8", "replace"))

        cli = mqtt.Client(
            # client_id 必须唯一：broker 对重复 id 会踢旧连接——
            # 若电脑上跑了两个实例（monitor + 手动测试），同 id 会互踢、消息收不全
            client_id=hashlib.md5((user or self.ip).encode()).hexdigest()[:16]
                      + uuid.uuid4().hex[:8],
            protocol=mqtt.MQTTv311)
        cli.username_pw_set(user, pwd)
        # 打印机证书是自签名的：paho 的 tls_insecure_set 只跳主机名校验，
        # 必须同时 cert_reqs=CERT_NONE 才能过自签名 CA 校验（踩过）
        cli.tls_set(certfile=crt, keyfile=key, cert_reqs=ssl.CERT_NONE)
        cli.tls_insecure_set(True)
        cli.on_connect = on_conn
        cli.on_message = on_msg
        cli.reconnect_delay_set(3, 30)
        self._cli = cli
        cli.connect(self.ip, self.mqtt_port, keepalive=30)

        # 主动查询线程：温度只在 info/query→info/report 这条链上（Rinkhals 文档协议）
        def query_loop():
            while not self._stop:
                c = self._cli
                if c is not None and self._model and self._devid and c.is_connected():
                    try:
                        c.publish(
                            f"anycubic/anycubicCloud/v1/slicer/printer/"
                            f"{self._model}/{self._devid}/info",
                            json.dumps({"type": "info", "action": "query",
                                        "msgid": str(uuid.uuid4()),
                                        "timestamp": int(time.time() * 1000)}),
                            qos=1)
                    except Exception:  # noqa: BLE001
                        pass
                for _ in range(self.INFO_QUERY_PERIOD):
                    if self._stop:
                        return
                    time.sleep(1)

        qt = threading.Thread(target=query_loop, daemon=True)
        qt.start()
        cli.loop_forever()  # 内置自动重连；连接异常退出后由外层重新发现凭据

    def _run(self):
        backoff = 3
        while not self._stop:
            try:
                self._session()
                backoff = 3  # 正常退出（理论上不会）
            except Exception as e:  # noqa: BLE001
                print(f"[{self.name}] 局域网链路异常：{e}，{backoff}s 后重试")
                with self._lock:
                    self._snap["state"] = 0
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)

    # -- 取数 ---------------------------------------------------------------
    def poll(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
        with self._lock:
            return dict(self._snap)


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
            elif t == "anycubic_lan":
                self.backends.append((key, AnycubicLAN(c)))
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
            print("[打印机] 配置里没有启用的打印机，跳过轮询（屏幕第 4/5 页会显示「无数据」）")
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
        # 别静默：否则用户只看得到「屏幕上没有数据」，分不清是没配置还是坏了
        print(f"[打印机] 未找到 {os.path.basename(CONFIG_FILE)}，打印机监控未启用"
              f"（把 printers.json.example 复制为 printers.json 并填写）")
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
    # 后台线程先跑起来（Anycubic LAN 是事件驱动，需要几秒收第一帧）
    for _, be in pm.backends:
        if isinstance(be, AnycubicLAN):
            be.poll()
    time.sleep(12)
    raw = {}
    for key, be in pm.backends:
        idx = key[-1]
        try:
            if isinstance(be, CrealityMoonraker):
                url = (f"http://{be.ip}:{be.port}/printer/objects/query"
                       f"?extruder&heater_bed&print_stats&virtual_sdcard")
                text, _ = http_get(url, timeout=8, allow_proxy=False)
                raw[f"printer{idx}"] = json.loads(text)
            elif isinstance(be, AnycubicLAN):
                raw[f"printer{idx}"] = be.raw or {"_note": "还没收到事件（打印机上报是事件驱动的）"}
            else:
                arr = be._status_list()  # noqa: SLF001
                raw[f"printer{idx}"] = arr
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
