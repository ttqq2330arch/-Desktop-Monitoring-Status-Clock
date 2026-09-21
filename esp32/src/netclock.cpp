#include "netclock.h"

#include <WiFi.h>
#include <Preferences.h>
#include <time.h>

// ---- 可调参数 -------------------------------------------------------------
static const uint32_t NC_BOOT_DELAY = 3000;      // 开机后多久才开始抢 WiFi（先让首帧画完）
static const uint32_t NC_WIFI_TO    = 15000;     // 单个 SSID 的连接超时
static const uint32_t NC_SNTP_TO    = 12000;     // 连上后等 SNTP 结果的超时
static const uint32_t NC_FAIL_WAIT  = 300000;    // 全部失败后的重试间隔（5 分钟）
static const uint32_t NC_REFRESH    = 21600000;  // 已对时后多久重新校准（6 小时）

static const int    NC_TZ_SEC = 8 * 3600;        // 中国 UTC+8（无夏令时）
static const char*  NC_NTP1   = "ntp.aliyun.com";
static const char*  NC_NTP2   = "cn.pool.ntp.org";
static const char*  NC_NTP3   = "ntp.tencent.com";

static const char*  NC_NS      = "netclk";       // NVS 命名空间
static const int    NC_MAX_CRED = 2;             // 最多记住 2 组（家里主/备路由器）

// ---- 内部状态 -------------------------------------------------------------
static Preferences gPrefs;
static bool     gReady  = false;
static uint32_t gBootMs = 0;

static char gSsid[NC_MAX_CRED][33];
static char gPass[NC_MAX_CRED][65];
static int  gCredN = 0;

enum NCState { NC_IDLE, NC_CONNECT, NC_SNTP, NC_OK, NC_FAIL };

static NCState  gState    = NC_IDLE;
static uint32_t gT0       = 0;      // 当前阶段起点
static int      gTry      = 0;      // 正在尝试第几组凭据
static bool     gForce    = false;  // 手动请求对时
static bool     gEver     = false;  // 是否成功对过时
static uint32_t gLastOk   = 0;      // 上次成功对时的 millis()
static uint32_t gNextTry  = 0;      // NC_FAIL 状态下的重试时刻

static bool gHasTime = false;       // 有一次未取走的结果
static int  gTy, gTmo, gTd, gTh, gTmi, gTs;

// ---- 前置声明（netClearCredentials 定义在实现之前，先声明）----------------
static void ncWifiOffQuiet();

// ---- 凭据存取 -------------------------------------------------------------
static void ncLoad() {
  gCredN = 0;
  if (!gPrefs.begin(NC_NS, true)) return;
  for (int i = 0; i < NC_MAX_CRED; i++) {
    char ks[8], kp[8];
    snprintf(ks, sizeof(ks), "s%d", i + 1);
    snprintf(kp, sizeof(kp), "p%d", i + 1);
    String s = gPrefs.getString(ks, "");
    if (s.length() == 0) continue;
    String p = gPrefs.getString(kp, "");
    strncpy(gSsid[gCredN], s.c_str(), sizeof(gSsid[0]) - 1);
    gSsid[gCredN][sizeof(gSsid[0]) - 1] = '\0';
    strncpy(gPass[gCredN], p.c_str(), sizeof(gPass[0]) - 1);
    gPass[gCredN][sizeof(gPass[0]) - 1] = '\0';
    gCredN++;
  }
  gPrefs.end();
}

bool netConfigured() { return gCredN > 0; }
bool netEverSynced() { return gEver; }
uint32_t netSinceLastSync(uint32_t now) { return gEver ? (now - gLastOk) : 0xFFFFFFFFu; }

bool netAddCredential(const char* ssid, const char* pass) {
  if (!ssid) return false;
  size_t n = strlen(ssid);
  if (n == 0 || n > 32) return false;                  // SSID 最长 32 字节
  if (pass && strlen(pass) > 64) return false;         // WPA2 口令最长 63 + 结尾

  int slot = -1;
  if (!gPrefs.begin(NC_NS, false)) return false;
  for (int i = 0; i < NC_MAX_CRED; i++) {
    char ks[8];
    snprintf(ks, sizeof(ks), "s%d", i + 1);
    String s = gPrefs.getString(ks, "");
    if (s.length() == 0) { if (slot < 0) slot = i; }   // 优先填空位
    else if (s == ssid)  { slot = i; break; }          // 同名则覆盖
  }
  if (slot < 0) slot = 1;                              // 两个都满就覆盖第 2 组，保住第 1 组
  char ks[8], kp[8];
  snprintf(ks, sizeof(ks), "s%d", slot + 1);
  snprintf(kp, sizeof(kp), "p%d", slot + 1);
  gPrefs.putString(ks, ssid);
  gPrefs.putString(kp, pass ? pass : "");
  gPrefs.end();

  ncLoad();
  Serial.printf("[NET] cred saved slot=%d ssid=%s total=%d\n", slot + 1, ssid, gCredN);
  return true;
}

void netClearCredentials() {
  if (gPrefs.begin(NC_NS, false)) {
    gPrefs.clear();
    gPrefs.end();
  }
  gCredN = 0;
  gState = NC_IDLE;
  gNextTry = 0;
  ncWifiOffQuiet();
  Serial.printf("[NET] credentials cleared\n");
}

void netRequestSync() {
  gForce  = true;
  gNextTry = 0;
  Serial.printf("[NET] sync requested\n");
}

// ---- 状态机 ---------------------------------------------------------------
static void ncWifiOffQuiet() {
  if (WiFi.getMode() == WIFI_OFF) return;   // 从未初始化过就别去 disconnect
  WiFi.disconnect(true, true);
  WiFi.mode(WIFI_OFF);
  Serial.println("[NET] wifi off");
}

static void ncAttempt(uint32_t now) {
  WiFi.persistent(false);          // 别让协议栈自己往 NVS 写东西
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(true);             // modem sleep：省电 + 降低对刷屏的干扰
  WiFi.begin(gSsid[gTry], gPass[gTry]);
  gT0    = now;
  gState = NC_CONNECT;
  Serial.printf("[NET] connecting slot=%d ssid=%s\n", gTry + 1, gSsid[gTry]);
}

static void ncNextOrFail(uint32_t now) {
  if (++gTry < gCredN) { ncAttempt(now); return; }
  gState   = NC_FAIL;
  gNextTry = now + NC_FAIL_WAIT;
  Serial.printf("[NET] all attempts failed, retry in %lu s\n",
                (unsigned long)(NC_FAIL_WAIT / 1000));
}

static void ncStart(uint32_t now) {
  gTry = 0;
  ncAttempt(now);
}

void netBegin() {
  gBootMs = millis();
  ncLoad();
  gReady = true;
  Serial.printf("[NET] begin creds=%d\n", gCredN);
}

void netPoll(uint32_t now, bool pcTimeAvailable) {
  if (!gReady) return;
  if (now - gBootMs < NC_BOOT_DELAY) return;

  switch (gState) {
    case NC_IDLE: {
      // 只在「没有 PC 时间源」且「从没对过 或 距上次对时超过 6 小时」时才联网。
      // PC 在线时完全不碰 WiFi：PC 每帧对齐，本来就不需要 NTP。
      bool stale = !gEver || (now - gLastOk >= NC_REFRESH);
      bool need  = gForce || (!pcTimeAvailable && stale);
      if (!need) break;
      gForce = false;
      if (gCredN == 0) {                 // 没配过网：不反复空转，等配置
        gState   = NC_FAIL;
        gNextTry = now + NC_FAIL_WAIT;
        break;
      }
      ncStart(now);
      break;
    }

    case NC_CONNECT: {
      if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("[NET] connected ip=%s rssi=%d\n",
                      WiFi.localIP().toString().c_str(), (int)WiFi.RSSI());
        configTime(NC_TZ_SEC, 0, NC_NTP1, NC_NTP2, NC_NTP3);
        gT0    = now;
        gState = NC_SNTP;
      } else if (now - gT0 > NC_WIFI_TO) {
        Serial.printf("[NET] wifi timeout slot=%d\n", gTry + 1);
        ncWifiOffQuiet();
        ncNextOrFail(now);
      }
      break;
    }

    case NC_SNTP: {
      struct tm tmv;
      if (getLocalTime(&tmv, 0) && (tmv.tm_year + 1900) >= 2020) {
        gTy  = tmv.tm_year + 1900; gTmo = tmv.tm_mon + 1;  gTd = tmv.tm_mday;
        gTh  = tmv.tm_hour;        gTmi = tmv.tm_min;      gTs = tmv.tm_sec;
        gHasTime = true;
        gEver    = true;
        gLastOk  = now;
        Serial.printf("[NET] SNTP ok %04d-%02d-%02d %02d:%02d:%02d  heap=%u\n",
                      gTy, gTmo, gTd, gTh, gTmi, gTs, (unsigned)ESP.getFreeHeap());
        ncWifiOffQuiet();                 // 拿到就关，之后靠内部时钟走
        gState = NC_OK;
      } else if (now - gT0 > NC_SNTP_TO) {
        Serial.printf("[NET] SNTP timeout slot=%d\n", gTry + 1);
        ncWifiOffQuiet();
        ncNextOrFail(now);
      }
      break;
    }

    case NC_OK:
      if (now - gLastOk >= NC_REFRESH) { gState = NC_IDLE; }   // 到期后由 IDLE 分支重新触发
      break;

    case NC_FAIL:
      if (gNextTry && now >= gNextTry) { gNextTry = 0; gState = NC_IDLE; }
      break;
  }
}

bool netTakeTime(int& y, int& mo, int& d, int& h, int& mi, int& s) {
  if (!gHasTime) return false;
  y = gTy; mo = gTmo; d = gTd; h = gTh; mi = gTmi; s = gTs;
  gHasTime = false;
  return true;
}

const char* netStatusText() {
  if (gCredN == 0)                 return "NO CFG";
  switch (gState) {
    case NC_CONNECT:               return "LINKING";
    case NC_SNTP:                  return "SYNCING";
    case NC_FAIL:                  return "NO NET";
    default: break;
  }
  return gEver ? "WIFI OK" : "NO TIME";
}

void netPrintStatus(Stream& out) {
  const char* st = "IDLE";
  switch (gState) {
    case NC_CONNECT: st = "CONNECT"; break;
    case NC_SNTP:    st = "SNTP";    break;
    case NC_OK:      st = "OK";      break;
    case NC_FAIL:    st = "FAIL";    break;
    default: break;
  }
  out.printf("[NET] state=%s creds=%d ever=%d status=%s",
             st, gCredN, (int)gEver, netStatusText());
  for (int i = 0; i < gCredN; i++) out.printf(" slot%d=%s", i + 1, gSsid[i]);
  if (gEver) out.printf(" lastok=%lu s ago", (unsigned long)((millis() - gLastOk) / 1000));
  out.print("\n");
}
