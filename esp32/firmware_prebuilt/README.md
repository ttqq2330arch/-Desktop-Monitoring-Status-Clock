# 预编译固件（免编译直烧）

与仓库源码同版本构建的固件四件套，不想搭 PlatformIO 环境可直接用 esptool 烧录：

```bash
python -m esptool --chip esp32 --port COM5 --baud 921600 \
  --before default_reset --after hard_reset write_flash -z \
  --flash_mode dio --flash_freq 40m --flash_size 4MB \
  0x1000 bootloader.bin 0x8000 partitions.bin 0xe000 boot_app0.bin 0x10000 firmware.bin
```

注意：本固件使用仓库自带的**自定义 3MB app 分区表**（`esp32/partitions.csv`），
必须连 `partitions.bin` 一起烧，单烧 app 会因分区不一致而异常。

| 文件 | 烧写偏移 | 字节 | md5 |
|---|---|---|---|
| `bootloader.bin` | 0x1000 | 17536 | `70c9a76fcbc41d62b871521885c08342` |
| `partitions.bin` | 0x8000 | 3072 | `aa5fc164aaabbe6bb8a19f52e2752cf3` |
| `boot_app0.bin` | 0xe000 | 8192 | `e6327541e2dc394ca2c3b3280ac0f39f` |
| `firmware.bin` | 0x10000 | 1207312 | `abfb0fd7f7e43f818e2e0e7a7c01a684` |

串口号以设备管理器为准（CH340）；请先停掉 PC 采集端再烧（`pc/stop_monitor.py`）。
说明：固件内嵌的调试串包含构建机路径（Administrator 为 Windows 默认账户名，非机密），
由 ESP-IDF 头文件的 assert 宏引入，不影响功能与安全。
