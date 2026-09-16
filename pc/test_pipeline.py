# -*- coding: utf-8 -*-
"""主机侧跑通测试：PC 采集 -> 固件解析 -> 三页内容生成。
不依赖真机，验证数据协议、日历算法、页面逻辑都能跑通不报错。
"""
import os, sys, json, traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import monitor as M

# ---------- 1) 真跑 PC 采集 -------------------------------------------------
def build_objects():
    gpu, ctemp, net = None, None, None
    try:
        gpu = M.GPU()
    except Exception as e:
        print(f"[warn] GPU() 构造失败，用桩代替: {e}")
        class _G:
            def read(self): return (None, None)
        gpu = _G()
    try:
        ctemp = M.CpuTemp(False)
    except Exception as e:
        print(f"[warn] CpuTemp() 构造失败，用桩代替: {e}")
        class _C:
            def read(self): return None
        ctemp = _C()
    try:
        net = M.NetRate()
    except Exception as e:
        print(f"[warn] NetRate() 构造失败，用桩代替: {e}")
        class _N:
            def sample(self): return (0.0, 0.0)
        net = _N()
    return gpu, ctemp, net

print("=== STEP 1: monitor.collect() 真实采集 ===")
gpu, ctemp, net = build_objects()
try:
    pkt = M.collect(gpu, ctemp, net, "C:/")
except Exception:
    traceback.print_exc()
    sys.exit(1)
print("原始 JSON 包:")
print(json.dumps(pkt, ensure_ascii=False, indent=2))

# ---------- 2) 镜像固件 handleLine 解析 ------------------------------------
print("\n=== STEP 2: 镜像固件解析 (handleLine) ===")
def get(d, k, default):
    v = d.get(k, default)
    return default if v is None else v

st = {
    "cpu": get(pkt,"c",-1), "mem": get(pkt,"m",-1), "memGB": get(pkt,"mf",-1.0),
    "cpuT": get(pkt,"t",-999), "gpu": get(pkt,"g",-1), "gpuT": get(pkt,"gt",-999),
    "upKB": get(pkt,"u",-1.0), "dnKB": get(pkt,"d",-1.0),
    "disk": get(pkt,"dk",-1), "dskFreeGB": get(pkt,"df",-1.0),
    "time": str(get(pkt,"tm","--:--")), "date": str(get(pkt,"dt","")),
    "uptime": str(get(pkt,"up","")),
    "year": get(pkt,"yr",0), "month": get(pkt,"mo",0), "day": get(pkt,"dy",0),
    "sec": get(pkt,"ss",0),
}
print(f"解析结果: cpu={st['cpu']}% mem={st['mem']}% gpu={st['gpu']} "
      f"dn={st['dnKB']} up={st['upKB']} disk={st['disk']}% "
      f"date={st['year']}-{st['month']:02d}-{st['day']:02d} time={st['time']}")

# ---------- 3) 镜像固件工具函数 --------------------------------------------
def fmtRate(kb):
    if kb < 0: return "--"
    if kb >= 1024: return "%.1fM" % (kb/1024.0)
    return "%.0fK" % kb
def dispTemp(c):  # gUnitF 默认 false -> 返回 C
    return c
def dayOfWeek(y,m,d):
    t=[0,3,2,5,0,3,5,1,4,6,2,4]
    if m<3: y-=1
    return (y + y//4 - y//100 + y//400 + t[m-1] + d) % 7
def daysInMonth(y,m):
    d=[31,28,31,30,31,30,31,31,30,31,30,31]
    if m==2 and ((y%4==0 and y%100!=0) or y%400==0): return 29
    return d[m-1] if 1<=m<=12 else 30
WK=["SUN","MON","TUE","WED","THU","FRI","SAT"]

# ---------- 4) 生成三页内容（与固件 drawXxx 一致）-------------------------
print("\n=== STEP 3: 三页屏幕内容（与固件渲染一致）===")

# 第1页 总览
print("\n--- 第1页 总览 (OVERVIEW) ---")
rows = [
    ("CPU", f"{max(st['cpu'],0)}%",  f"{dispTemp(st['cpuT'] if st['cpuT']>-900 else 0)}C"),
    ("RAM", f"{max(st['mem'],0)}%",  f"{st['memGB']:.1f}G"),
    ("NET", f"v{fmtRate(st['dnKB'])}", f"^{fmtRate(st['upKB'])}"),
    ("GPU", f"{max(st['gpu'],0)}%",  f"{dispTemp(st['gpuT'] if st['gpuT']>-900 else 0)}C"),
    ("DSK", f"{max(st['disk'],0)}%",  f"{st['dskFreeGB']:.0f}G"),
]
for label, val, aux in rows:
    print(f"  [{label:3}] {val:>8}   {aux}")

# 第2页 大时钟
print("\n--- 第2页 大时钟 (CLOCK) ---")
hh = st['time'][:2]; mm = st['time'][3:5]
print(f"  时间: {hh}:{mm}   (冒号每0.5s闪烁)")
dstr = f"{st['year']:04d}-{st['month']:02d}-{st['day']:02d}" if st['year'] else (st['date'] or "--")
print(f"  日期: {dstr}")
if st['year']:
    print(f"  星期: {WK[dayOfWeek(st['year'], st['month'], st['day'])]}")
print(f"  秒弧: {st['sec']}/60")

# 第3页 整面日历
print("\n--- 第3页 整面日历 (CALENDAR) ---")
MON=["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
print(f"  标题: {MON[st['month']-1]} {st['year']}")
print("  表头: " + " ".join(f"{w[0]}" for w in WK))  # M T W T F S S
fd = (dayOfWeek(st['year'], st['month'], 1) + 6) % 7  # 周一为首列
total = daysInMonth(st['year'], st['month'])
grid = ["  "] * fd + [f"{d:2}" for d in range(1, total+1)]
for r in range(0, max(42, len(grid)), 7):
    line = grid[r:r+7]
    print("  " + " ".join(f"{c:>2}" for c in line))
print(f"  今天高亮: {st['day']} (强调色实心圆)")

# ---------- 5) 健全性检查 --------------------------------------------------
print("\n=== STEP 4: 健全性检查 ===")
errs=[]
if st['cpu']<-1 or st['cpu']>100: errs.append("cpu 超范围")
if st['mem']<-1 or st['mem']>100: errs.append("mem 超范围")
if st['year']==0: errs.append("year 缺失 -> 日历无法显示")
if not (0<=st['sec']<=59): errs.append("sec 超范围")
# 星期交叉验证：用 Python 标准库
import datetime
py_wd = datetime.date(st['year'], st['month'], st['day']).strftime("%a").upper()
if st['year'] and WK[dayOfWeek(st['year'],st['month'],st['day'])] != py_wd:
    errs.append(f"weekday 算法与标准库不符: fw={WK[dayOfWeek(st['year'],st['month'],st['day'])]} py={py_wd}")
if errs:
    print("发现异常:")
    for e in errs: print("  -", e)
else:
    print("  ✓ 全部通过：字段范围正常、year 有效、weekday 算法与标准库一致")
print("\n跑通测试结束。")
