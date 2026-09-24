// 设备自带网页服务 —— 手机/平板/电脑浏览器直接打开设备地址看状态，不必开电脑。
//
// 设计取舍：
// ・**不碰 WiFi**：连网/保持/重连统一由 netclock 管（netSetWifiHold(true)），
//   本模块只管 HTTP。避免两个模块抢 WiFi 状态机。
// ・**不依赖主程序内部结构**：状态 JSON 由主程序注册回调填充（webSetStatusFn），
//   webui 不认识 Stats/PStat，将来数据源从「PC 串口帧」换成「云端轮询」时这里不用改。
// ・**页面走 PROGMEM**：HTML/CSS 不占 DRAM，直接 send_P 出网。
#pragma once
#include <Arduino.h>

// 主程序注册的状态填充器：把当前快照写成 JSON 对象串（不含最外层大括号也可，
// 由主程序决定；本模块只负责把它塞进响应体）。
typedef void (*WebStatusFn)(String& json);
void webSetStatusFn(WebStatusFn fn);

void webBegin();              // setup() 里调一次
void webPoll(uint32_t now);   // loop() 里周期调用，非阻塞

bool webReady();              // HTTP 服务是否已在跑（WiFi 连上后才起）

// 打印机凭据：存 NVS（绝不进源码 —— 本工程要开源导出，硬编码必泄露）。
// which: 0 = Anycubic，1 = Creality。未配置返回空串。
String webToken(int which);
