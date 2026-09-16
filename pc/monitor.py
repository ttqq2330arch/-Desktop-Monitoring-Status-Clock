#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
桌面电脑状态监控 · PC 采集端
每 1 秒采集本机状态，通过 USB 串口（CH340）以 JSON 行推给 ESP32 小屏。

用法
    python monitor.py                # 自动扫描 CH340 串口
    python monitor.py --port COM3    # 手动指定串口
    python monitor.py --list         # 只列出可用串口后退出
    python monitor.py --temp         # 启用 CPU 温度（需管理员权限 + LibreHardwareMonitor）

依赖
    pip install psutil pyserial pynvml

开机自启（推荐，任务计划）
    schtasks /create /tn PCMonitor /tr "pythonw <本文件绝对路径>" /sc onlogon /rl highest /f
    不需要管理员时去掉 /rl highest
    删除：schtasks /delete /tn PCMonitor /f

注意：脚本运行时会独占 COM 口，烧录 ESP32 前必须先关掉它。
"""

import argparse
import json
import re
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

try:
    import psutil
except ImportError:
    sys.exit("缺少 psutil，先执行：pip install psutil")

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    sys.exit("缺少 pyserial，先执行：pip install pyserial")


def app_dir():
    """脚本所在目录。

    打包成 exe 后 __file__ 指向临时解压目录（_MEIPASS），直接用它会把日志
    写进临时目录、进程一退出就没了。所以 frozen 时改用 sys.executable 定位。
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


HERE = app_dir()

# pythonw（开机自启、无控制台）下 sys.stdout 为 None，后续 print 会直接崩溃；
# 这里兜底把 stdout/stderr 重定向到日志文件。有控制台运行时不受影响。
if getattr(sys, "stdout", None) is None:
    sys.stdout = open(
        os.path.join(HERE, "monitor.log"),
        "a", encoding="utf-8", buffering=1,
    )
if getattr(sys, "stderr", None) is None:
    sys.stderr = sys.stdout

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 启动痕迹：无条件落盘，只写 ASCII。
# 用来区分「系统压根没拉起自启」和「脚本起来了但中途崩了」——没有这行就只能靠猜。
try:
    with open(os.path.join(HERE, "monitor.log"),
              "a", encoding="utf-8") as _f:
        _f.write("[LAUNCH] %s pid=%s exe=%s\n" % (
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            os.getpid(),
            os.path.basename(sys.executable),
        ))
except Exception:
    pass

BAUD = 115200
# 沁恒 CH340/CH341 全系 VID
CH340_VIDS = (0x1A86,)
CH340_PIDS = (0x7523, 0x7522, 0x5523, 0x55D4)


# ---------------------------------------------------------------- 串口发现
def list_ports():
    return list(serial.tools.list_ports.comports())


def find_ch340():
    for p in list_ports():
        if p.vid in CH340_VIDS and (p.pid in CH340_PIDS or p.pid is None):
            return p.device
        desc = f"{p.description or ''} {p.manufacturer or ''}".upper()
        if "CH340" in desc or "CH341" in desc or "USB-SERIAL" in desc:
            return p.device
    return None


def open_port(port):
    try:
        s = serial.Serial(port, BAUD, timeout=1, write_timeout=1)
        print(f"[串口] 已连接 {port} @ {BAUD}")
        return s
    except Exception as e:
        print(f"[串口] 打开 {port} 失败：{e}")
        return None


# ---------------------------------------------------------------- 网络速率
class NetRate:
    """按真实间隔做差值，不硬编码 1 秒"""

    def __init__(self):
        self.prev = None

    def _total(self):
        rx = tx = 0
        for name, c in psutil.net_io_counters(pernic=True).items():
            if name.lower().startswith("lo"):
                continue
            rx += c.bytes_recv
            tx += c.bytes_sent
        return rx, tx

    def sample(self):
        now = time.monotonic()
        rx, tx = self._total()
        if self.prev is None:
            self.prev = (rx, tx, now)
            return 0.0, 0.0
        prx, ptx, pt = self.prev
        dt = max(now - pt, 0.001)
        up = (tx - ptx) / dt / 1024.0
        dn = (rx - prx) / dt / 1024.0
        self.prev = (rx, tx, now)
        return max(up, 0.0), max(dn, 0.0)


# ---------------------------------------------------------------- GPU（NVIDIA）
class GPU:
    def __init__(self):
        self.ok = False
        try:
            import warnings

            # pynvml 老包名会刷 FutureWarning，功能没影响，静音即可
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", FutureWarning)
                import pynvml

            self.pynvml = pynvml
            try:
                pynvml.nvmlInit()
            except Exception:
                pynvml.nvmlInit_v2()
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.ok = True
            print("[GPU] pynvml 就绪")
        except Exception as e:
            print(f"[GPU] 不可用（非 N 卡或未装 pynvml），该行显示 --：{e}")

    def read(self):
        if not self.ok:
            return None, None
        try:
            u = self.pynvml.nvmlDeviceGetUtilizationRates(self.handle).gpu
            t = self.pynvml.nvmlDeviceGetTemperature(
                self.handle, self.pynvml.NVML_TEMPERATURE_GPU
            )
            return int(u), int(t)
        except Exception:
            self.ok = False
            return None, None


# ---------------------------------------------------------------- CPU 温度（可选）
class CpuTemp:
    """需要管理员权限，且脚本目录要有 LibreHardwareMonitorLib.dll
    拿不到就静默降级，不影响其他指标。"""

    def __init__(self, enable):
        self.ok = False
        if not enable:
            return
        try:
            import clr  # pythonnet

            dll = os.path.join(HERE, "LibreHardwareMonitor", "LibreHardwareMonitorLib.dll")
            if not os.path.exists(dll):
                print(f"[温度] 未找到 {dll}，已跳过")
                return
            clr.AddReference(dll)
            from LibreHardwareMonitor import Hardware

            self.HW = Hardware
            self.computer = Hardware.Computer()
            self.computer.IsCpuEnabled = True
            self.computer.IsGpuEnabled = False
            self.computer.Open()
            self.ok = True
            print("[温度] LibreHardwareMonitor 就绪")
        except Exception as e:
            print(f"[温度] 初始化失败，已跳过：{e}")

    def read(self):
        if not self.ok:
            return None
        try:
            for hw in self.computer.Hardware:
                hw.Update()
                for s in hw.Sensors:
                    if (
                        s.SensorType == self.HW.SensorType.Temperature
                        and "package" in str(s.Name).lower()
                        and s.Value is not None
                    ):
                        return float(s.Value)
        except Exception:
            pass
        return None


# ---------------------------------------------------------------- 天气（Open-Meteo，免密钥）
# 后台线程每 interval_min 分钟刷新一次，主循环每帧把最近一次结果塞进 JSON。
# 这样既不占用 1Hz 串口节奏，也避免对免费接口高频请求被限流。
# 自动定位（auto_location=true）按可达性逐级回退，**优先级 2026-09-15 已调整**：
#   1) pconline（太平洋电脑网，国内）—— 按国内 IP 库给中文省/市，再经 Open-Meteo 地理编码
#      转坐标。名字与坐标同源，是当前首选。
#   2) ipinfo.io/geo —— 仅兜底。英文城市名经本地字典 CITY_ZH 转中文；**字典未收录即放弃**
#      （未收录的地名多为境外错定位，采纳其坐标会让整份天气取错城市）。
#   3) weather_tune.json 写死的城市 —— 同样经 Open-Meteo 地理编码转坐标。
# 三级都失败才用配置文件里的 lat/lon 兜底。
# [为什么把国内源提到第一] 本机出口 IP 被 ipinfo 误判（实测返回过 Tuen Mun/屯门、
#   Taichung/台中）。旧实现「坐标取 ipinfo、中文名回落 pconline」把两个来源拼在一起，
#   产生自相矛盾的定位：屏幕显示「安康」而气温是台中的 32.4°C。修法不是补字典条目，
#   而是让坐标与显示名同源 —— 同源之后，任何一级单独出错都不会再污染天气数据。
# 说明：反向地理编码（按坐标查中文名）在本机网络不可达；Open-Meteo 按英文名反查
#       中文会命中同名小地方（"Xi'an" -> 贵州某"西安"村），故改用本地字典最可靠。
CITY_ZH = {
    "beijing": "北京", "shanghai": "上海", "tianjin": "天津", "chongqing": "重庆",
    "guangzhou": "广州", "shenzhen": "深圳", "dongguan": "东莞", "foshan": "佛山",
    "zhuhai": "珠海", "zhongshan": "中山", "huizhou": "惠州", "shantou": "汕头",
    "hangzhou": "杭州", "ningbo": "宁波", "wenzhou": "温州", "jiaxing": "嘉兴",
    "shaoxing": "绍兴", "jinhua": "金华", "taizhou": "台州", "huzhou": "湖州",
    "nanjing": "南京", "suzhou": "苏州", "wuxi": "无锡", "changzhou": "常州",
    "xuzhou": "徐州", "nantong": "南通", "yangzhou": "扬州", "zhenjiang": "镇江",
    "hefei": "合肥", "wuhu": "芜湖", "fuzhou": "福州", "xiamen": "厦门",
    "quanzhou": "泉州", "nanchang": "南昌", "ganzhou": "赣州",
    "jinan": "济南", "qingdao": "青岛", "yantai": "烟台", "weifang": "潍坊",
    "zibo": "淄博", "linyi": "临沂", "weihai": "威海",
    "zhengzhou": "郑州", "luoyang": "洛阳", "wuhan": "武汉", "yichang": "宜昌",
    "changsha": "长沙", "zhuzhou": "株洲", "hengyang": "衡阳",
    "nanning": "南宁", "guilin": "桂林", "liuzhou": "柳州", "haikou": "海口",
    "sanya": "三亚", "chengdu": "成都", "mianyang": "绵阳", "yibin": "宜宾",
    "guiyang": "贵阳", "zunyi": "遵义", "kunming": "昆明", "dali": "大理",
    "lijiang": "丽江", "lasa": "拉萨", "lhasa": "拉萨",
    "xian": "西安", "lanzhou": "兰州", "xining": "西宁", "yinchuan": "银川",
    "urumqi": "乌鲁木齐", "wulumuqi": "乌鲁木齐", "kashgar": "喀什", "kashi": "喀什",
    "shenyang": "沈阳", "dalian": "大连", "anshan": "鞍山", "changchun": "长春",
    "jilin": "吉林", "harbin": "哈尔滨", "daqing": "大庆", "qiqihar": "齐齐哈尔",
    "shijiazhuang": "石家庄", "tangshan": "唐山", "baoding": "保定",
    "qinhuangdao": "秦皇岛", "zhangjiakou": "张家口",
    "taiyuan": "太原", "datong": "大同", "hohhot": "呼和浩特", "huhehaote": "呼和浩特",
    "baotou": "包头", "ordos": "鄂尔多斯", "eerduosi": "鄂尔多斯",
    "baoji": "宝鸡", "xianyang": "咸阳", "weinan": "渭南", "yulin": "榆林",
    "yanan": "延安", "hanzhong": "汉中", "ankang": "安康",
    "tianshui": "天水", "jiuquan": "酒泉", "jiayuguan": "嘉峪关", "dunhuang": "敦煌",
    "karamay": "克拉玛依", "korla": "库尔勒",
    "hongkong": "香港", "macau": "澳门", "macao": "澳门", "taipei": "台北",
}

# 反查表：中文 -> 拼音。给设备端「中文缺字时回退英文」用。
# [2026-09-16] 不能再把中文原样塞进英文名字段——设备端回退路径用的是 ASCII
# 字库，中文会渲染成方块/乱码（pconline 定位给「安康」时就踩这个坑）。
CITY_EN = {v: k for k, v in CITY_ZH.items()}


class WeatherProvider:
    def __init__(self, tune_file):
        self.tune_file = tune_file
        self.data = None          # 最近一次成功结果
        self.lock = threading.Lock()
        self.interval = 600
        self.stop = False
        self._route = None        # 网络出口：None=未定 / "direct" / "proxy"
        self.load_tune()
        self._load_cache()        # 先垫上上次成功的数据，断网也不至于显示「无数据」

    # ---- 结果落盘缓存 -----------------------------------------------------
    # [2026-09-16] 原来 self.data 只在内存里，monitor 每次被 watcher 重启
    # （开机 / 烧录后拉起）都得重新联网；一旦开局网络不通，屏上就一直
    # 「无数据」。落盘后重启即可先用旧值顶住，等联网成功再刷新。
    def _cache_path(self):
        return os.path.join(HERE, "weather_cache.json")

    def _save_cache(self, w):
        try:
            with open(self._cache_path(), "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "data": w}, f, ensure_ascii=False)
        except Exception as e:
            print(f"[天气] 缓存写入失败（{e}）")

    def _load_cache(self):
        try:
            with open(self._cache_path(), "r", encoding="utf-8") as f:
                j = json.load(f)
            d = j.get("data")
            if isinstance(d, dict) and "wt" in d:
                self.data = d
                age = int((time.time() - float(j.get("ts", 0))) / 60)
                print(f"[天气] 载入缓存（{age} 分钟前）："
                      f"{d.get('wct')} {d.get('wt')}°C")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[天气] 缓存读取失败（{e}）")

    def load_tune(self):
        defaults = {
            "auto_location": True,
            "city": "Beijing",
            "lat": 39.9042,
            "lon": 116.4074,
            "interval_min": 10,
        }
        try:
            with open(self.tune_file, "r", encoding="utf-8") as f:
                v = json.load(f)
            if isinstance(v, dict):
                defaults.update(v)
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"[天气] 调参读取失败（{e}），用默认配置")
        self.tune = defaults
        self.interval = max(1, int(defaults.get("interval_min", 10))) * 60

    # ---- 网络出口策略 ----------------------------------------------------
    # [2026-09-16] 本机实测故障：系统代理（IE 设置）开着并指向 127.0.0.1:7890，
    # 但代理软件没启动、该端口无人监听。Windows 上 urllib.request.getproxies()
    # 会直接读注册表，于是所有天气请求都被发往那个空洞端口，立刻收到
    # WinError 10061「目标计算机积极拒绝」——四个源全挂，屏上长期显示「无数据」。
    # 对策：**直连优先，失败再回落系统代理**，并把本次选中的出口记下来复用。
    # 天气源里 pconline 是国内的、open-meteo 一般也可直连，直连成功就不必受代理影响。
    def _do_open(self, req, timeout, use_proxy):
        if use_proxy:
            return urllib.request.build_opener().open(req, timeout=timeout)
        # ProxyHandler({}) 显式清空代理 → 真正直连，绕开注册表里的失效代理
        return urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        ).open(req, timeout=timeout)

    def _open(self, url, timeout=8):
        """返回可读的响应对象。直连优先、代理兜底；两者都失败则抛最后一个异常。"""
        req = urllib.request.Request(
            url, headers={"User-Agent": "pc-monitor/1.0"}
        )
        if self._route == "proxy":
            order = (True, False)
        else:
            order = (False, True)
        last = None
        for use_proxy in order:
            try:
                r = self._do_open(req, timeout, use_proxy)
                if self._route != ("proxy" if use_proxy else "direct"):
                    self._route = "proxy" if use_proxy else "direct"
                    print(f"[天气] 网络出口：{'系统代理' if use_proxy else '直连'}")
                return r
            except Exception as e:
                last = e
        raise last

    def _http_get(self, url, timeout=8):
        with self._open(url, timeout) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))

    def _http_get_text(self, url, timeout=8):
        """拿原始文本（给返回 JSONP / 非 JSON 的服务用，如 pconline）。"""
        with self._open(url, timeout) as r:
            raw = r.read()
        for enc in ("utf-8", "gbk"):
            try:
                return raw.decode(enc)
            except Exception:
                pass
        return raw.decode("utf-8", "ignore")

    def _geocode(self, city):
        """把城市名经 Open-Meteo 地理编码成 (lat, lon)；失败返回 None。"""
        try:
            q = urllib.parse.quote(city)
            g = self._http_get(
                f"https://geocoding-api.open-meteo.com/v1/search?name={q}&count=1&language=zh"
            )
            res = g.get("results")
            if res:
                r0 = res[0]
                return float(r0["latitude"]), float(r0["longitude"])
        except Exception as e:
            print(f"[天气] 城市「{city}」地理编码失败（{e}）")
        return None

    def _short_city(self, name):
        """去掉末尾的 市/县/区，屏幕更简洁（西安市 -> 西安）。"""
        return re.sub(r"[市县区]$", "", name)

    def _norm(self, s):
        """归一化英文地名做字典查表：去空格/撇号/点，转小写（Xi'an -> xian）。"""
        return re.sub(r"[\s'’.\-]", "", str(s)).lower()

    def _pconline_city(self):
        """国内服务取中文城市名（去掉末尾 市/县/区）；失败返回 None。"""
        try:
            raw = self._http_get_text("https://whois.pconline.com.cn/ipJson.jsp")
            m = re.search(r'"city"\s*:\s*"([^"]+)"', raw)
            if m and m.group(1):
                return self._short_city(m.group(1))
        except Exception:
            pass
        return None

    def locate(self):
        """按可达性逐级回退定位。铁律：**中文城市名与坐标必须来自同一个城市**。"""
        t = self.tune
        if t.get("auto_location", True):
            # 1) 国内源优先：pconline 按国内 IP 库给中文城市名，再经 Open-Meteo 地理编码取坐标。
            #    名字与坐标同源，不会出现「显示 A 城市、取 B 城市天气」。
            # [2026-09-15 修正] 原实现把 ipinfo 放在第一优先，但本机出口 IP 被境外库误判
            # （实测返回过 Tuen Mun/屯门、Taichung/台中），它给出的坐标会把整份天气带偏：
            # 屏幕显示「安康」而气温是台中的 32.4°C（安康同期实测 18.9°C）。故改为国内源优先。
            try:
                cn = self._pconline_city()
                if cn:
                    coord = self._geocode(cn)
                    if coord:
                        # 英文名字段必须是纯 ASCII（见 CITY_EN 注释），查不到拼音给 LOCAL
                        en = (CITY_EN.get(cn) or "local").upper()
                        return coord[0], coord[1], cn[:16], en[:16]
                    print(f"[天气] 国内城市「{cn}」地理编码失败，换 ipinfo")
            except Exception as e:
                print(f"[天气] 国内定位失败（{e}），换 ipinfo")
            # 2) ipinfo.io：仅作兜底，且**要求英文城市名能被本地字典 CITY_ZH 翻译**。
            #    字典收录 = 可信地名；未收录说明极可能是境外错定位，此时宁可不采纳它的
            #    坐标——否则又会回到「名字是 A、坐标是 B」的老问题。
            try:
                j = self._http_get("https://ipinfo.io/geo")
                loc = j.get("loc", "")
                if "," in loc:
                    lat, lon = loc.split(",")
                    en = str(j.get("city") or t.get("city") or "Local")
                    zh = CITY_ZH.get(self._norm(en))
                    if zh:
                        return float(lat), float(lon), zh[:16], en[:16]
                    print(f"[天气] ipinfo 城市「{en}」未收录（疑似境外错定位），改用配置城市")
            except Exception as e:
                print(f"[天气] ipinfo 定位失败（{e}），用配置城市")
        # 3) 回退：weather_tune.json 写死的城市 -> Open-Meteo 地理编码
        city = t.get("city", "Beijing")
        zh = CITY_ZH.get(self._norm(city), city)
        coord = self._geocode(city)
        if coord:
            return coord[0], coord[1], str(zh)[:16], str(city)[:16]
        return float(t["lat"]), float(t["lon"]), str(zh)[:16], str(city)[:16]

    def refresh(self):
        try:
            lat, lon, city, city_en = self.locate()
            url = (
                "https://api.open-meteo.com/v1/forecast"
                f"?latitude={lat:.4f}&longitude={lon:.4f}"
                "&current=temperature_2m,relative_humidity_2m,"
                "apparent_temperature,weather_code,wind_speed_10m"
                "&daily=temperature_2m_max,temperature_2m_min"
                "&timezone=auto"
            )
            j = self._http_get(url)
            c = j.get("current", {})
            d = j.get("daily") or {}
            w = {
                "wt":  round(float(c.get("temperature_2m", 0)), 1),
                "wc":  int(c.get("weather_code", -1)),
                "wf":  round(float(c.get("apparent_temperature", 0)), 1),
                "wh":  int(c.get("relative_humidity_2m", -1)),
                "ww":  round(float(c.get("wind_speed_10m", 0)), 1),
                "whi": round(float((d.get("temperature_2m_max") or [0])[0]), 0),
                "wlo": round(float((d.get("temperature_2m_min") or [0])[0]), 0),
                "wct": (city or "Local")[:16],       # 中文城市名（优先显示）
                "wce": (city_en or "Local")[:16],    # 英文城市名（字库缺失时回退）
            }
            with self.lock:
                self.data = w
            self._save_cache(w)
            print(f"[天气] {city}({city_en}) {w['wt']}°C code={w['wc']} H{w['whi']}/L{w['wlo']}")
            return True
        except Exception as e:
            print(f"[天气] 获取失败（{e}），沿用上次数据")
            return False

    def snapshot(self):
        with self.lock:
            return dict(self.data) if self.data else None

    def run(self):
        self.refresh()           # 启动即取一次，先有数据
        delay = self.interval
        fail_n = 0
        while not self.stop:
            time.sleep(delay)
            if self.stop:
                break
            if self.refresh():
                fail_n = 0
                delay = self.interval
            else:
                # [2026-09-16] 原来失败也要死等 10 分钟。开机时网络（网卡/代理）
                # 往往还没就绪，一等就是十分钟没数据。改为指数退避，最快 30s 重试。
                fail_n += 1
                delay = min(30 * (2 ** (fail_n - 1)), 300)
                print(f"[天气] {delay}s 后重试（连续失败 {fail_n} 次）")

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()


# ---------------------------------------------------------------- 采集
def pick_disk(want="C:/"):
    """优先返回指定盘符；拿不到就退回第一个可用分区，全失败返回 None"""
    try:
        du = psutil.disk_usage(want)
        return du
    except Exception:
        pass
    for part in psutil.disk_partitions():
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            return psutil.disk_usage(part.mountpoint)
        except Exception:
            continue
    return None


def human_uptime():
    sec = int(time.time() - psutil.boot_time())
    h, rem = divmod(sec, 3600)
    m = rem // 60
    if h >= 100:
        return f"{h}h"
    if h:
        return f"{h}h{m:02d}m"
    return f"{m}m"


# ------------------------------------------------------- 时钟页调参（热重载）
# 数字在卡片内的垂直偏移由 PC 端下发，改 clock_tune.json 里 digit_offset 即可实时生效，
# 无需重烧固件。打包成 exe 后从 sys.executable 所在目录读取 json，源码运行时从 __file__ 目录读。
TUNE_FILE = os.path.join(
    os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__)),
    "clock_tune.json",
)
DEFAULT_TUNE = {"digit_offset": 0, "digit_stretch": 170}  # 偏移正=上移；拉伸 %=数字拉高倍率（100=原样），宽度不变


def load_tune():
    """读取调参文件；缺失/损坏时回落到默认值。"""
    try:
        with open(TUNE_FILE, "r", encoding="utf-8") as f:
            v = json.load(f)
        if not isinstance(v, dict):
            raise ValueError("tune 不是对象")
        out = dict(DEFAULT_TUNE)
        out.update(v)
        return out
    except FileNotFoundError:
        return dict(DEFAULT_TUNE)
    except Exception as e:
        print(f"[调参] {TUNE_FILE} 读取失败（{e}），用默认值 {DEFAULT_TUNE}")
        return dict(DEFAULT_TUNE)


def collect(gpu, ctemp, net, disk_want="C:/", tune=None, wp=None):
    up, dn = net.sample()
    mem = psutil.virtual_memory()
    du = pick_disk(disk_want)
    g_util, g_temp = gpu.read()
    t = ctemp.read()
    now = datetime.now()
    tune = tune or DEFAULT_TUNE

    data = {
        "c": int(psutil.cpu_percent(interval=None)),
        "m": int(mem.percent),
        "mf": round(mem.used / (1024 ** 3), 1),
        "t": int(t) if t is not None else -999,
        "g": g_util if g_util is not None else -1,
        "gt": g_temp if g_temp is not None else -999,
        "u": round(up, 1),
        "d": round(dn, 1),
        "dk": int(du.percent) if du else -1,
        "df": round(du.free / (1024 ** 3), 0) if du else -1,
        "tm": now.strftime("%H:%M"),
        "dt": now.strftime("%m-%d"),
        "up": human_uptime(),
        "yr": now.year,
        "mo": now.month,
        "dy": now.day,
        "ss": now.second,
        "do": int(tune.get("digit_offset", DEFAULT_TUNE["digit_offset"])),
        "ds": int(tune.get("digit_stretch", DEFAULT_TUNE["digit_stretch"])),
    }

    # 天气页：把后台线程最近一次结果并入本帧（字段缺失时设备端显示 "NO DATA"）
    if wp is not None:
        w = wp.snapshot()
        if w:
            data.update(w)

    return data


# ---------------------------------------------------------------- 单实例保护
# 用本地固定端口做互斥锁：进程退出时 socket 由系统回收，不会像锁文件那样留下残留。
# （早先用 psutil 扫进程判断，pythonw 下会把启动中的自己误判成已有实例，不可靠）
LOCK_PORT = 47651


def acquire_lock():
    """抢到锁返回持有中的 socket（调用方必须一直持有到进程结束）；
    已有实例在跑则返回 None。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", LOCK_PORT))
        return s
    except OSError:
        try:
            s.close()
        except Exception:
            pass
        return None


# ---------------------------------------------------------------- 主循环
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="手动指定串口，如 COM3")
    ap.add_argument("--list", action="store_true", help="列出串口后退出")
    ap.add_argument("--temp", action="store_true", help="启用 CPU 温度（需管理员）")
    ap.add_argument("--interval", type=float, default=1.0, help="采样间隔，默认 1 秒")
    ap.add_argument("--disk", default="C:/", help="要监控的盘符，默认 C:/")
    ap.add_argument("--dry-run", action="store_true", help="只打印 JSON 不写串口，用于调试")
    ap.add_argument("--no-weather", action="store_true", help="关闭天气获取（不请求网络）")
    args = ap.parse_args()

    if args.list:
        for p in list_ports():
            print(f"{p.device}  {p.description}  VID:{p.vid:04X} PID:{p.pid:04X}"
                  if p.vid else f"{p.device}  {p.description}")
        return

    # 单实例：已有实例在跑就直接退出，避免多实例抢同一个串口。
    # lock 必须一直持有到进程结束，否则锁会提前释放。
    lock = acquire_lock()
    if lock is None:
        print("已有 monitor.py 实例在运行，本次启动退出")
        return

    port = args.port or find_ch340()
    if not port and not args.dry_run:
        # 开机自启时 USB 往往比 Windows 登录慢半拍，此时 CH340 还没枚举出来。
        # 这里绝不能直接退出——退了就再也不会重试，屏就永远停在 PC MONITOR。
        print("[串口] 未发现 CH340，持续等待设备就绪…")
        while not port:
            time.sleep(2)
            port = find_ch340()
        print(f"[串口] 发现 {port}")

    gpu = GPU()
    ctemp = CpuTemp(args.temp)
    net = NetRate()
    psutil.cpu_percent(interval=None)  # 预热，之后每次调用返回上一周期均值

    # 天气提供者（后台线程定时刷新）。--no-weather 时直接置空，本帧不含天气字段。
    wp = None
    if not args.no_weather:
        try:
            wtf = os.path.join(HERE, "weather_tune.json")
            wp = WeatherProvider(wtf)
            wp.start()
            print(f"[天气] 已启动（每 {wp.interval // 60} 分钟刷新，改 {os.path.basename(wtf)} 重启生效）")
        except Exception as e:
            print(f"[天气] 初始化失败（{e}），本会话不发送天气")
            wp = None

    ser = None
    fail = 0
    tune = load_tune()
    tune_mtime = os.path.getmtime(TUNE_FILE) if os.path.exists(TUNE_FILE) else 0
    print(f"[调参] digit_offset={tune['digit_offset']}（改 {os.path.basename(TUNE_FILE)} 实时生效）")
    print(f"[启动] 目标 {port or '(dry-run)'}，按 Ctrl+C 退出")
    while True:
        # 调参文件热重载：改完 json 下一帧就下发新值，屏幕立刻跟着变
        try:
            mt = os.path.getmtime(TUNE_FILE) if os.path.exists(TUNE_FILE) else 0
            if mt != tune_mtime:
                tune_mtime = mt
                tune = load_tune()
                print(f"[调参] 已重载：digit_offset={tune['digit_offset']}")
        except Exception:
            pass
        if not args.dry_run and (ser is None or not ser.is_open):
            ser = open_port(port)
            if ser is None:
                fail += 1
                time.sleep(2)
                # 连续失败就重扫：ESP32 拔插后 COM 号经常会变，死守旧号永远连不上
                if fail >= 3 and not args.port:
                    fail = 0
                    found = find_ch340()
                    if found and found != port:
                        print(f"[串口] 改扫到 {found}")
                        port = found
                continue
            fail = 0
        try:
            data = collect(gpu, ctemp, net, args.disk, tune, wp)
            line = json.dumps(data, separators=(",", ":")) + "\n"
            if args.dry_run:
                print(line, end="")
            else:
                ser.write(line.encode("ascii", "ignore"))
        except (serial.SerialException, OSError) as e:
            print(f"[串口] 断开（{e}），2 秒后重连")
            try:
                ser.close()
            except Exception:
                pass
            ser = None
            time.sleep(2)
            continue
        except KeyboardInterrupt:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[退出]")
    except SystemExit as e:
        # 任何 sys.exit 都要留痕，否则 pythonw 下静默消失，事后无从查起
        print("[退出] %s" % (e.code if e.code else ""))
    except Exception:
        import traceback
        print("[崩溃]\n" + traceback.format_exc())
