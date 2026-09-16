# 第三方资源与许可

本仓库**只收录自己写的代码与生成结果**，第三方库、商业字体、打包产物均不入库。
下面逐项说明每一项的来源、许可与处置方式。

---

## 1. 固件依赖（由 PlatformIO 自动下载，仓库不含源码）

| 组件 | 版本 | 许可 | 说明 |
|---|---|---|---|
| [LovyanGFX](https://github.com/lovyan03/LovyanGFX) | `^1.2.0` | **FreeBSD** | LCD 驱动与精灵缓冲。库内还打包了若干子组件，各有独立许可（TJpgDec / Pngle MIT / GFX font 2-clause BSD / IPA font 等），详见上游仓库的 License 段落 |
| [ArduinoJson](https://github.com/bblanchon/ArduinoJson) | `^7.1.0` | **MIT** | 串口 JSON 解析 |
| [espressif32 platform](https://github.com/platformio/platform-espressif32) | `6.12.0` | Apache-2.0 | PlatformIO 平台定义 |
| Arduino core for ESP32 / ESP-IDF | 随平台 | Apache-2.0 / LGPL-2.1 | 由上面的平台自动拉取 |

原开发机上这些库曾放在 `esp32/lib/`（共约 130 MB）离线编译。
开源版已在 `platformio.ini` 里改用 `lib_deps`，首次 `pio run` 时自动下载，**仓库不需要也不应该包含 `lib/`**。

---

## 2. 字体

### 2.1 随仓库分发（SIL Open Font License 1.1）

翻页时钟的数字掩码由 `esp32/tools/gen_clock_font.py` 离线烘焙而来。
其中三套字体是 Google Fonts 发布的 OFL 字体，**随仓库提供**，许可全文见 `licenses/`：

| 文件 | 版权行 | 许可全文 |
|---|---|---|
| `esp32/tools/fonts/Fredoka_wdth_wght.ttf` | Copyright 2016 The Fredoka Project Authors | `licenses/OFL-Fredoka.txt` |
| `esp32/tools/fonts/Nunito_wght.ttf` | Copyright 2014 The Nunito Project Authors | `licenses/OFL-Nunito.txt` |
| `esp32/tools/fonts/Poppins-Bold.ttf` | Copyright 2020 The Poppins Project Authors | `licenses/OFL-Poppins.txt` |

这三套字体另有 6 个同批次的选型候选字体（Asap / Baloo 2 / Comfortaa / Quicksand /
Varela Round / M PLUS Rounded 1c）在选型阶段被淘汰，**未收录**，以控制仓库体积。

### 2.2 不随仓库分发（专有 / 商业授权）

| 字体 | 用在哪 | 为什么不收录 |
|---|---|---|
| **Trebuchet MS**（`C:/Windows/Fonts/trebucbd.ttf`） | 时钟第 4 套数字 | Microsoft 随 Windows 分发的商业字体，**无再分发授权**。脚本从本机系统字体读取，因此仓库不含该文件 |
| **SimHei 中易黑体** | 生成 16×16 中文点阵字模（`src/cn_font.h` / `weather_cn.h` / `cn_city.h`） | 同样是 Microsoft 专有字体。仓库收录的是**从字体渲染出的位图数组**，不含字体文件本体 |

`gen_clock_font.py` 已做容错：**字体文件不存在时自动跳过并打印提示**，
所以在没有 Trebuchet MS 的机器（或 Linux / macOS）上重新生成仍是可用的，只是少一套字形。

想要凑齐 4 套：把你系统里对应的字体放到 `esp32/tools/fonts/` 并改 `FONTS` 表的路径即可。

---

## 3. 视觉风格参考：《我的世界》

总览页（`src/mc_theme.h`）的配色、立体边框、经验条等**取自《我的世界》(Minecraft)** 的
GUI 设计语言，属于风格致敬：

- 本仓库**不包含**任何 Mojang / Microsoft 的美术资源文件（无贴图、无音效、无字体）。
- 所有图标都是在代码里用矩形与像素点**重新画**出来的（见 `tools/mc_ui_preview.py`）。
- 本项目与 Mojang Studios / Microsoft **无任何关联**，未获其赞助或认可。
- "Minecraft" 是 Mojang Synergies AB 的商标。

若你要把这个项目用于商业用途，建议把总览页换成中性配色（`main.cpp` 里的 `MC_*` 常量集中可改），
以规避商标与外观风格方面的争议。

---

## 4. 未收录的运行时产物

为了保持仓库干净，下列内容一律不入库（已写入 `.gitignore`）：

| 内容 | 原因 |
|---|---|
| `esp32/.pio/` | PlatformIO 编译缓存（170 MB+），本地可重建 |
| `esp32/lib/` | 第三方库源码，改由 `lib_deps` 拉取 |
| `pc/dist/` | PyInstaller 便携版产物（3 个 exe，30 MB+），可用 `pc/build_portable.py` 重新打包 |
| `*.log` / `build_log.txt` / `probe_log.txt` | 运行与调试日志 |
| `pc/weather_tune.json` | 本机运行配置，仓库给的是 `weather_tune.example.json` |
| `esp32/src/clock_font.h` | 单字体时代的残留文件，固件已改用 `clock_fonts.h` |
| `esp32/tools/*.png` | 设计稿生成器的中间产物；精选图另存于 `docs/img/` |
