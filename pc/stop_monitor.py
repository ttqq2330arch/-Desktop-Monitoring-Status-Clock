# 停止 PC 监控采集（烧录 ESP32 固件前必做）
#
# 为什么必须停：脚本独占 COM6，不停掉 PlatformIO 抢不到串口，烧录必然失败。
#
# 怎么停才停得住：现在有 USB 看门狗盯着，光杀进程没用——它几秒内就会把脚本拉回来。
# 所以先创建 pause.flag，看门狗见到这个文件就不再拉起，然后才杀进程。
#
# 用法
#   python stop_monitor.py
#
# 恢复：双击 start_monitor.bat（删掉 pause.flag，看门狗几秒内自动把采集拉起来）
import os
import time

import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
PAUSE_FLAG = os.path.join(HERE, "pause.flag")


def _still(p):
    try:
        return p.is_running()
    except Exception:
        return False


def main():
    # 1. 先让看门狗让路，否则杀了也会被拉回来
    try:
        with open(PAUSE_FLAG, "w", encoding="utf-8") as f:
            f.write("烧录中，看门狗暂停拉起。完成后运行 start_monitor.bat 恢复。\n")
        print("已创建 pause.flag，看门狗暂停拉起")
    except Exception as e:
        print("创建 pause.flag 失败：%s（看门狗可能把脚本拉回来）" % e)

    # 2. 再杀采集进程
    me = os.getpid()
    targets = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if "python" not in (p.name() or "").lower():
                continue
            if p.pid == me:
                continue
            cl = p.cmdline() or []
            if not any(str(a).endswith("monitor.py") for a in cl):
                continue
            targets.append(p)
        except Exception:
            continue

    if not targets:
        print("没有运行中的 monitor.py")
    else:
        for p in targets:
            try:
                p.terminate()
                print("已请求结束 %s (%s)" % (p.pid, p.name()))
            except Exception as e:
                print("结束失败 %s: %s" % (p.pid, e))

        time.sleep(2)

        for p in targets:
            try:
                if p.is_running():
                    p.kill()
                    print("强制结束 %s" % p.pid)
            except Exception:
                pass

        time.sleep(1)
        alive = [p.pid for p in targets if _still(p)]
        print("完成。仍存活：%s" % (alive if alive else "无"))

    print("烧录完成后双击 start_monitor.bat 恢复推送。")


if __name__ == "__main__":
    main()
