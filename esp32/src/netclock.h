// 独立对时模块 —— 让设备在「不接电脑」时也有正确时间。
//
// 背景：ESP32 的内部 RTC 断电即丢，上电时并不知道现在几点。原固件的时间
// 完全来自 PC 串口帧，所以脱离 PC 后时钟页只能显示 NO DATA。
//
// 做法：用模组自带的 2.4G WiFi 连路由器 -> SNTP 取标准时间 -> 写入内部时钟，
// **拿到时间立刻关掉 WiFi**（省电，且避免 WiFi 任务抢占 CPU 影响 SPI 刷屏）。
// 凭据存在 NVS 里（不是源码里，避免随开源导出泄露），用串口命令写入。
//
// 两条时间源的优先级：PC 串口帧 > NTP。PC 在线时根本不启动联网（PC 每帧对齐，零漂移）。
#pragma once
#include <Arduino.h>

// setup() 里调一次：载入 NVS 凭据并准备联网
void netBegin();

// loop() 里周期调用。pcTimeAvailable = 「当前有 PC 时间源」（在线且已同步过）
// 非阻塞：内部是状态机，单次推进最多几百微秒（WiFi.mode 那一下除外）
void netPoll(uint32_t now, bool pcTimeAvailable);

// 是否已配置过至少一组凭据
bool netConfigured();

// 追加/覆盖一组凭据；返回是否成功
bool netAddCredential(const char* ssid, const char* pass);

// 清空全部凭据并断开
void netClearCredentials();

// 立即请求一次对时（无视 6 小时周期）
void netRequestSync();

// 取出一次成功对时的结果；返回 true 时参数已被填充（取走即清标志）
bool netTakeTime(int& y, int& mo, int& d, int& h, int& mi, int& s);

// 是否成功对过时（哪怕只有一次）
bool netEverSynced();

// 距离上次成功对时过去了多少毫秒（未对过时返回一个很大的值）
uint32_t netSinceLastSync(uint32_t now);

// 给串口日志用：详细状态
void netPrintStatus(Stream& out);

// 给屏幕用：极短状态词（≤4 个汉字位）
const char* netStatusText();

// ---- 网页服务支持（2026-09-24 新增）-------------------------------------
// 默认策略是「对完时立刻关 WiFi」省电。要让设备常驻网页服务时，先调
// netSetWifiHold(true)：此后 WiFi 保持连接（掉线自动重连），且无论 PC 在不在线
// 都会联网。webui 模块只负责 HTTP，连网这件事仍然统一由本模块管，避免两处抢 WiFi。
void netSetWifiHold(bool hold);

// WiFi 是否已连上（网页服务可用）
bool netWifiUp();

// 本机 IP 字符串（未连上时返回 "0.0.0.0"）
String netIpText();

// 凭据读取：让配网页能列出/回填已保存的 WiFi
int  netCredCount();
bool netGetCred(int idx, char* ssid, size_t nSsid, char* pass, size_t nPass);
