# PlatformIO 构建钩子：去掉链接阶段的 -Wl,-Map=<file>
#
# 原因：工程路径含中文时，xtensa-esp32-elf-ld 在 Windows 上
# 无法创建非 ASCII 路径的 map 文件，链接会报
#   "cannot open map file ...: No such file or directory"
# map 文件只是链接器输出的符号地址表，烧录用不到，去掉不影响固件。
#
# 根治办法是把工程搬到纯 ASCII 路径（如 F:\pc-monitor），那时可删除本文件。

Import("env")

_map_flags = ("-Map", ".map")


def _drop(flag):
    if not isinstance(flag, str):
        return False
    return any(k in flag for k in _map_flags)


env["LINKFLAGS"] = [f for f in env["LINKFLAGS"] if not _drop(f)]
