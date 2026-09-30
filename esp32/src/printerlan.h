// 离线局域网打印机轮询模块
// =====================================================================
// 设计目标（与用户需求一致）：
//   · PC 连着（在线）→ 打印机数据走串口（UART），本模块完全不动、不碰 WiFi。
//   · PC 没连（离线）→ ESP32 自己用 WiFi 去问打印机，填回 pr[2]。
//   · 两者互不干涉：渲染层只读 pr[2]，根本不感知数据来自串口还是局域网；
//     数据源由「是否在线」单一判定门控，天然互斥、不会同时写。
//
// slot 0 = 创想三维（Creality Moonraker HTTP :7125，无账号）
// slot 1 = 纵维立方（Anycubic Kobra X 局域网 MQTT :9883 + :18910 发现 + AES 解密）
//
// 配置存 NVS（命名空间 "prn"），绝不进源码；串口命令 / 网页均可写。
#pragma once
#include <Arduino.h>

// 打印机实况（串口与局域网两种来源共用这一份）
struct PStat {
  bool   have  = false;    // 是否已拿到过一次数据
  char   name[16] = "";    // 打印机名（ASCII）
  int    state = 0;        // 0离线 1空闲 2打印中
  float  hot   = -1;       // 热端温度 °C（-1 未知）
  float  bed   = -1;       // 热床温度 °C
  int    prog  = -1;       // 打印进度 %（-1 未知）
  char   file[24] = "";    // 当前文件/任务名（ASCII）
};
extern PStat pr[2];        // 定义在 main.cpp

// 打印机类型
enum { PL_TYPE_CREALITY = 0, PL_TYPE_ANYCUBIC = 1 };

// setup() 里调一次：载入 NVS 配置
void plBegin();

// loop() 里周期调用。online=true 时本模块完全不动作（串口拥有数据）；
// online=false 时才离线轮询局域网打印机。
void plPoll(uint32_t now, bool online);

// 该 slot 是否在 NVS 里启用了离线局域网
bool plCfgEnabled(int slot);

// 配置：slot(0/1) type(0=creality 1=anycubic) ip(点分十进制)。name 可选。
// 返回是否成功（slot 合法 + ip 看起来像 IPv4）。
bool plSetPrinter(int slot, int type, const char* ip, const char* name = nullptr);

// 清空全部离线配置
void plClearConfig();

// 串口日志用：详细状态
void plPrintStatus(Stream& out);

// 该 slot 当前数据来源：0=PC 串口 / 1=离线局域网（供网页状态展示，验证「互不干涉」）
int plSrc(int slot);
