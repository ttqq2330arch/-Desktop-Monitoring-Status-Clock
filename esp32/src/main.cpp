/* ============================================================================
   桌面电脑状态监控 · 显示端固件
   ESP32-WROOM-32 DevKit V1 (CH340C) + ST7735S 128x160 横放 = 逻辑 160x128
   数据由 PC 端 monitor.py 经 USB 串口（UART0）以 JSON 行推送，本固件只负责显示

   接线（ST7735S 模块 -> ESP32）
     VCC -> 3.3V      GND -> GND
     SCL/SCK -> 18    SDA/MOSI -> 23
     CS -> 5          DC/A0 -> 17      RES/RST -> 16
     BLK -> 4（改 PWM 调光，见亮度设置）
     MISO 不接

   轻触开关（2脚/4脚通用：一端接 GPIO，另一端接 GND；INPUT_PULLUP，按下读 LOW）
     BTN  -> 13   （唯一按键：每按一下切下一页，总览→时钟→日历循环，带幕布过渡）

   屏幕不对先改下面「屏幕微调」那五个常量，别动别的地方
   ============================================================================ */

#define LGFX_USE_V1
#include <LovyanGFX.hpp>
#include <ArduinoJson.h>
#include <math.h>
#include <string.h>    // memset（时钟页 alpha 掩码清零）
#include "cn_font.h"   // 16x16 中文点阵字模（年月一~十，黑体生成）

// ============================== 屏幕微调 ====================================
#define PIN_SCK   18
#define PIN_MOSI  23
#define PIN_MISO  19
#define PIN_CS     5
#define PIN_DC    17
#define PIN_RST   16
#define PIN_BLK    4

// 轻触开关：另一端接 GND，启用内部上拉，按下读 LOW
// 注意：避开 ESP32 strapping pin（0/2/5/12/15）、flash 占用（6-11）、
//      已用 SPI/背光/控制脚（4=BLK / 5=CS / 16=RST / 17=DC / 18=SCK / 23=MOSI）。
// 单按键循环切页：每按一下切到下一页（总览→时钟→日历→总览…），去抖 25ms。
// 历史包袱：OK 曾用 15（strapping）不行，改 4 又撞 BLK，最终单键定在 GPIO13。
#define PIN_BTN       13            // 唯一按键，按下=切下一页

// offset 与 memory_width/height 共同决定 CASET/RASET 的起始地址（见 Panel_LCD::setRotation）。
// 出厂几何 = 130/162 + 偏移 (0,0) → rot1 的 (colstart, rowstart) = (0, mw-pw-ox) = (0, 2)，
// 即 128 行落在 GRAM 行 [2,129]。这组值从项目第一天跑到现在，画面从未错位，别动。
#define OFFSET_X    0     // 有白边/画面偏移：调这个
#define OFFSET_Y    0     // 和这个
#define RGB_ORDER   false // 红蓝反了：改 true
#define INVERT_COL  false // 整屏发黑或发白：改 true
#define SPI_FREQ    20000000  // 花屏就降到 10000000

// ---- 安装方向（外壳装反时改这里，不用拆机）--------------------------------
// 外壳把屏幕装成了 180° 倒装，需要把整屏内容也转 180°。
//
// ★为什么不直接用 lcd.setRotation(3)（两组参数都实测失败，别再回头走这条路）：
//   本屏 GRAM 是 132x162、可视 128x160，属非标准几何，180° 要靠库对地址窗口取镜像实现。
//   实测两组参数的 rot3 窗口（代入 Panel_LCD::setRotation 公式）：
//     130/162 + (0,0) → rot3 = (2, 0)，与 rot1 的 (0, 2) 不同 → 画面沿对角线错位（"斜屏"）
//     132/160 + (2,0) → rot3 = (0, 2)，与 rot1 完全相同 → 不斜了，但屏幕最上方出现一条横向乱码
//   第二组的结果说明：即使把窗口调成与 rot1 数值相同，这块屏的 MADCTL/GRAM 对应关系
//   依然无法靠库的 rotation 3 对齐。再试第三组参数是赌，不是解 —— 停在这里。
//
// ★本版改用：软件像素级 180° 翻转
//   rotation 恒为 1（完全沿用已验证正确的显示通路），在每帧绘制完成后把 sprite 缓冲
//   整体翻转 180°（行序倒置 + 行内像素倒置）再推送。
//   它不触碰任何地址窗口 / MADCTL，所以「斜屏、错位、乱码」这类地址类故障在原理上
//   不可能发生 —— 屏幕的物理行为与翻转前逐行一致。
//   代价仅为每帧一次 40KB 的内存搬运（10240 次 16bit 交换），1Hz 刷新下可忽略。
#define PANEL_FLIP_180  1   // 1 = 外壳倒装（软件翻转 180°）；0 = 正常方向
#define PANEL_ROT       1   // 固定横屏。180° 由 flipBuf180() 在像素层完成，不走 setRotation

// ============================== 网格常量 ====================================
#define SCR_W 160
#define SCR_H 128
#define HEAD_H    17      // 顶栏高度（时钟页 / 天气页仍在用）
// ★防撕裂边距（本屏的唯一硬约束，改布局前先读这段）：
//   翻转后「逻辑 y 小」= 物理顶边（SPI 推屏写入的起点，与面板扫描重叠最重）；
//   反过来「逻辑 y 大」= 物理底边。两种方向都可能撕裂，所以逻辑两端都要留纯背景带。
//   纯背景行每帧逐像素相同 → 撕裂时新旧帧一致 → 肉眼不可见。
//   若把「每秒变化的动态内容」（时钟/日期/数值）压进这两条带，撕裂立刻变成可见闪烁。
//   ⚠️ 不要再靠「把邻行复制进端点行」来兜底：邻行若含动态内容，等于把动态内容搬进撕裂带。
#define EDGE_TOP   3       // 逻辑顶部纯背景带行数（y=0..2）
#define EDGE_BOT   4       // 逻辑底部纯背景带行数（y=124..127）
#define BODY_TOP   19      // 指标行起始（逻辑 y）：上方 3~18 为「时钟带 + 凹槽分隔线」
#define ROW_H      21      // 指标行高：5 行 × 21 = 105 → 19..123，末行内容收在 y=123

// ============================== 配色（极简 · 单强调色） ======================
static constexpr uint16_t RGB(uint8_t r, uint8_t g, uint8_t b) {
  return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3);
}
static constexpr uint16_t swap16(uint16_t v) {
  return (uint16_t)(((v >> 8) & 0xFF) | ((v & 0xFF) << 8));
}
static const uint16_t C_BG    = RGB(0x0E, 0x0E, 0x13);  // 近黑底（TFT 背光省电）
static const uint16_t C_HEAD  = RGB(0x16, 0x16, 0x1E);  // 顶栏（极淡）
static const uint16_t C_LINE  = RGB(0x2A, 0x2A, 0x34);  // 发丝分隔线
static const uint16_t C_TXT   = RGB(0xEE, 0xEE, 0xF2);  // 主文字（近白）
static const uint16_t C_DIM   = RGB(0x73, 0x73, 0x82);  // 次要 / 注释（灰）
static const uint16_t C_ACC   = RGB(0x4D, 0xD0, 0xC4);  // 唯一强调色（清新青绿）
static const uint16_t C_WARN  = RGB(0xEF, 0x9F, 0x27);  // 负载偏高（≥60%）
static const uint16_t C_HOT   = RGB(0xE5, 0x4A, 0x4A);  // 高负载（≥85%）转红
static const uint16_t C_SEL   = C_ACC;                  // 选中高亮 = 强调色

// 总览页各指标基色（克制、低饱和；仅在高负载时整体转 WARN/HOT）
static const uint16_t MC_CPU  = RGB(0x4D, 0xD0, 0xC4);  // 青绿
static const uint16_t MC_RAM  = RGB(0xE0, 0xA0, 0x60);  // 暖橙
static const uint16_t MC_NET  = RGB(0x5A, 0xA0, 0xF0);  // 蓝
static const uint16_t MC_GPU  = RGB(0xB0, 0x80, 0xE0);  // 紫
static const uint16_t MC_DSK  = RGB(0x6C, 0xD0, 0x80);  // 绿

// 负载阈值着色：>=85% 红，>=60% 橙，否则用指标基色
static uint16_t loadColor(int pct, uint16_t base) {
  if (pct < 0)   return base;
  if (pct >= 85) return C_HOT;
  if (pct >= 60) return C_WARN;
  return base;
}

// ============================== LGFX 设备 ===================================
// 自检轮播用的候选几何配置表：[memW, memH, panelW, panelH, offX, offY, rotation]
// ST7735S 128x160 斜屏几乎都出在这几个参数的组合上，轮播让用户直接指认哪组不斜
static const int CFG_N = 9;
static const int CFG_TAB[CFG_N][7] = {
  {132,162,128,160,2,1,1},
  {132,162,128,160,0,0,1},
  {132,162,128,160,0,3,1},
  {132,162,128,160,2,3,1},
  {132,162,128,160,1,2,1},
  {130,162,128,160,0,0,1},   // 5 = 出厂几何 rot1（与 LGFX 构造函数当前值一致）
  {132,160,128,160,0,0,1},   // 6
  {132,160,128,160,2,0,3},   // 7 = 出厂几何 rot3（与第 5 项配对：两者都应不斜才算正确）
  {132,162,128,160,2,1,0},
};
static int gCfg = 0;
static int gW = 160, gH = 128;

class LGFX : public lgfx::LGFX_Device {
  lgfx::Panel_ST7735S _panel;
  lgfx::Bus_SPI       _bus;

public:
  LGFX() {
    {
      auto cfg = _bus.config();
      cfg.spi_host   = VSPI_HOST;
      cfg.spi_mode   = 0;
      cfg.freq_write = SPI_FREQ;
      cfg.freq_read  = 8000000;
      cfg.spi_3wire  = false;
      cfg.use_lock   = true;
      cfg.dma_channel = 1;
      cfg.pin_sclk = PIN_SCK;
      cfg.pin_mosi = PIN_MOSI;
      cfg.pin_miso = PIN_MISO;
      cfg.pin_dc   = PIN_DC;
      _bus.config(cfg);
      _panel.setBus(&_bus);
    }
    {
      auto cfg = _panel.config();
      cfg.pin_cs    = PIN_CS;
      cfg.pin_rst   = PIN_RST;
      cfg.pin_busy  = -1;
      cfg.panel_width  = 128;
      cfg.panel_height = 160;
      cfg.memory_width  = 130;   // 配 OFFSET_X=0 → rot1 的 rowstart = 130-128-0 = 2（长期验证值）
      cfg.memory_height = 162;   // 出厂值；rotation 恒为 1，180° 由 flipBuf180() 完成
      cfg.offset_x     = OFFSET_X;
      cfg.offset_y     = OFFSET_Y;
      cfg.offset_rotation = 0;
      cfg.readable = false;
      cfg.invert   = INVERT_COL;
      cfg.rgb_order = RGB_ORDER;
      cfg.dlen_16bit = false;
      cfg.bus_shared = false;
      _panel.config(cfg);
    }
    setPanel(&_panel);
  }

  // 自检轮播：切到第 idx 组几何配置并重新初始化屏幕
  void applyCfg(int idx) {
    int i = ((idx % CFG_N) + CFG_N) % CFG_N;
    auto cfg = _panel.config();
    cfg.memory_width  = CFG_TAB[i][0];
    cfg.memory_height = CFG_TAB[i][1];
    cfg.panel_width   = CFG_TAB[i][2];
    cfg.panel_height  = CFG_TAB[i][3];
    cfg.offset_x      = CFG_TAB[i][4];
    cfg.offset_y      = CFG_TAB[i][5];
    cfg.offset_rotation = 0;
    _panel.config(cfg);
    init();                        // 重复 init 会按新配置重写 MADCTL/CASET/RASET
    setRotation(CFG_TAB[i][6]);
    fillScreen(C_BG);
  }
};

static LGFX lcd;
static LGFX_Sprite sprite(&lcd);
#include "weather_cn.h" // 天气页中文点阵字模（晴/阴/雨/雪…），须放在 sprite 声明之后
#include "cn_city.h"    // 城市名中文点阵字模（地名常用字），同样须在 sprite 之后
#include "mc_theme.h"   // 总览页《我的世界》主题：5x7 点阵字 + 方块图标（纯 ASCII，不需中文字库）
#include "clock_fonts.h" // 时钟页圆润数字掩码（多字体 4-bit alpha，长按按键循环切换）

// ============================== 数据 ========================================
struct Stats {
  int   cpu   = -1;
  int   mem   = -1;
  float memGB = -1;
  int   cpuT  = -999;
  int   gpu   = -1;
  int   gpuT  = -999;
  float upKB  = 0;
  float dnKB  = 0;
  int   disk  = -1;
  float dskFreeGB = -1;
  char  time[8]   = "--:--";
  char  date[8]   = "";
  char  uptime[10]= "";
  int   year  = 0;   // 日历页用：PC 下发的完整日期
  int   month = 0;
  int   day   = 0;
  int   sec   = 0;   // 秒（驱动时钟页秒针环 / 冒号闪烁）

  // 天气页（PC 端 monitor.py 经 Open-Meteo 下发，无数据时为未就绪）
  bool   wHave = false;   // 是否已拿到过一次天气
  float  wTemp = 0;      // 当前温度 °C
  int    wCode = -1;      // WMO 天气代码
  float  wFeel = 0;      // 体感温度 °C
  int    wHum  = -1;     // 相对湿度 %
  float  wWind = 0;      // 风速 km/h
  float  wHi   = 0;      // 当日最高温 °C
  float  wLo   = 0;      // 当日最低温 °C
  char   wCity[24] = "";   // 城市名（中文 UTF-8，优先显示）
  char   wCityEn[24] = ""; // 城市名（英文 ASCII，字库缺字时回退）
};
static Stats   st;
static bool    hasData = false;
static uint32_t lastPkt = 0;
static volatile bool newData = false;   // 收到一帧完整有效数据就置位

// ---- 前向声明：这些函数定义在文件后部，提前声明供渲染/解析调用 ----
static void render();
void drawSelfTestPattern();
static int dayOfWeek(int y, int m, int d);
static int daysInMonth(int y, int m);
// 收包/错包计数（串口解析共用，定义在此以便前置使用）
static uint32_t rxOk = 0, rxBad = 0;

// ---- 离线时钟：PC 关机后由 ESP32 自己走时，不再依赖电脑 ----
// 在线时每帧用 PC 带来的真实时间对齐（零漂移）；离线时按 millis() 流逝推进。
// 前提：ESP32 的 USB 在电脑关机后仍由主板待机供电（USB 待机供电默认多开启）。
static int      gClkY = 0, gClkM = 0, gClkD = 0;   // 年/月/日
static int      gClkH = 0, gClkMi = 0, gClkS = 0;  // 时/分/秒
static uint32_t gClkMs = 0;                        // 上次从 PC 同步时间时的 millis()
static bool     gClkSynced = false;                // 是否已拿到过一次有效时间
static const uint32_t OFFLINE_MS = 5000;           // 超过这么久没收帧 = PC 已离线
static bool     gWasOnline = true;                 // 上一帧在/离线状态（用于边沿触发跳页）

// ============================== 12x12 矢量图标 ==============================
enum { IC_CLOCK, IC_CHIP, IC_RAM, IC_NET, IC_GPU, IC_DISK };

static void drawIcon(int id, int x, int y, uint16_t c) {
  switch (id) {
    case IC_CLOCK:
      sprite.drawCircle(x + 6, y + 6, 5, c);
      sprite.drawLine(x + 6, y + 6, x + 6, y + 3, c);
      sprite.drawLine(x + 6, y + 6, x + 9, y + 6, c);
      sprite.fillRect(x + 5, y + 0, 2, 1, c);
      break;
    case IC_CHIP:
      sprite.drawRect(x + 2, y + 2, 8, 8, c);
      sprite.fillRect(x + 4, y + 4, 4, 4, c);
      sprite.fillRect(x + 4, y + 0, 1, 2, c);
      sprite.fillRect(x + 7, y + 0, 1, 2, c);
      sprite.fillRect(x + 4, y + 10, 1, 2, c);
      sprite.fillRect(x + 7, y + 10, 1, 2, c);
      sprite.fillRect(x + 0, y + 4, 2, 1, c);
      sprite.fillRect(x + 0, y + 7, 2, 1, c);
      sprite.fillRect(x + 10, y + 4, 2, 1, c);
      sprite.fillRect(x + 10, y + 7, 2, 1, c);
      break;
    case IC_RAM:
      sprite.drawRect(x + 1, y + 3, 10, 6, c);
      sprite.fillRect(x + 3, y + 5, 1, 2, c);
      sprite.fillRect(x + 5, y + 5, 1, 2, c);
      sprite.fillRect(x + 7, y + 5, 1, 2, c);
      sprite.fillRect(x + 2, y + 9, 1, 2, c);
      sprite.fillRect(x + 5, y + 9, 1, 2, c);
      sprite.fillRect(x + 8, y + 9, 1, 2, c);
      break;
    case IC_NET:
      sprite.drawLine(x + 6, y + 1, x + 6, y + 11, c);
      sprite.fillTriangle(x + 6, y + 1, x + 3, y + 5, x + 9, y + 5, c);
      sprite.fillTriangle(x + 6, y + 11, x + 3, y + 7, x + 9, y + 7, c);
      break;
    case IC_GPU:
      sprite.drawRect(x + 1, y + 3, 10, 7, c);
      sprite.drawCircle(x + 4, y + 6, 2, c);
      sprite.drawCircle(x + 8, y + 6, 2, c);
      sprite.fillRect(x + 3, y + 10, 6, 1, c);
      break;
    case IC_DISK:
      sprite.drawRoundRect(x + 1, y + 3, 10, 6, 1, c);
      sprite.fillRect(x + 3, y + 5, 4, 1, c);
      sprite.fillRect(x + 3, y + 7, 4, 1, c);
      sprite.fillCircle(x + 9, y + 6, 1, c);
      break;
  }
}

// ============================== 绘制工具 ====================================
// Font2 是 BMPfont、Font0 是 GLCDfont，两者类型不同，不能写成三元表达式，
// 必须分开调用 setFont(const IFont*) 重载
static void pickFont(int fontH) {
  if (fontH > 12) sprite.setFont(&lgfx::fonts::Font2);
  else            sprite.setFont(&lgfx::fonts::Font0);
}
static void txtRight(const char* s, int right, int centerY, int fontH, uint16_t color, uint16_t bg) {
  pickFont(fontH);
  sprite.setTextColor(color, bg);
  sprite.setCursor(right - sprite.textWidth(s), centerY - fontH / 2);
  sprite.print(s);
}
static void txtLeft(const char* s, int left, int centerY, int fontH, uint16_t color, uint16_t bg) {
  pickFont(fontH);
  sprite.setTextColor(color, bg);
  sprite.setCursor(left, centerY - fontH / 2);
  sprite.print(s);
}
static void txtCenter(const char* s, int cx, int centerY, int fontH, uint16_t color, uint16_t bg) {
  pickFont(fontH);
  sprite.setTextColor(color, bg);
  sprite.setCursor(cx - sprite.textWidth(s) / 2, centerY - fontH / 2);
  sprite.print(s);
}

// 绘制 16x16 中文点阵字模（左上角坐标 x,y）
static void drawCn(int idx, int x, int y, uint16_t color) {
  for (int row = 0; row < CN_GLYPH_H; row++) {
    uint16_t bits = (uint16_t)pgm_read_byte(&CN_GLYPHS[idx][row * 2]) << 8
                  | pgm_read_byte(&CN_GLYPHS[idx][row * 2 + 1]);
    for (int col = 0; col < CN_GLYPH_W; col++)
      if (bits & (0x8000 >> col)) sprite.writeFastHLine(x + col, y + row, 1, color);
  }
}

// 居中绘制 "2026 年 9 月" 风格的中文月份标题
static void drawMonthTitle(int year, int month, int centerY, uint16_t color) {
  char ybuf[8], mbuf[4];
  snprintf(ybuf, sizeof(ybuf), "%d", year);
  snprintf(mbuf, sizeof(mbuf), "%d", month);
  pickFont(14);
  int wy = sprite.textWidth(ybuf);
  int wm = sprite.textWidth(mbuf);
  int gap = 3;
  int x = (SCR_W - (wy + gap + 16 + gap + wm + gap + 16)) / 2;
  sprite.setTextColor(color, C_BG);
  sprite.setCursor(x, centerY - 7);
  sprite.print(ybuf);
  drawCn(CN_NIAN, x + wy + gap, centerY - 8, color);
  int x2 = x + wy + gap + 16 + gap;
  sprite.setCursor(x2, centerY - 7);
  sprite.print(mbuf);
  drawCn(CN_YUE, x2 + wm + gap, centerY - 8, color);
}
// 大号文本（Font2 × size 放大），用于调节页的重点数字
static void txtBig(const char* s, int cx, int cy, int size, uint16_t color) {
  sprite.setFont(&lgfx::fonts::Font2);
  sprite.setTextSize(size);
  sprite.setTextColor(color, C_BG);
  sprite.setCursor(cx - sprite.textWidth(s) / 2, cy - (16 * size) / 2);
  sprite.print(s);
  sprite.setTextSize(1);
}

// 速率格式化：>=1024 KB/s 显示 M，否则 K
static void fmtRate(float kb, char* out, size_t n) {
  if (kb < 0)          snprintf(out, n, "--");
  else if (kb >= 1024) snprintf(out, n, "%.1fM", kb / 1024.0f);
  else                 snprintf(out, n, "%.0fK", kb);
}

// ---- 软件 180° 翻转（外壳倒装用）------------------------------------------
// 为什么不用 lcd.setRotation(3)：见文件顶部 PANEL_FLIP_180 处的说明（两组参数实测均失败）。
// 这里对 sprite 的 16bit 缓冲做「行序倒置 + 行内像素倒置」= 整幅 180° 旋转。
//
// 三点必须守住：
//  1) 只搬 16bit 元素、不拆元素内部字节 —— 缓冲是 swap565 字节序，拆字节会红蓝互换。
//  2) 按 sprite.width() 逐行处理，不假设整块缓冲连续无行间距。
//  3) 只能在「本帧绘制已全部完成、即将 push」时调用；调用后缓冲内容已变，
//     若同一帧再画东西或再翻转一次，画面就会被转回/画错位置。
static void flipBuf180() {
  if (!PANEL_FLIP_180) return;
  uint16_t* buf = (uint16_t*)sprite.getBuffer();
  const int W = sprite.width();
  const int H = sprite.height();
  if (!buf || W <= 0 || H <= 0 || W > SCR_W) return;

  static uint16_t line[SCR_W];          // 单行暂存 320B，避免逐像素三重交换
  for (int y = 0; y < H / 2; ++y) {
    uint16_t* a = buf + (size_t)y * W;
    uint16_t* b = buf + (size_t)(H - 1 - y) * W;
    for (int x = 0; x < W; ++x) line[x] = a[x];          // 暂存上半行
    for (int x = 0; x < W; ++x) a[x] = b[W - 1 - x];     // 下半行倒序搬上去
    for (int x = 0; x < W; ++x) b[W - 1 - x] = line[x];  // 上半行倒序搬下来
  }
  if (H & 1) {                                           // 奇数高度时中间行需自反
    uint16_t* m = buf + (size_t)(H / 2) * W;
    for (int x = 0; x < W / 2; ++x) { uint16_t t = m[x]; m[x] = m[W - 1 - x]; m[W - 1 - x] = t; }
  }

  // ★不要在这里做任何「端点补偿」——曾经加过两版都没用，第二版还制造了新故障：
  //   旧 v1：把最外 1 行涂成 gBgColor → 该行原本是头栏色，涂完露出一条异色横线；
  //   旧 v2：把紧邻端点的内侧行整行复制进端点行 → 内侧行若是「每秒变化的数值」
  //          （总览页 y=126 正是 DSK 副值字形底行），等于把动态内容搬进撕裂带，
  //          底部于是出现一条随数值跳变的短横线（"最左下方闪烁/乱码"的真身）。
  //   正确做法是让逻辑两端各留若干行**纯背景**（见文件顶部 EDGE_TOP/EDGE_BOT 说明）：
  //   背景行每帧逐像素恒等，撕裂时新旧帧相同 → 天然不可见，不需要任何补偿代码。
}

// 统一的「推屏」出口：翻页过渡期间 gPush=false，只画进 sprite 不推送，
// 由过渡逻辑在 sprite 上叠加幕布后再手动 push。
static bool gPush = true;
static void pushScreen() {
  if (!gPush) return;
  flipBuf180();
  sprite.pushSprite(0, 0);
}

// ============================== 按键 ========================================
// 单按键两种手势：
//   短按（按住 <600ms 后松开）→ 循环切页
//   长按（按住 >=600ms）      → 循环切换时钟页数字字体（用于在设备上现场比对字形）
// 判定走 25ms 去抖后的 stable 电平，全程非阻塞（loop 每 2ms 调一次）。
struct Btn {
  uint8_t pin;
  bool raw;         // 最近一次 raw 读
  bool stable;      // 去抖后的稳定电平（LOW=按下）
  uint32_t dbT;     // 上次 raw 翻转时刻
  uint32_t downT;   // 按下沿（stable 变 LOW）时刻，用于长按计时
  bool longFired;   // 本次按住是否已触发长按（防止松手时再补一次短按）
};
static Btn BTN;
// 单按键：按下沿 → 切下一页（循环）
static bool evNext = false;
static bool evFont = false;   // 长按 → 切换时钟页字体
static const uint32_t BTN_LONG_MS = 600;

static void btnSetup() {
  pinMode(PIN_BTN, INPUT_PULLUP);
  BTN.pin = PIN_BTN;
  BTN.raw = digitalRead(PIN_BTN);
  BTN.stable = BTN.raw;
  BTN.dbT = 0;
  BTN.downT = 0;
  BTN.longFired = false;
}

static void btnPoll() {
  evNext = false;
  evFont = false;
  uint32_t now = millis();
  bool r = digitalRead(BTN.pin);
  if (r != BTN.raw) {               // raw 翻转，重启去抖计时
    BTN.raw = r;
    BTN.dbT = now;
  } else if (now - BTN.dbT >= 25) { // 稳定超过 25ms，采纳
    if (r != BTN.stable) {
      BTN.stable = r;
      if (r == LOW) {               // 按下沿：起长按计时
        BTN.downT = now;
        BTN.longFired = false;
      } else if (!BTN.longFired) {  // 抬起沿且本次没长按过 → 短按切页
        evNext = true;
      }
    }
  }
  // 长按：按住不放超过 BTN_LONG_MS 即触发一次（不等松手，手感更跟手）
  if (BTN.stable == LOW && !BTN.longFired && now - BTN.downT >= BTN_LONG_MS) {
    BTN.longFired = true;
    evFont = true;
  }
}

// ============================== 页面 / 状态 ================================
// 三个页面用三个开关直接选；只有 ST_MON 一个状态，无菜单/无设置/无自检。
enum UiState  { ST_MON };
enum ViewPage { VIEW_OVERVIEW, VIEW_CLOCK, VIEW_CALENDAR, VIEW_WEATHER };   // 1总览 2大时钟 3整面日历 4天气
static const int N_PAGES = 4;

static UiState  uiState = ST_MON;
static ViewPage curView = VIEW_OVERVIEW;

// 硬编码（不要设置菜单）：亮度 ~78% / 刷新 1s / °C
static const uint8_t  gBright    = 200;
static const uint32_t gRefreshMs = 1000;

// 翻页过渡
static const uint32_t TRANS_MS = 170;
static bool     transActive = false;
static uint32_t transStart  = 0;
static bool     gBlink      = false;      // 时钟冒号闪烁状态
static uint32_t lastClockDraw = 0;

// 翻页：直接跳到指定页 + 启动幕布过渡（170ms 推屏动效）
static void goPage(ViewPage p) {
  if (transActive) return;            // 过渡中忽略重复翻页
  if (p == curView) return;           // 同页不重绘
  curView = p;
  transActive = true;
  transStart  = millis();
  gPush = false;                      // 过渡期间先不推送，由幕布逻辑控制
}

// 温度换算（硬编码 °C，屏幕字体无 °，显示成 "62C"）
static int dispTemp(int c) { return c; }

// ============================== 通用屏 ======================================
// bg 可传入所在页的底色（字符背景块要跟页面底色一致，否则会出现色块）
static void drawNoData(uint16_t bg = C_BG) {
  const char* a = "PC MONITOR";
  const char* b = "NO DATA";
  sprite.setFont(&lgfx::fonts::Font2);
  sprite.setTextColor(C_DIM, bg);
  sprite.setCursor((SCR_W - sprite.textWidth(a)) / 2, SCR_H / 2 - 18);
  sprite.print(a);
  sprite.setFont(&lgfx::fonts::Font0);
  sprite.setTextColor(C_LINE, bg);
  sprite.setCursor((SCR_W - sprite.textWidth(b)) / 2, SCR_H / 2 + 4);
  sprite.print(b);
}

// 顶部页码圆点：当前页用强调色实心，其余灰色小点（共 N_PAGES 页）
static void drawPageDots() {
  int cx = SCR_W / 2, y = 6;
  for (int i = 0; i < N_PAGES; i++) {
    int x = cx + (int)((i - (N_PAGES - 1) / 2.0) * 9);
    if (i == (int)curView) sprite.fillCircle(x, y, 2, C_ACC);
    else                   sprite.fillCircle(x, y, 1, C_DIM);
  }
}

// 秒针刻度环：60 格，已过的秒数填强调色，未过填灰；末端强调色圆点（Braun 黄秒针的极简致敬）
static void drawSecRing(int cx, int cy, int R, int sec) {
  for (int i = 0; i < 60; i++) {
    float a = (i * 6 - 90) * PI / 180.0f;
    int x = cx + (int)(cosf(a) * (R - 1));
    int y = cy + (int)(sinf(a) * (R - 1));
    sprite.fillCircle(x, y, 1, (i <= sec) ? C_ACC : C_DIM);
  }
  float a = (sec * 6 - 90) * PI / 180.0f;
  sprite.fillCircle(cx + (int)(cosf(a) * R), cy + (int)(sinf(a) * R), 2, C_ACC);
}

static void drawHeader(bool stale) {
  char buf[16];
  sprite.fillRect(0, 0, SCR_W, HEAD_H, C_HEAD);
  drawIcon(IC_CLOCK, 4, 2, C_DIM);
  txtLeft(stale ? "--:--" : st.time, 20, HEAD_H / 2, 16, C_TXT, C_HEAD);
  snprintf(buf, sizeof(buf), "%s %s", st.date, stale ? "OFF" : st.uptime);
  txtRight(buf, 156, HEAD_H / 2, 8, stale ? C_WARN : C_DIM, C_HEAD);
  sprite.drawLine(0, HEAD_H, SCR_W, HEAD_H, C_LINE);
  drawPageDots();
}

// ============================== 第2页：翻页时钟（split-flap）===============
// 当前方案：clock_candy_main_3x.png · 糖果店·奶油（无框）
//   ① 6 张卡片各一块马卡龙色（HH/MM/SS 每数字一色），上亮下暗 + 中缝 + 糖衣高光
//   ② 数字用 Trebuchet MS Bold 圆润掩模，翻页时按卡片索引替换哨兵色，零额外显存
//   ③ 全屏唯一动效就是翻页：旧上半向中缝收拢 → 新下半由中缝向下展开
#define FC_W       22                 // 卡片宽
#define FC_H       42                 // 卡片高
#define FC_HALF    20                 // 上半卡高（对齐设计稿：上 20 行 + 下 22 行）
#define FC_HB      22                 // 下半卡高（= FC_H - FC_HALF），中缝画在 FC_Y+FC_HALF
#define FC_GW       (FC_W - 2)        // 数字位图宽（左右各内缩 1px，保住圆角描边）
#define FC_GB       ((FC_GW + 1) / 2) // 每行占字节数（4-bit alpha：高 nibble = 左像素）
#define FC_DIG_DY_DEF (0)             // 数字偏移默认值（PC 端未下发时用；正=上移，负=下移）
#define FC_Y        26                // 卡片顶部 y
#define FLIP_MS    420                // 翻页总时长
#define FLIP_FPS   40                 // 动画帧间隔（25fps）

// 时钟页方案：clock_candy_main_3x.png · 糖果店·奶油（无框）
// 6 张卡片各一块马卡龙色，上半亮、下半压暗 10%，深紫灰数字。
static const uint16_t C_CARD_TOP[6] = {
  RGB(0x24, 0x24, 0x2E), RGB(0x24, 0x24, 0x2E), RGB(0x24, 0x24, 0x2E),
  RGB(0x24, 0x24, 0x2E), RGB(0x24, 0x24, 0x2E), RGB(0x24, 0x24, 0x2E)
};
static const uint16_t C_CARD_BOT[6] = {
  RGB(0x17, 0x17, 0x1E), RGB(0x17, 0x17, 0x1E), RGB(0x17, 0x17, 0x1E),
  RGB(0x17, 0x17, 0x1E), RGB(0x17, 0x17, 0x1E), RGB(0x17, 0x17, 0x1E)
};
static const uint16_t C_CARD_DIG[6] = {
  RGB(0xFF, 0x4F, 0x81), RGB(0xFF, 0xB0, 0x00), RGB(0xFF, 0xF4, 0x5C),
  RGB(0x5C, 0xFF, 0x8A), RGB(0x4F, 0xC3, 0xFF), RGB(0xB3, 0x88, 0xFF)
}; // 6 位数字各一 Candy Rainbow 色
static const uint16_t C_FOLD_W      = RGB(0x08, 0x08, 0x0C);   // 中缝（近黑）
static const uint16_t C_BG_W        = RGB(0x0E, 0x0E, 0x13);   // 时钟页底（与全局 C_BG 一致的近黑）
static const uint16_t C_DATE_W      = RGB(0x8E, 0x8E, 0x93);   // 日期次级
static const uint16_t C_UP_W        = RGB(0x48, 0x48, 0x4A);   // uptime 最弱
static const uint16_t C_COLON_W     = RGB(0x8E, 0x8E, 0x93);   // 冒号点（iOS secondaryLabel 灰）

// sprite 缓冲字节序标定（启动时实测，不写死）：
// LGFX_Sprite 的 setColorDepth(16) 内部是 rgb565_2Byte = swap565_t（swapped=true），
// 即缓冲区里的 uint16 在小端 CPU 上读出来是 swap16(逻辑色值)。
// LovyanGFX 的绘图 API（fillRect/drawPixel…）会自动做这层交换，
// 但**直接写 getBuffer() 裸缓冲时必须自己补上**，否则屏上红蓝通道互换
// （实测表现：逻辑深灰 #24242E 显示成绿色、粉色数字显示成蓝紫 —— 即"绿底蓝色块"）。
static bool gSprSwap = true;            // true = 裸写缓冲前需 swap16

// 卡片 x 坐标：HH [2] MM [7] SS，组间距 7（放冒号点），组内间距 2
static const int FC_X[6] = { 4, 28, 57, 81, 110, 134 };

// 10 个数字的上下半 **4-bit alpha 掩码**（0=背景，15=墨迹；每行 FC_GB 字节，高 nibble 在前）。
// 与屏缓冲字节序无关；翻页叶片贴图时按 alpha 与卡面底色混合 → 抗锯齿边缘。
static uint8_t  gTop[10][FC_HALF * FC_GB];   // 卡片行 [0..20)
static uint8_t  gBot[10][FC_HB   * FC_GB];   // 卡片行 [20..42)
static bool     gFlipReady = false;
// 时钟页当前字体索引：长按按键循环切换，切换后重新烘焙 gTop/gBot（掩码源换一套）。
static uint8_t  gFontIdx = 0;
static uint32_t gFontTagT = 0;                 // 最近一次切换字体的时刻（屏幕提示字体名 1.5s）
static const uint32_t FONT_TAG_MS = 1500;
static int      gDigDy = FC_DIG_DY_DEF;   // 数字垂直偏移，可由 PC 端 "do" 字段实时改写
static int      gStretch = 100;           // 数字垂直拉伸 %（100=原样，与预览稿自然比例一致），PC 端 "ds" 可调；宽度不变只拉高

struct FlipDigit { int8_t cur = -1, prev = -1; uint32_t t0 = 0; bool anim = false; };
static FlipDigit FD[6];

// RGB565 按 alpha 线性混合（a=0 → 全背景，a=15 → 全墨迹）。
// 与设计稿 PIL 的抗锯齿合成同构，是数字边缘"圆润"的来源。
static inline uint16_t blend565(uint16_t bg, uint16_t fg, int a) {
  const int ia = 15 - a;
  const int r = (((fg >> 11) & 0x1F) * a + ((bg >> 11) & 0x1F) * ia) / 15;
  const int g = (((fg >>  5) & 0x3F) * a + ((bg >>  5) & 0x3F) * ia) / 15;
  const int b = (( fg        & 0x1F) * a + ( bg        & 0x1F) * ia) / 15;
  return (uint16_t)((r << 11) | (g << 5) | b);
}

// 4-bit alpha 掩码取第 x 个像素（每行 FC_GB 字节，高 nibble = 偶数列）
static inline uint8_t nibAt(const uint8_t* row, int x) {
  const uint8_t v = row[x >> 1];
  return (x & 1) ? (uint8_t)(v & 0x0F) : (uint8_t)(v >> 4);
}

static inline void nibSet(uint8_t* row, int x, uint8_t a) {
  uint8_t& b = row[x >> 1];
  if (x & 1) b = (uint8_t)((b & 0xF0) | (a & 0x0F));
  else       b = (uint8_t)((uint8_t)(a << 4) | (b & 0x0F));
}

// 把 0-9 的 4-bit alpha 掩码（clock_fonts.h 中 gFontIdx 那一套）按 gStretch 重采样，
// 切半存入 gTop/gBot。长按按键切换字体时重新调用本函数即可（掩码源换一套）。
// 流程（不依赖任何字体度量）：
//   1) 扫描 alpha>0 的行 → 墨迹范围 [minY,maxY]；
//   2) 拉伸目标高度 stH = inkH * gStretch / 100（限 ≤38 防顶边）；
//   3) 逐行最近邻重采样 alpha，墨迹中心 cy 按 stH 动态限幅（超了贴边不裁切）；
//   4) 切片：gTop = 卡片行 [0..20)，gBot = 卡片行 [20..42)。
//      [关键修正] 旧版下半自卡片行 22 起，屏幕行 20/21 整段无内容 → 数字被拦腰
//      横切 2 行，是"圆润度不足"的另一半原因。设计稿下半从 FC_Y+FC_HALF 起，
//      故此处对齐为行 20，数字只在 1px 中缝线上被覆盖。
//
// [定位语义·实测备忘] 本机 LovyanGFX 两个大坑（2026-09-10 设备实测）：
//   ① setCursor+print 的 datum 定位异常——middle_center+print 把 Font4 数字画到
//      y=36..41（卡片最底）并裁剪，bottom_center+print 直接画出界；字形定位必须用
//      drawString(s, x, y)（配合 setTextDatum）。
//   ② sprite 缓冲字节序：16bit sprite 内部是 rgb565_2Byte = swap565_t（LovyanGFX
//      colortype.hpp 有明确定义），即裸缓冲里存的是 swap16(逻辑色值)。凡直接写
//      getBuffer() 的地方都必须自己补 swap16，否则屏上红蓝通道互换（设备实测：
//      深灰卡面显示成绿色块）。启动时用 gSprSwap 实测标定，不写死假设。
static void buildFlipGlyphs() {
  static LGFX_Sprite tmp(&lcd);
  tmp.setColorDepth(16);
  if (!tmp.createSprite(FC_GW, FC_H)) return;

  // 1) 标定缓冲字节序：用同一个精灵类、同样的 setColorDepth(16)，写入已知值再读回。
  //    读回 == 写入值 → 不交换（0x1234 对称，故用一个上下字节不同的值才可判）。
  //    只做一次：长按切换字体时会重复调用本函数，无需反复标定。
  static bool sprCalibrated = false;
  if (!sprCalibrated) {
    tmp.fillSprite(0x1234);
    const uint16_t got = ((const uint16_t*)tmp.getBuffer())[0];
    gSprSwap = (got != 0x1234);
    Serial.printf("[DIAG] sprite16 fill=0x1234 buf=0x%04X swap=%d\n", got, (int)gSprSwap);
    sprCalibrated = true;
  }

  // 圆润数字：来自 gen_clock_font.py 的 4-bit alpha 掩码（替代内置 Font4 块面字）。
  // 多套字体并存于 clock_fonts.h，此处只烘焙当前 gFontIdx 那一套 —— RAM 占用与
  // 单字体方案相同（gTop/gBot 尺寸不变），多出来的只是 Flash 里的掩码表。
  memset(gTop, 0, sizeof(gTop));
  memset(gBot, 0, sizeof(gBot));
  Serial.printf("[CLK] font=%d \"%s\"\n", (int)gFontIdx, CLOCK_FONT_NAME[gFontIdx]);
  for (int d = 0; d < 10; d++) {
    // 1) 墨迹范围（alpha > 0 的行）
    int minY = FC_H, maxY = -1;
    for (int y = 0; y < FC_H; y++) {
      for (int x = 0; x < FC_GW; x++) {
        if (pgm_read_byte(&CLOCK_FONTS[gFontIdx][d][y][x])) {
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    if (maxY < 0) { minY = FC_H / 2; maxY = minY; }      // 兜底：量不到墨迹就用中心
    const int inkH = maxY - minY + 1;
    // 2) 拉伸目标高度 + 中心动态限幅
    int stH = (inkH * gStretch) / 100;
    if (stH > 38) stH = 38;
    if (stH < 1)  stH = 1;
    int cy    = (FC_H / 2) - gDigDy;                     // 目标中心行（正 do=上移）
    const int cyMin = stH / 2;
    const int cyMax = (FC_H - 1) - (stH - 1 - stH / 2);
    if (cy < cyMin) cy = cyMin;
    if (cy > cyMax) cy = cyMax;
    const int inkTop = cy - stH / 2;                     // 拉伸后墨迹首行
    // 3) 逐行最近邻重采样 alpha，切片写入 gTop[0..20) / gBot[20..42)
    for (int y = 0; y < FC_H; y++) {
      const int sy = (y < inkTop || y >= inkTop + stH)
                       ? -1
                       : minY + (int)((int32_t)(y - inkTop) * inkH / stH);
      uint8_t* dst = (y < FC_HALF) ? gTop[d] + y * FC_GB
                                   : gBot[d] + (y - FC_HALF) * FC_GB;
      for (int x = 0; x < FC_GW; x++) {
        uint8_t a = 0;
        if (sy >= 0 && sy < FC_H) a = pgm_read_byte(&CLOCK_FONTS[gFontIdx][d][sy][x]);
        if (a) nibSet(dst, x, a);
      }
    }
  }
  tmp.deleteSprite();
  gFlipReady = true;
}

// 把半张 4-bit alpha 掩码按 dstH 垂直压缩贴到 sprite（最近邻取样），并按 alpha 与
// 卡面底色混合 → 数字边缘抗锯齿。srcRows = 源掩码行数（上半 FC_HALF / 下半 FC_HB）。
// LUT 只有 16 项，每半张卡算一次；逐像素仅一次查表，ESP32 上开销可忽略。
static void blitHalf(int dx, int dy, int dstH, const uint8_t* src, int srcRows,
                     uint16_t bgColor, uint16_t digColor) {
  if (dstH <= 0 || srcRows <= 0) return;
  // 混合 + 裸缓冲字节序换算，一次算好 16 级查找表
  uint16_t lut[16];
  for (int a = 0; a < 16; a++) {
    const uint16_t c = blend565(bgColor, digColor, a);
    lut[a] = gSprSwap ? swap16(c) : c;
  }
  uint16_t* dst = (uint16_t*)sprite.getBuffer();
  for (int ty = 0; ty < dstH; ty++) {
    const int sy = (ty * srcRows) / dstH;
    if (dy + ty < 0 || dy + ty >= SCR_H) continue;
    uint16_t* orow = dst + (uint32_t)(dy + ty) * SCR_W + dx;
    const uint8_t* srow = src + (uint32_t)sy * FC_GB;
    for (int x = 0; x < FC_GW; x++) orow[x] = lut[nibAt(srow, x)];
  }
}

// 按当前时刻的 h/m/s 更新 6 位数字；变化时打上动画起点。
// 统一读内部时钟 gClk*：在线时它已被 PC 每帧对齐，离线时它自己走时，所以离线也能翻页。
static void updateFlipDigits(bool animate) {
  if (!gClkSynced) return;
  int v[6];
  v[0] = gClkH / 10;  v[1] = gClkH % 10;
  v[2] = gClkMi / 10; v[3] = gClkMi % 10;
  v[4] = gClkS / 10;  v[5] = gClkS % 10;
  for (int i = 0; i < 6; i++) {
    if (v[i] < 0 || v[i] > 9) continue;            // "--:--" 期间保持原值
    if (FD[i].cur == v[i]) continue;
    FD[i].prev = FD[i].cur;
    FD[i].cur  = v[i];
    if (animate && FD[i].prev >= 0) { FD[i].t0 = millis(); FD[i].anim = true; }
    else                            { FD[i].prev = v[i];   FD[i].anim = false; }
  }
}

// 清掉已结束的动画；返回是否仍有卡片在翻
static bool flipTick() {
  uint32_t now = millis();
  bool any = false;
  for (int i = 0; i < 6; i++) {
    if (!FD[i].anim) continue;
    if (now - FD[i].t0 >= FLIP_MS) FD[i].anim = false;
    else                           any = true;
  }
  return any;
}

// ---- 离线走时：把内部时钟按真实流逝的毫秒推进（在线时每帧被 PC 重新对齐，不会累积漂移）----
static void tickClock() {
  if (!gClkSynced) return;
  uint32_t now = millis();
  uint32_t dt  = now - gClkMs;
  if (dt < 1000) return;
  uint32_t add = dt / 1000;          // 本次应推进的整秒数
  gClkMs += (uint32_t)add * 1000;    // 余下 <1s 的零头留到下次
  gClkS += add;
  if (gClkS >= 60) { uint32_t c = gClkS / 60; gClkS %= 60; gClkMi += c; }
  if (gClkMi >= 60) { uint32_t c = gClkMi / 60; gClkMi %= 60; gClkH += c; }
  if (gClkH >= 24) { uint32_t c = gClkH / 24; gClkH %= 24; gClkD += c; }
  uint8_t dim = daysInMonth(gClkY, gClkM);
  while (gClkD > dim) {
    gClkD -= dim; gClkM++;
    if (gClkM > 12) { gClkM = 1; gClkY++; }
    dim = daysInMonth(gClkY, gClkM);
  }
}

// PC 每帧带时间 → 用真实时间重新对齐内部时钟（在线时零漂移）
static void syncClockFromPC() {
  gClkY  = st.year;
  gClkM  = st.month;
  gClkD  = st.day;
  gClkH  = (st.time[0] - '0') * 10 + (st.time[1] - '0');
  gClkMi = (st.time[3] - '0') * 10 + (st.time[4] - '0');
  gClkS  = st.sec;
  gClkMs = millis();
  gClkSynced = true;
}

static void drawFlipCard(int i, uint32_t now) {
  if (FD[i].cur < 0) return;
  int x = FC_X[i], ix = x + 1;
  const int topY = FC_Y;                                        // gTop = 卡片行 [0..20)
  const int botY = FC_Y + FC_HALF;                              // gBot = 卡片行 [20..42)
  const FlipDigit& f = FD[i];
  uint16_t cTop = C_CARD_TOP[i];
  uint16_t cBot = C_CARD_BOT[i];

  float p = 1.0f;
  if (f.anim) p = (float)(now - f.t0) / (float)FLIP_MS;
  if (p > 1.0f) p = 1.0f;

  // 卡片底：上下两半分别填色（上 20 行 / 下 22 行，与设计稿一致）
  sprite.fillRoundRect(x, FC_Y, FC_W, FC_HALF, 3, cTop);
  sprite.fillRoundRect(x, botY, FC_W, FC_HB, 3, cBot);
  // 抹平中缝两侧的圆角缺口
  sprite.fillRect(x, FC_Y + FC_HALF - 4, FC_W, 4, cTop);

  // C 方案：无糖果高光；卡片统一深灰，数字自身就是彩虹色
  uint16_t cDig = C_CARD_DIG[i];

  if (p >= 1.0f) {                                                   // 静止：当前数字
    blitHalf(ix, topY, FC_HALF, gTop[f.cur],  FC_HALF, cTop, cDig);
    blitHalf(ix, botY, FC_HB,   gBot[f.cur],  FC_HB,   cBot, cDig);
  } else if (p < 0.5f) {                                             // A：旧上半向中缝收拢
    blitHalf(ix, topY, FC_HALF, gTop[f.cur],  FC_HALF, cTop, cDig);  // 收拢后露出新上半
    blitHalf(ix, botY, FC_HB,   gBot[f.prev], FC_HB,   cBot, cDig);  // 下半仍是旧值
    const int hA = (int)(FC_HALF * (1.0f - p * 2.0f));
    blitHalf(ix, topY + FC_HALF - hA, hA, gTop[f.prev], FC_HALF, cTop, cDig);
  } else {                                                           // B：新下半由中缝展开
    blitHalf(ix, topY, FC_HALF, gTop[f.cur],  FC_HALF, cTop, cDig);
    blitHalf(ix, botY, FC_HB,   gBot[f.prev], FC_HB,   cBot, cDig);
    const int hB = (int)(FC_HB * ((p - 0.5f) * 2.0f));
    blitHalf(ix, botY, hB, gBot[f.cur], FC_HB, cBot, cDig);
  }

  sprite.drawFastHLine(x + 1, botY, FC_W - 2, C_FOLD_W);   // 中缝（卡片行 20）
  // 本方案无卡片描边框（无框彩虹电子风格）
}

static void drawClockPage() {
  sprite.fillScreen(C_BG_W);
  bool offline = (millis() - lastPkt > OFFLINE_MS);
  if (!gClkSynced || !gFlipReady) { drawNoData(); pushScreen(); return; }
  drawPageDots();

  uint32_t now = millis();
  for (int i = 0; i < 6; i++) drawFlipCard(i, now);

  // 组间冒号点：两个 2x2 小方块，对称于卡片中缝（彩虹电子主题，静态不闪）
  int cy = FC_Y + FC_H / 2;
  for (int k = 0; k < 2; k++) {
    int cx = (k == 0) ? (FC_X[1] + FC_W + 3) : (FC_X[3] + FC_W + 3);
    sprite.fillRect(cx, cy - 6, 2, 2, C_COLON_W);
    sprite.fillRect(cx, cy + 4, 2, 2, C_COLON_W);
  }

  // 日期（琥珀次级，卡片下方）—— 读内部时钟，离线也准
  char dstr[16];
  snprintf(dstr, sizeof(dstr), "%04d-%02d-%02d", gClkY, gClkM, gClkD);
  txtCenter(dstr, SCR_W / 2, 92, 14, C_DATE_W, C_BG_W);

  // 字体切换提示：长按换字体后，顶部显示 "F2/4 Nunito" 1.5s，便于在设备上辨认当前字形。
  if (gFontTagT && (now - gFontTagT) < FONT_TAG_MS) {
    char tag[28];
    snprintf(tag, sizeof(tag), "F%d/%d %s", (int)gFontIdx + 1, (int)CLOCK_FONT_COUNT,
             CLOCK_FONT_NAME[gFontIdx]);
    sprite.setFont(&lgfx::fonts::Font2);
    sprite.setTextDatum(textdatum_t::middle_center);
    sprite.setTextColor(C_CARD_DIG[gFontIdx % 6], C_BG_W);
    sprite.drawString(tag, SCR_W / 2, 17);
  }

  // 开机时长（最弱，底部）；离线时 PC 已关机，uptime 无意义，留空
  if (st.uptime[0] && !offline) txtCenter(st.uptime, SCR_W / 2, 112, 8, C_UP_W, C_BG_W);

  if (!gPush) return;                       // 翻页幕布期间由过渡逻辑统一推送
  // 先整帧翻转，再决定推哪块：翻转后「卡片区」在缓冲里和屏上都落在
  // [SCR_H-FC_Y-FC_H, SCR_H-FC_Y)，所以源偏移与目标 y 用同一个镜像后的坐标。
  flipBuf180();
  const int cardY = SCR_H - FC_Y - FC_H;
  // 只在卡片区有动画时推局部（160x42 ≈ 13KB），静止时整屏推，省一半 SPI 带宽
  if (flipTick()) {
    uint16_t* buf = (uint16_t*)sprite.getBuffer();
    lcd.pushImage(0, cardY, SCR_W, FC_H, buf + (uint32_t)cardY * SCR_W);
  } else {
    sprite.pushSprite(0, 0);
  }
}

// ============================== 第3页：整面日历表格 =========================
static void drawCalendarPage() {
  sprite.fillScreen(C_BG);
  if (!hasData || !st.year) { drawNoData(); pushScreen(); return; }
  drawPageDots();

  static const char* WD[7]  = {"Mo","Tu","We","Th","Fr","Sa","Su"};
  int cw   = 22;                        // 每列宽
  int gx0  = (SCR_W - cw * 7) / 2;      // 居中（左右各留 3px）
  int gy0  = 46;                        // 网格起始
  if (st.month >= 1 && st.month <= 12)
    drawMonthTitle(st.year, st.month, 22, C_TXT);       // "2026 年 9 月"
  else {
    char yb[8];
    snprintf(yb, sizeof(yb), "%04d", st.year);
    txtCenter(yb, SCR_W / 2, 22, 14, C_TXT, C_BG);
  }
  sprite.drawLine(20, 30, SCR_W - 20, 30, C_LINE);

  int rows = 6;
  int rh   = (SCR_H - gy0) / rows;      // 每格高
  // 星期行
  for (int i = 0; i < 7; i++) txtCenter(WD[i], gx0 + cw * i + cw / 2, 38, 10, C_DIM, C_BG);
  sprite.drawLine(0, gy0, SCR_W, gy0, C_LINE);
  // 网格竖线（发丝线）
  for (int i = 1; i < 7; i++) sprite.drawLine(gx0 + cw * i, gy0, gx0 + cw * i, SCR_H, C_LINE);

  // 日期
  int fd = (dayOfWeek(st.year, st.month, 1) + 6) % 7;   // 周一为首列
  int total = daysInMonth(st.year, st.month);
  int row = 0, col = fd;
  char ds[3];
  for (int d = 1; d <= total; d++) {
    int cx = gx0 + cw * col + cw / 2;
    int cy = gy0 + rh * row + rh / 2;
    snprintf(ds, sizeof(ds), "%d", d);
    if (d == st.day) {
      sprite.fillCircle(cx, cy, (rh - 4) / 2, C_ACC);          // 今天：强调色实心圆
      txtCenter(ds, cx, cy, 11, C_BG, C_ACC);
    } else {
      uint16_t c = (col >= 5) ? C_DIM : C_TXT;                // 周末灰显
      txtCenter(ds, cx, cy, 11, c, C_BG);
    }
    if (++col > 6) { col = 0; row++; }
  }
  pushScreen();
}

// ============================== 第4页：天气 =================================
// 数据来自 PC 端 monitor.py（Open-Meteo 免费接口，无需密钥）。
// 屏幕小，只放最关键信息：城市 + 大图标 + 大号温度 + 天气描述 + 湿度/风速/体感。
enum WIcon { W_SUN, W_MOON, W_CLOUD, W_OVERCAST, W_FOG, W_RAIN, W_SNOW, W_THUNDER };

// WMO 天气代码 -> 图标类型；night 用于区分晴天的太阳/月亮
static int wmoToIcon(int code, bool night) {
  if (code == 0) return night ? W_MOON : W_SUN;
  if (code == 1) return night ? W_MOON : W_CLOUD;   // 大致晴朗
  if (code == 2) return W_CLOUD;                     // 局部多云
  if (code == 3) return W_OVERCAST;                  // 阴
  if (code == 45 || code == 48) return W_FOG;        // 雾
  if (code >= 51 && code <= 57) return W_RAIN;       // 毛毛雨
  if (code >= 61 && code <= 67) return W_RAIN;       // 雨
  if (code >= 80 && code <= 82) return W_RAIN;       // 阵雨
  if (code >= 71 && code <= 77) return W_SNOW;       // 雪
  if (code >= 85 && code <= 86) return W_SNOW;       // 阵雪
  if (code >= 95) return W_THUNDER;                  // 雷暴
  return W_CLOUD;
}
static const char* wmoToText(int code) {
  switch (code) {
    case 0:  return "Clear";
    case 1:  return "Mainly clear";
    case 2:  return "Partly cloudy";
    case 3:  return "Overcast";
    case 45: case 48: return "Fog";
    case 51: case 53: case 55: return "Drizzle";
    case 56: case 57: return "Freezing drizzle";
    case 61: return "Light rain";
    case 63: return "Rain";
    case 65: return "Heavy rain";
    case 66: case 67: return "Freezing rain";
    case 71: return "Light snow";
    case 73: return "Snow";
    case 75: return "Heavy snow";
    case 77: return "Snow grains";
    case 80: case 81: case 82: return "Rain showers";
    case 85: case 86: return "Snow showers";
    case 95: return "Thunderstorm";
    case 96: case 99: return "Thunderstorm hail";
    default: return "Unknown";
  }
}

// 中文天气描述（WMO 代码 → 简练中文）
static const char* wmoToTextCn(int code) {
  switch (code) {
    case 0:  return "晴";
    case 1:  return "晴间多云";
    case 2:  return "多云";
    case 3:  return "阴";
    case 45: case 48: return "雾";
    case 51: case 53: case 55: return "毛毛雨";
    case 56: case 57: return "冻雨";
    case 61: return "小雨";
    case 63: return "中雨";
    case 65: return "大雨";
    case 66: case 67: return "冻雨";
    case 71: return "小雪";
    case 73: return "雪";
    case 75: return "大雪";
    case 77: return "雪粒";
    case 80: case 81: case 82: return "阵雨";
    case 85: case 86: return "阵雪";
    case 95: return "雷阵雨";
    case 96: case 99: return "雷阵雨";
    default: return "未知";
  }
}

// 纯中文串宽度（含字间距），仅用于排版计算，不绘制
static int cnStrW(const char* s) {
  int n = 0;
  for (const char* p = s; *p; ) {
    if ((unsigned char)*p >= 0x80) { n++; p += 3; } else p++;
  }
  return n * (WCN_W + 2);
}
// 居中绘制纯中文串（天气描述用），垂直按 16px 字模居中
static void txtCnCenter(const char* s, int cx, int y, uint16_t color) {
  int n = 0;
  for (const char* p = s; *p; ) {
    if ((unsigned char)*p >= 0x80) { n++; p += 3; } else p++;
  }
  int w = n * WCN_W + (n - 1) * 2;
  drawCnStr(s, cx - w / 2, y - WCN_H / 2, color);
}

// 一朵云：三个圆 + 圆角底座，色调克制（DIM 灰）
static void drawCloud(int cx, int cy, int r, uint16_t c) {
  sprite.fillCircle(cx - r * 0.45, cy,            r * 0.50, c);
  sprite.fillCircle(cx + r * 0.45, cy,            r * 0.50, c);
  sprite.fillCircle(cx,            cy - r * 0.25,  r * 0.55, c);
  sprite.fillRoundRect(cx - r * 0.85, cy, (int)(r * 1.7), (int)(r * 0.7), (int)(r * 0.3), c);
}

// 在 (cx,cy) 画边长约 s 的天气图标；云灰、太阳/月亮/雨用强调或对比色
static void drawWeatherIcon(int type, int cx, int cy, int s) {
  int r = s / 2;
  switch (type) {
    case W_SUN: {
      sprite.fillCircle(cx, cy, (int)(r * 0.55), C_ACC);
      for (int i = 0; i < 8; i++) {
        float a = i * PI / 4;
        int x1 = cx + (int)(cosf(a) * r * 0.72), y1 = cy + (int)(sinf(a) * r * 0.72);
        int x2 = cx + (int)(cosf(a) * r * 0.95), y2 = cy + (int)(sinf(a) * r * 0.95);
        sprite.drawLine(x1, y1, x2, y2, C_ACC);
      }
      break;
    }
    case W_MOON: {
      sprite.fillCircle(cx, cy, (int)(r * 0.60), C_ACC);
      sprite.fillCircle(cx + (int)(r * 0.32), cy - (int)(r * 0.12), (int)(r * 0.55), C_BG); // 挖月牙
      break;
    }
    case W_CLOUD: {
      drawCloud(cx, cy, (int)(r * 0.95), C_DIM);
      sprite.fillCircle(cx + (int)(r * 0.55), cy - (int)(r * 0.50), (int)(r * 0.22), C_ACC); // 露出小太阳
      break;
    }
    case W_OVERCAST: {
      drawCloud(cx, cy + (int)(r * 0.20), (int)(r * 0.70), C_DIM);
      drawCloud(cx, cy - (int)(r * 0.15), (int)(r * 0.85), C_DIM);
      break;
    }
    case W_FOG: {
      drawCloud(cx, cy - (int)(r * 0.40), (int)(r * 0.80), C_DIM);
      for (int i = -1; i <= 2; i++)
        sprite.drawLine(cx - (int)(r * 0.7), cy + i * (int)(r * 0.28),
                        cx + (int)(r * 0.7), cy + i * (int)(r * 0.28), C_DIM);
      break;
    }
    case W_RAIN: {
      drawCloud(cx, cy - (int)(r * 0.35), (int)(r * 0.85), C_DIM);
      for (int i = -1; i <= 1; i++) {
        int xx = cx + i * (int)(r * 0.40);
        sprite.drawLine(xx, cy + (int)(r * 0.15), xx - 3, cy + (int)(r * 0.60), C_ACC);
      }
      break;
    }
    case W_SNOW: {
      drawCloud(cx, cy - (int)(r * 0.35), (int)(r * 0.85), C_DIM);
      for (int i = -1; i <= 1; i++)
        sprite.fillCircle(cx + i * (int)(r * 0.40), cy + (int)(r * 0.45), 2, C_TXT);
      break;
    }
    case W_THUNDER: {
      drawCloud(cx, cy - (int)(r * 0.35), (int)(r * 0.85), C_DIM);
      int bx = cx, by = cy + (int)(r * 0.10);
      sprite.fillTriangle(bx - 4, by,     bx + 4, by,     bx, by + 6,  C_WARN);
      sprite.fillTriangle(bx - 2, by + 6, bx + 4, by + 6, bx, by + 12, C_WARN);
      break;
    }
  }
}

static void drawWeatherHeader() {
  sprite.fillRect(0, 0, SCR_W, HEAD_H, C_HEAD);
  // 城市名：汉字字库齐全就画中文，否则回退英文，避免缺字乱码
  if (st.wCity[0] && cityCnAllFound(st.wCity)) {
    drawCityCn(st.wCity, 4, (HEAD_H - CCN_H) / 2, C_TXT);
  } else {
    const char* city = st.wCityEn[0] ? st.wCityEn : "WEATHER";
    txtLeft(city, 4, HEAD_H / 2, 12, C_TXT, C_HEAD);
  }
  bool stale = !hasData || (millis() - lastPkt > 5000);
  txtRight(stale ? "--:--" : st.time, 156, HEAD_H / 2, 8, C_DIM, C_HEAD);
  sprite.drawLine(0, HEAD_H, SCR_W, HEAD_H, C_LINE);
  drawPageDots();
}

static void drawWeatherPage() {
  sprite.fillScreen(C_BG);
  if (!hasData) { drawNoData(); pushScreen(); return; }
  drawWeatherHeader();

  if (!st.wHave) {
    txtCnCenter("无数据", SCR_W / 2, 84, C_DIM);
    pushScreen();
    return;
  }

  int hour = (st.time[0] - '0') * 10 + (st.time[1] - '0');
  bool night = (hour >= 19 || hour < 6);

  // 第一行：左侧大图标 + 右侧超大温度（苹果风左右排布）
  // 图标下移并缩小，避免云朵顶到顶栏（0~17）造成顶部闪烁
  drawWeatherIcon(wmoToIcon(st.wCode, night), 40, 46, 24);

  char tbuf[8];
  snprintf(tbuf, sizeof(tbuf), "%d", (int)(st.wTemp + (st.wTemp >= 0 ? 0.5f : -0.5f)));
  sprite.setFont(&lgfx::fonts::Font2);
  sprite.setTextSize(3);
  int nw = sprite.textWidth(tbuf);
  int startX = 150 - (nw + 16);       // 温度块整体右对齐到 x=150
  int numY = 46 - 24;                 // Font2×3 = 48 高，中心 46
  sprite.setTextColor(C_TXT, C_BG);
  sprite.setCursor(startX, numY);
  sprite.print(tbuf);
  sprite.fillCircle(startX + nw + 3, numY + 6, 3, C_TXT);   // °
  sprite.setTextSize(1);
  sprite.setCursor(startX + nw + 8, numY + 30);
  sprite.print("C");
  sprite.setFont(&lgfx::fonts::Font0);   // 复位文字状态，避免大字号带进后续 txt*
  sprite.setTextSize(1);

  // 天气描述（中文，灰，垂直居中）—— 整体上移 3mm（≈13px）
  txtCnCenter(wmoToTextCn(st.wCode), SCR_W / 2, 69, C_DIM);

  // 当日最高/最低（中文标签 + 数字）。必须用 drawCnStr 的返回值推进，
  // 否则双字标签宽度算错，数字会压在第二个汉字上叠在一起。
  char ht[8], lt[8];
  snprintf(ht, sizeof(ht), "%d", (int)(st.wHi + 0.5f));
  snprintf(lt, sizeof(lt), "%d", (int)(st.wLo + 0.5f));
  int hlY = 83;   // 整体上移 3mm（≈13px）
  int segW = cnStrW("最高") + sprite.textWidth(ht) + 10
           + cnStrW("最低") + sprite.textWidth(lt);
  int x = (SCR_W - segW) / 2;
  sprite.setTextColor(C_DIM, C_BG); x += drawCnStr("最高", x, hlY, C_DIM);
  sprite.setTextColor(C_TXT, C_BG); sprite.setCursor(x, hlY); sprite.print(ht); x += sprite.textWidth(ht) + 10;
  sprite.setTextColor(C_DIM, C_BG); x += drawCnStr("最低", x, hlY, C_DIM);
  sprite.setTextColor(C_TXT, C_BG); sprite.setCursor(x, hlY); sprite.print(lt);

  // 底部副指标：湿度 / 风速（中文标签 + 数字）
  char hum[12], wnd[12];
  if (st.wHum >= 0) snprintf(hum, sizeof(hum), "%d%%", st.wHum); else strcpy(hum, "--");
  snprintf(wnd, sizeof(wnd), "%d", (int)(st.wWind + 0.5f));
  int subY = 101;   // 整体上移 3mm（≈13px）
  int segW2 = cnStrW("湿度") + sprite.textWidth(hum) + 10
            + cnStrW("风速") + sprite.textWidth(wnd);
  int x2 = (SCR_W - segW2) / 2;
  sprite.setTextColor(C_DIM, C_BG); x2 += drawCnStr("湿度", x2, subY, C_DIM);
  sprite.setTextColor(C_TXT, C_BG); sprite.setCursor(x2, subY); sprite.print(hum); x2 += sprite.textWidth(hum) + 10;
  sprite.setTextColor(C_DIM, C_BG); x2 += drawCnStr("风速", x2, subY, C_DIM);
  sprite.setTextColor(C_TXT, C_BG); sprite.setCursor(x2, subY); sprite.print(wnd);

  pushScreen();
}

// ============================== 第1页：总览（《我的世界》主题） ==============
// 视觉规格全部取自 MC 官方：16 色格式化调色板 / GUI 灰阶 / 经验条绿 #80FF20。
// 三条结构规则（比色值更关键）：
//   ① 立体边框 —— 凸起=上/左亮、下/右暗；凹陷反过来（MC 里所有 GUI 元素都遵守）
//   ② 文字带右下 1px 投影
//   ③ 方块图标嵌在物品栏式凹槽里
// 字体是 5x7 点阵（见 mc_theme.h）：本页内容全 ASCII，不需要中文字库。
static const uint16_t MCUI_LBL_SH = RGB(0x1A, 0x1A, 0x1A);  // 标签投影（与设计稿同值）

// MC 顶栏（深色面板条 + 方块页码）已按用户要求移除：状态页顶部不再画页面条，
// 顶部留为背景色，时钟带上移贴近顶部。SPI 端点安全带仍由 flipBuf180() 兜底。



// 一行指标：凹槽方块图标 + 标签 + 分段经验条 + 加粗主值 + 灰副值
static void drawMcRow(int idx, const uint16_t* icon, const char* label, int pct,
                      const char* val, const char* aux, uint16_t base) {
  const int rh = ROW_H, top = BODY_TOP + idx * rh;
  const int c1 = top + 4;    // 主行：标签 / 条 / 主值
  const int c2 = top + 14;   // 副行：副值

  mcIcon(icon, 2, top + 4);
  mcStr(label, 18, c1, MCUI_GRAY, 1, MCUI_LBL_SH, false);
  mcXpBar(52, c1, 76, 6, pct, mcLoadColor(pct, base));
  mcStrRight(val, 156, c1, MCUI_WHITE, 1, MCUI_SHADOW, true);
  if (aux[0]) mcStr(aux, 52, c2, MCUI_DGRAY, 1, 0, false);
}

static void drawOverview() {
  bool stale = !hasData || (millis() - lastPkt > 5000);
  sprite.fillScreen(MCUI_BG);
  if (!hasData) { drawNoData(MCUI_BG); pushScreen(); return; }
  // ---- 时钟带：大时钟 2 倍字 + 日期/开机时长 1 倍字横排其后、底边对齐。
  // 时钟 2x 占 y=3..16（7px 字形 ×2），日期 1x 占 y=10..16 → 底边同在 y=16，观感是同一横行。
  // 下移 2px 的原因：逻辑 y=0..2 必须留成纯背景（EDGE_TOP=3），否则时钟顶部压在撕裂带里，
  // 每秒跳秒时会被 SPI 推屏/面板扫描的时序冲突切成可见闪烁。
  mcStr(stale ? "--:--" : st.time, 2, 3, MCUI_WHITE, 2, MCUI_SHADOW, false);
  char dt[28];
  snprintf(dt, sizeof(dt), "%s %s", st.date, stale ? "OFF" : st.uptime);
  mcStr(dt, 66, 10, stale ? MCUI_RED : MCUI_GRAY, 1, MCUI_LBL_SH, false);
  // ---- 顶带下沿的 MC 凹槽分隔线（暗线 + 黑缝，共 2px）：把「时钟区」与「指标区」分开，
  // 取代已被移除的顶栏面板条。属静态内容，落在撕裂带里也不会闪。
  sprite.writeFastHLine(0, 17, SCR_W, MCUI_LO);
  sprite.writeFastHLine(0, 18, SCR_W, MCUI_BLACK);

  char buf[16], aux[20];
  // CPU（基色 = MC 青 §b）
  int cp = st.cpu >= 0 ? st.cpu : 0;
  snprintf(buf, sizeof(buf), "%d%%", cp);
  snprintf(aux, sizeof(aux), "%dC", dispTemp(st.cpuT > -900 ? st.cpuT : 0));
  drawMcRow(0, MC_ICON_CPU, "CPU", cp, buf, aux, MCUI_AQUA);
  // RAM（金 §6）
  int mp = st.mem >= 0 ? st.mem : 0;
  snprintf(buf, sizeof(buf), "%d%%", mp);
  snprintf(aux, sizeof(aux), "%.1fG", st.memGB >= 0 ? st.memGB : 0);
  drawMcRow(1, MC_ICON_RAM, "RAM", mp, buf, aux, MCUI_GOLD);
  // NET（无百分比含义：经验条留空槽，主值=下行、副值=上行）
  char dn[12], up[12];
  fmtRate(st.dnKB, dn, sizeof(dn));
  fmtRate(st.upKB, up, sizeof(up));
  snprintf(aux, sizeof(aux), "^%s", up);
  drawMcRow(2, MC_ICON_NET, "NET", -1, dn, aux, MCUI_BLUE);
  // GPU（品红 §d）
  int gp = st.gpu >= 0 ? st.gpu : 0;
  snprintf(buf, sizeof(buf), "%d%%", gp);
  snprintf(aux, sizeof(aux), "%dC", dispTemp(st.gpuT > -900 ? st.gpuT : 0));
  drawMcRow(3, MC_ICON_GPU, "GPU", gp, buf, aux, MCUI_LPURPLE);
  // DSK（绿 §a）
  int dp = st.disk >= 0 ? st.disk : 0;
  snprintf(buf, sizeof(buf), "%d%%", dp);
  snprintf(aux, sizeof(aux), "%.0fG", st.dskFreeGB >= 0 ? st.dskFreeGB : 0);
  drawMcRow(4, MC_ICON_DSK, "DSK", dp, buf, aux, MCUI_GREEN);

  pushScreen();
}

// ============================== 日期工具 ====================================
// Sakamoto 算法：返回 0=周日..6=周六
static int dayOfWeek(int y, int m, int d) {
  static const int t[12] = {0,3,2,5,0,3,5,1,4,6,2,4};
  if (m < 3) y -= 1;
  return (y + y/4 - y/100 + y/400 + t[m-1] + d) % 7;
}
static int daysInMonth(int y, int m) {
  static const int d[12] = {31,28,31,30,31,30,31,31,30,31,30,31};
  if (m == 2 && ((y % 4 == 0 && y % 100 != 0) || y % 400 == 0)) return 29;
  return (m >= 1 && m <= 12) ? d[m-1] : 30;
}

// ============================== 渲染分发 ====================================
static void render() {
  if      (curView == VIEW_OVERVIEW) drawOverview();
  else if (curView == VIEW_CLOCK)    drawClockPage();
  else if (curView == VIEW_CALENDAR) drawCalendarPage();
  else                               drawWeatherPage();
}

// ============================== 串口解析 ====================================
// 用固定容量文档：解析过程零堆分配，杜绝长期运行的内存碎片
static void handleLine(const char* line) {
  // ArduinoJson 7 把 StaticJsonDocument 标了 deprecated，官方推荐 JsonDocument，
  // 但后者走堆分配，1Hz 常年跑下去迟早碎片。这里坚持用静态文档并局部屏蔽警告。
  // 容量按「字段数 × 每成员约 16B + 键值字符串」估：天气字段加进来后 512 已不够，
  // 会返回 NoMemory 让整帧解析失败。给到 1024 留一倍余量（占用 loop 任务栈）。
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
  StaticJsonDocument<1024> doc;
#pragma GCC diagnostic pop
  DeserializationError err = deserializeJson(doc, line);
  if (err) { rxBad++; return; }

  st.cpu   = doc["c"]  | -1;
  st.mem   = doc["m"]  | -1;
  st.memGB = doc["mf"] | -1.0f;
  st.cpuT  = doc["t"]  | -999;
  st.gpu   = doc["g"]  | -1;
  st.gpuT  = doc["gt"] | -999;
  st.upKB  = doc["u"]  | -1.0f;
  st.dnKB  = doc["d"]  | -1.0f;
  st.disk  = doc["dk"] | -1;
  st.dskFreeGB = doc["df"] | -1.0f;

  strlcpy(st.time,   doc["tm"] | "--:--", sizeof(st.time));
  strlcpy(st.date,   doc["dt"] | "",      sizeof(st.date));
  strlcpy(st.uptime, doc["up"] | "",      sizeof(st.uptime));
  st.year  = doc["yr"] | 0;
  st.month = doc["mo"] | 0;
  st.day   = doc["dy"] | 0;
  st.sec   = doc["ss"] | 0;

  // 天气页字段（PC 端 Open-Meteo 下发；缺失时保持「未就绪」状态）
  int wc = doc["wc"] | -1;
  if (wc >= 0) {
    st.wHave = true;
    st.wTemp = doc["wt"] | 0.0f;
    st.wCode = wc;
    st.wFeel = doc["wf"] | 0.0f;
    st.wHum  = doc["wh"] | -1;
    st.wWind = doc["ww"] | 0.0f;
    st.wHi   = doc["whi"] | 0.0f;
    st.wLo   = doc["wlo"] | 0.0f;
    strlcpy(st.wCity, doc["wct"] | "", sizeof(st.wCity));
    strlcpy(st.wCityEn, doc["wce"] | "", sizeof(st.wCityEn));
  }

  // 数字垂直偏移（"do"，正=上移）与拉伸（"ds"，100=原样）：任一变化都重建位图（约 1ms）。
  // 偏移超限时拉伸中心会按墨迹高度动态贴边，不会再把数字裁掉。
  int dy = doc["do"] | FC_DIG_DY_DEF;
  if (dy < -15) dy = -15;
  if (dy >  15) dy =  15;
  int sq = doc["ds"] | 170;
  if (sq < 100) sq = 100;
  if (sq >  220) sq = 220;
  if (dy != gDigDy || sq != gStretch) {
    gDigDy   = dy;
    gStretch = sq;
    buildFlipGlyphs();
    newData = true;
  }

  hasData = true;
  lastPkt = millis();
  rxOk++;
  newData = true;
  syncClockFromPC();        // 用 PC 带来的真实时间对齐内部时钟
  updateFlipDigits(true);   // 秒/分/时变化即刻打上翻页动画起点
}

// ============================== 几何自检图案 ================================
// 把它把「屏幕模块物理插歪」和「驱动配置导致画面倾斜」彻底区分开：
//   边框四边完整      -> offset 正确，缺边就是偏移没配准
//   网格线正交不斜    -> 行列寻址正确，斜就是 GRAM 宽高配反
//   圆是正圆不是椭圆  -> 像素纵横比 1:1，变椭圆就是宽高配错
//   角标 1/2/3/4 位置 -> 验证旋转方向（1 左上 2 右上 3 左下 4 右下）
void drawSelfTestPattern() {
  sprite.deleteSprite();
  if (!sprite.createSprite(gW, gH)) {
    lcd.fillScreen(RGB(0xF0, 0x40, 0x40));
    lcd.setFont(&lgfx::fonts::Font0);
    lcd.setTextColor(RGB(0xFF, 0xFF, 0xFF), RGB(0xF0, 0x40, 0x40));
    lcd.setCursor(6, 58);
    lcd.print("SPRITE FAIL");
    return;
  }
  sprite.fillSprite(C_BG);

  const uint16_t C_GRID = RGB(0x40, 0x48, 0x58);
  const uint16_t C_EDGE = RGB(0xFF, 0xFF, 0xFF);
  const uint16_t C_CIRC = RGB(0x00, 0xE0, 0xFF);
  const uint16_t C_CROS = RGB(0xFF, 0x40, 0x40);
  const uint16_t C_LBL  = RGB(0xFF, 0xE0, 0x00);

  int step = 16;
  for (int x = 0; x <= gW; x += step) sprite.drawLine(x, 0, x, gH, C_GRID);
  for (int y = 0; y <= gH; y += step) sprite.drawLine(0, y, gW, y, C_GRID);
  sprite.drawLine(gW / 2, 0, gW / 2, gH, C_CROS);
  sprite.drawLine(0, gH / 2, gW, gH / 2, C_CROS);
  sprite.drawCircle(gW / 2, gH / 2, gW >= gH ? 40 : 30, C_CIRC);
  sprite.drawCircle(gW / 2, gH / 2, 20, C_CIRC);
  sprite.drawRect(0, 0, gW, gH, C_EDGE);

  sprite.setFont(&lgfx::fonts::Font2);
  sprite.setTextColor(C_EDGE, C_BG);
  sprite.setCursor(4, 4);             sprite.print("1");
  sprite.setCursor(gW - 14, 4);       sprite.print("2");
  sprite.setCursor(4, gH - 20);       sprite.print("3");
  sprite.setCursor(gW - 14, gH - 20); sprite.print("4");

  char lbl[24];
  snprintf(lbl, sizeof(lbl), "CFG %d", gCfg);
  sprite.setTextColor(C_LBL, C_BG);
  sprite.setCursor(gW / 2 - sprite.textWidth(lbl) / 2, gH / 2 - 30);
  sprite.print(lbl);

  snprintf(lbl, sizeof(lbl), "%dx%d o%d,%d r%d",
           CFG_TAB[gCfg][0], CFG_TAB[gCfg][1],
           CFG_TAB[gCfg][4], CFG_TAB[gCfg][5], CFG_TAB[gCfg][6]);
  sprite.setFont(&lgfx::fonts::Font0);
  sprite.setTextColor(C_ACC, C_BG);
  sprite.setCursor(gW / 2 - sprite.textWidth(lbl) / 2, gH / 2 + 10);
  sprite.print(lbl);

  flipBuf180();                   // 与主页面一致：跟随安装方向（角标随之镜像，不影响判读斜屏）
  sprite.pushSprite(0, 0);
}

// ============================== UI 状态机 ==================================
// 极简：只有 ST_MON。短按循环切页（带 170ms 幕布过渡），长按切换时钟页数字字体。
static void handleUi() {
  if (evNext) goPage((ViewPage)(((int)curView + 1) % N_PAGES));   // 循环：总览→时钟→日历→天气→总览
  if (evFont) {
    // 长按：换下一套字体 → 重新烘焙叶片 → 若不在时钟页则跳过去，便于立刻比对。
    gFontIdx = (uint8_t)((gFontIdx + 1) % CLOCK_FONT_COUNT);
    buildFlipGlyphs();
    for (int i = 0; i < 6; i++) FD[i].anim = false;   // 丢弃进行中的翻页动画
    gFontTagT = millis();                            // 屏幕上提示字体名 1.5s
    if (curView != VIEW_CLOCK) goPage(VIEW_CLOCK);
    else                       render();             // 已在时钟页：立即重绘，不等 600ms
  }
}

// ============================== 主程序 ======================================
void setup() {
  // 背光改 PWM 调光（亮度设置用），默认满亮
  ledcSetup(0, 5000, 8);
  ledcAttachPin(PIN_BLK, 0);
  ledcWrite(0, gBright);

  Serial.setRxBufferSize(1024);   // 默认 256，重连瞬间容易积压丢帧
  Serial.begin(115200);
  Serial.setTimeout(0);
  // 启动跟踪：串口是唯一能在「屏不亮」时告诉我们卡在哪一步的通道
  Serial.printf("\n[BOOT] start reset=%d\n", (int)esp_reset_reason());

  lcd.init();
  lcd.setRotation(PANEL_ROT);     // 恒为横屏 1；外壳倒装时 180° 由 flipBuf180() 在像素层完成
  lcd.fillScreen(C_BG);
  gW = lcd.width();
  gH = lcd.height();
  // 旋转号打进日志：设备倒装时不用猜，串口直接能确认固件到底转了多少度
  Serial.printf("[BOOT] lcd %dx%d rot=%d flip180=%d\n", gW, gH, (int)lcd.getRotation(), PANEL_FLIP_180);

  sprite.setColorDepth(16);
  // 160*128*2 = 40KB。分配失败必须看得见，否则只会得到一块无从排查的黑屏
  if (!sprite.createSprite(SCR_W, SCR_H)) {
    lcd.fillScreen(RGB(0xF0, 0x40, 0x40));
    lcd.setFont(&lgfx::fonts::Font0);
    lcd.setTextColor(RGB(0xFF, 0xFF, 0xFF), RGB(0xF0, 0x40, 0x40));
    lcd.setCursor(10, 58);
    lcd.print("SPRITE FAIL");
    for (;;) delay(1000);         // 卡在这，别让问题被后面的逻辑掩盖
  }

  Serial.printf("[BOOT] sprite ok heap=%u\n", (unsigned)ESP.getFreeHeap());

  btnSetup();
  buildFlipGlyphs();      // 预渲染 0-9 的上下半数字位图（翻页时钟用）
  updateFlipDigits(false);
  Serial.printf("[BOOT] glyphs ok heap=%u\n", (unsigned)ESP.getFreeHeap());

#ifdef SELFTEST
  // 自检轮播：依次套用 9 组几何配置，每组停留 2.5s。
  // 屏幕角标 "CFG n" + 参数行 标明当前是第几组。看哪一组画面不斜就报 CFG 号。
  int idx = 0;
  for (;;) {
    gCfg = ((idx % CFG_N) + CFG_N) % CFG_N;
    lcd.applyCfg(gCfg);
    gW = lcd.width();
    gH = lcd.height();
    drawSelfTestPattern();
    Serial.printf("CFG %d  mem %dx%d  panel %dx%d  off %d,%d  rot %d\n",
                  gCfg, CFG_TAB[gCfg][0], CFG_TAB[gCfg][1],
                  CFG_TAB[gCfg][2], CFG_TAB[gCfg][3],
                  CFG_TAB[gCfg][4], CFG_TAB[gCfg][5], CFG_TAB[gCfg][6]);
    delay(2500);
    idx++;
  }
#endif

  render();
  Serial.printf("[BOOT] render done heap=%u\n", (unsigned)ESP.getFreeHeap());
}

// ============================== 主循环 ======================================
// 串口接收用固定缓冲区，绝不在循环里做堆分配（长期运行的碎片就来自这里）。
// 容量必须留足余量：一帧 JSON 会随字段增加而变长（天气 7 个字段 + 中文城市名
// 转义后约 268 字节）。缓冲一旦小于帧长，超长帧会被整条丢掉，表现为
// 「串口在收、但 rxOk 一直 0、屏上永远未连接」——排查时极易误判成硬件问题。
static char   rxBuf[640];
static size_t rxLen = 0;

static void pumpSerial() {
  while (Serial.available()) {
    int c = Serial.read();
    if (c < 0) break;
    if (c == '\n') {
      if (rxLen) { rxBuf[rxLen] = '\0'; handleLine(rxBuf); rxLen = 0; }
    } else if (c != '\r') {
      // 超长帧直接丢弃并复位，避免半包粘在一起越积越长
      if (rxLen < sizeof(rxBuf) - 1) rxBuf[rxLen++] = (char)c;
      else                           rxLen = 0;
    }
  }
}

static uint32_t lastDraw = 0;

void loop() {
  pumpSerial();
  btnPoll();
  tickClock();   // 离线时内部时钟继续走时
  // PC 离线（断流超过 OFFLINE_MS）→ 自动跳回时钟页，离线继续走时（边沿触发一次）
  bool online = (millis() - lastPkt <= OFFLINE_MS);
  if (gWasOnline && !online && curView != VIEW_CLOCK) goPage(VIEW_CLOCK);
  gWasOnline = online;
  uint32_t now = millis();

  // 翻页幕布过渡：用 BG 幕布从左锚定向右展开，露出已画好的新页
  if (transActive) {
    if (now - transStart >= TRANS_MS) {
      gPush = true;
      transActive = false;
      render();                       // 收尾：推最终帧
    } else {
      gPush = false;
      render();                       // 把新页画进 sprite（不推送）
      int w = (int)(SCR_W * (1.0f - (float)(now - transStart) / TRANS_MS));
      // 180° 软件翻转会把缓冲左右镜像 → 幕布画在逻辑右侧，屏上才会出现在左侧，
      // 观感仍是「幕布自左向右收缩、新页自右向左展开」，与翻转前一致。
      sprite.fillRect(SCR_W - w, 0, w, SCR_H, C_BG);   // 幕布：已展开部分露出新页
      flipBuf180();
      sprite.pushSprite(0, 0);
    }
    delay(2);
    return;
  }

  if (evNext) handleUi();

  if (uiState == ST_MON && curView == VIEW_CLOCK) {
    updateFlipDigits(true);   // 在线=随帧同步；离线=内部时钟走时，秒变即翻页
    // 时钟页：翻页动画期间按 25fps 重绘，静止时跟随数据帧（1Hz）
    bool anim = false;
    for (int i = 0; i < 6; i++) if (FD[i].anim) { anim = true; break; }
    if (anim) {
      if (now - lastClockDraw >= FLIP_FPS) { lastClockDraw = now; render(); }
    } else if (newData || (now - lastClockDraw > 600)) {
      newData = false;
      lastClockDraw = now;
      render();
    }
  } else {
    // 只有「来了新数据」或「距上次重绘满刷新间隔」才刷屏。
    // 数据是 1Hz 的，无脑重绘会让大半的 SPI 传输在推重复画面。
    bool need = newData || (now - lastDraw >= gRefreshMs);
    if (need) {
      newData  = false;
      lastDraw = now;
      render();
    }
  }

  // 心跳：3 秒一行，报当前页 / 累计收帧 / 坏帧 / 是否有数据 / 剩余内存。
  // 用来在「屏幕不亮或不更新」时区分「没收到数据」和「收到了但没画出来」。
  static uint32_t lastHb = 0;
  if (now - lastHb >= 3000) {
    lastHb = now;
    Serial.printf("[HB] view=%d rx=%lu bad=%lu data=%d heap=%u\n",
                  (int)curView, (unsigned long)rxOk, (unsigned long)rxBad,
                  (int)hasData, (unsigned)ESP.getFreeHeap());
  }

  delay(2);   // 让出 CPU，避免 loop 空转把 IDLE 饿死触发任务看门狗
}
