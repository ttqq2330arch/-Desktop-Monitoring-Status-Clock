// 离线局域网打印机轮询实现（见 printerlan.h 的设计说明）
#include "printerlan.h"

#include <Preferences.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <mbedtls/aes.h>
#include <mbedtls/md5.h>
#include <string.h>
#include <strings.h>    // strcasecmp（区分大小写的状态比较）
#include <time.h>       // time()（epochMs 用真实纪元毫秒）

#include "netclock.h"   // netSetLanHold

// =====================================================================
// 配置（NVS 命名空间 "prn"）
//   e0/e1 : 是否启用离线 LAN（0/1）
//   t0/t1 : 类型（0=Creality 1=Anycubic）
//   i0/i1 : IPv4 地址
//   n0/n1 : 显示名（可选，缺省按类型给默认值）
// =====================================================================
static const char* PL_NS = "prn";

struct SlotCfg { bool enabled; int type; char ip[16]; char name[16]; };
static SlotCfg gCfg[2];
static bool     gLoaded = false;
static Preferences gPrefs;
static int      gSrc[2] = { 0, 0 };   // 数据来源：0=PC 串口 1=离线局域网（展示用）

static void loadCfg() {
  gPrefs.begin(PL_NS, true);
  for (int i = 0; i < 2; i++) {
    char ke[8], kt[8], ki[8], kn[8];
    snprintf(ke, sizeof ke, "e%d", i + 1);
    snprintf(kt, sizeof kt, "t%d", i + 1);
    snprintf(ki, sizeof ki, "i%d", i + 1);
    snprintf(kn, sizeof kn, "n%d", i + 1);
    gCfg[i].enabled = gPrefs.getInt(ke, 0) != 0;
    gCfg[i].type    = gPrefs.getInt(kt, i);     // 默认 slot0=Creality slot1=Anycubic
    String ip  = gPrefs.getString(ki, "");
    String nm  = gPrefs.getString(kn, "");
    strncpy(gCfg[i].ip,   ip.c_str(),  sizeof(gCfg[i].ip)   - 1); gCfg[i].ip[sizeof(gCfg[i].ip) - 1]   = 0;
    strncpy(gCfg[i].name, nm.c_str(),  sizeof(gCfg[i].name) - 1); gCfg[i].name[sizeof(gCfg[i].name) - 1] = 0;
  }
  gPrefs.end();
  gLoaded = true;
}

// =====================================================================
// 小工具：base64 解码 / MD5 / AES-128-CBC
// =====================================================================
// 诊断：记录 b64dec 跳过的字符（位置+字符），下次失败时打印
static int  gB64Skips = 0;
static int  gB64SkipAt[5];
static char gB64SkipCh[5];

// ★base64 取值用函数而非手写查表 —— 手写 T[128] 曾因行错位把 '7'/'W' 等正常字符
//  全判成非法（表条目只有 119 个、整体错位），密文解出即废。函数写法不可能错位。
static inline int b64val(char c) {
  if (c >= 'A' && c <= 'Z') return c - 'A';
  if (c >= 'a' && c <= 'z') return c - 'a' + 26;
  if (c >= '0' && c <= '9') return c - '0' + 52;
  if (c == '+') return 62;
  if (c == '/') return 63;
  return -1;
}

static int b64dec(const char* in, uint8_t* out, int outcap) {
  gB64Skips = 0;
  int len = (int)strlen(in), o = 0, acc = 0, bits = 0;
  for (int i = 0; i < len; i++) {
    char c = in[i];
    if (c == '=') break;
    int v = b64val(c);
    if (v < 0) {
      if (gB64Skips < 5) { gB64SkipAt[gB64Skips] = i; gB64SkipCh[gB64Skips] = c; }
      gB64Skips++;
      continue;            // 忽略空白/换行等
    }
    acc = (acc << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      if (o < outcap) out[o++] = (uint8_t)((acc >> bits) & 0xFF);
    }
  }
  return o;
}

static void md5hex(const char* s, char outHex[33]) {
  unsigned char dig[16];
  mbedtls_md5_ret((const unsigned char*)s, strlen(s), dig);
  static const char* hx = "0123456789abcdef";
  for (int i = 0; i < 16; i++) { outHex[i * 2] = hx[dig[i] >> 4]; outHex[i * 2 + 1] = hx[dig[i] & 0xF]; }
  outHex[32] = 0;
}

// 纪元毫秒：系统时间已对上（SNTP 对时 / PC 帧带时间）→ 用真实时间；
// 还没对上（上电头几分钟）→ 用固定基座 + 开机毫秒兜底（打印机只用作防重放，不校准点）。
static uint64_t epochMs() {
  time_t tnow = time(nullptr);
  if (tnow > 1600000000) return (uint64_t)tnow * 1000ULL + (uint64_t)(millis() % 1000);
  return 1700000000000ULL + (uint64_t)millis() * 1000ULL;
}

// AES-128-CBC 解密（mbedtls）。成功返回明文长度（已去 PKCS7），失败返回 -1
static int aesCbcDec(const uint8_t* key16, const uint8_t* iv16,
                     const uint8_t* in, int len, uint8_t* out, int outcap) {
  if (len <= 0 || len % 16) return -1;
  if (outcap < len) return -1;
  mbedtls_aes_context aes;
  mbedtls_aes_init(&aes);
  if (mbedtls_aes_setkey_dec(&aes, key16, 128) != 0) { mbedtls_aes_free(&aes); return -1; }
  uint8_t iv[16]; memcpy(iv, iv16, 16);
  int rc = mbedtls_aes_crypt_cbc(&aes, MBEDTLS_AES_DECRYPT, len, iv, in, out);
  mbedtls_aes_free(&aes);
  if (rc != 0) return -1;
  int pad = out[len - 1];
  if (pad < 1 || pad > 16) return -1;
  return len - pad;
}

// 简单的「像不像 IPv4」校验（四段 0-255）
static bool ipOk(const char* ip) {
  int a, b, c, d, n = -1;
  if (sscanf(ip, "%d.%d.%d.%d%n", &a, &b, &c, &d, &n) != 4) return false;
  if ((size_t)n != strlen(ip)) return false;
  if (a < 0 || a > 255 || b < 0 || b > 255 || c < 0 || c > 255 || d < 0 || d > 255) return false;
  return true;
}

// =====================================================================
// Creality（Moonraker HTTP）
// =====================================================================
static uint32_t gCrT0 = 0;
static const uint32_t CR_PERIOD = 6000;     // 6 秒轮询一次（打印机变化慢）

static void pollCreality(int slot) {
  HTTPClient http;
  String url = String("http://") + gCfg[slot].ip +
               ":7125/printer/objects/query?extruder&heater_bed&print_stats&virtual_sdcard";
  http.begin(url);
  http.setReuse(false);   // keep-alive 关闭：防每请求 ~224B 堆泄漏
  http.setTimeout(5000);
  int code = http.GET();
  if (code != HTTP_CODE_OK) { http.end(); return; }
  String body = http.getString();
  http.end();

  // 容量按 Moonraker 返回估算：status 块约 1KB 上下
  StaticJsonDocument<1536> doc;
  if (deserializeJson(doc, body) != DeserializationError::Ok) return;
  JsonObject r = doc["result"]["status"];
  if (r.isNull()) return;

  PStat& p = pr[slot];
  p.have = true;
  strncpy(p.name, gCfg[slot].name[0] ? gCfg[slot].name : "CREALITY", sizeof(p.name) - 1);
  p.name[sizeof(p.name) - 1] = 0;

  float hot = r["extruder"]["temperature"] | -1.0f;
  float bed = r["heater_bed"]["temperature"] | -1.0f;
  p.hot = (hot < 0) ? -1 : hot;
  p.bed = (bed < 0) ? -1 : bed;

  const char* st = r["print_stats"]["state"] | "standby";
  p.state = (strcmp(st, "printing") == 0 || strcmp(st, "paused") == 0) ? 2 : 1;
  float prog = r["print_stats"]["progress"] | 0.0f;
  p.prog = (int)(prog * 100 + 0.5f);
  if (p.prog < 0) p.prog = -1;
  const char* fn = r["print_stats"]["filename"] | "";
  strncpy(p.file, fn, sizeof(p.file) - 1);
  p.file[sizeof(p.file) - 1] = 0;
}

// =====================================================================
// Anycubic（Kobra X 局域网：:18910 发现 → :9883 MQTT-TLS 客户端证书）
// =====================================================================
enum AcState { AC_IDLE, AC_DISCOVER, AC_CONNECT, AC_RUN, AC_FAIL };
static AcState   gAcSt = AC_IDLE;
static uint32_t  gAcT0 = 0;
static uint32_t  gAcQueryT = 0;
static uint32_t  gAcNextTry = 0;
static int       gAcBackoff = 3;
static char      gAcModel[40] = "";
static char      gAcDev[40] = "";          // ★deviceId 实测 32 字符 —— 曾用 [32] 截掉末位，查询主题拼错打印机就不应答
static char      gAcDid[17] = "";           // 客户端标识（md5("pc-monitor") 前 16 位）
// 凭据需长期存活（setCertificate/setPrivateKey/connect 之后才真正握手使用），
// 故用静态缓冲存，不依赖发现时那次 JSON 文档的作用域。
static char      gAcCrt[2048] = "";
static char      gAcPk[2048]  = "";
static char      gAcUser[128] = "";
static char      gAcPass[128] = "";
static WiFiClientSecure gAcWcs;
static PubSubClient     gAcMqtt(gAcWcs);

static void acIngest(const char* topic, const char* payload) {
  // ★info/report 实测 ~1.5KB、几十个键 —— 池开销远大于字符数，1536 会 NoMemory 静默丢包
  static StaticJsonDocument<4096> j;
  if (deserializeJson(j, payload) != DeserializationError::Ok) { Serial.println("[LAN] AC msg json fail"); return; }
  const char* act = j["action"] | "";
  JsonObject  d = j["data"];
  PStat& p = pr[1];

  // ★"/info/report" 共 12 字符 —— 曾经写 -11 造成 off-by-one，温度分支永远不命中
  if (strstr(topic, "/info/report") != nullptr) {
    // 权威状态 + 温度（温度只有这条链上有）
    JsonObject temp = d["temp"];
    if (!temp.isNull()) {
      float h = temp["curr_nozzle_temp"] | -1.0f;
      float b = temp["curr_hotbed_temp"] | -1.0f;
      p.hot = (h < 0) ? -1 : h;
      p.bed = (b < 0) ? -1 : b;
    }
    const char* s = d["state"] | "";
    if (strcasecmp(s, "printing") == 0 || strcasecmp(s, "resuming") == 0 || strcasecmp(s, "pausing") == 0)
      p.state = 2;
    else if (strcasecmp(s, "free") == 0 || strcasecmp(s, "idle") == 0 || strcasecmp(s, "done") == 0 ||
             strcasecmp(s, "paused") == 0 || strcasecmp(s, "stopped") == 0 ||
             strcasecmp(s, "finished") == 0 || strcasecmp(s, "success") == 0 ||
             strcasecmp(s, "failed") == 0 || strcasecmp(s, "error") == 0)
      p.state = 1;                    // 已知空闲/完成词 → 显式置空闲（★此前逻辑写反，free 会落到不动作，state 停在 0=离线）
    p.have = true;
    return;
  }

  int setState = -1;
  if (!strcasecmp(act, "start") || !strcasecmp(act, "resume") || !strcasecmp(act, "report") ||
      !strcasecmp(act, "progress") || !strcasecmp(act, "printing") || !strcasecmp(act, "reprint"))
    setState = 2;
  else if (!strcasecmp(act, "stop") || !strcasecmp(act, "end") || !strcasecmp(act, "finish") ||
           !strcasecmp(act, "completed") || !strcasecmp(act, "complete") || !strcasecmp(act, "pause") ||
           !strcasecmp(act, "paused") || !strcasecmp(act, "error") || !strcasecmp(act, "abort") ||
           !strcasecmp(act, "cancel"))
    setState = 1;
  if (setState >= 0) p.state = setState;

  float prog = d["progress"] | -1.0f;
  if (prog >= 0) { p.prog = (int)(prog + 0.5f); if (p.prog < 0 || p.prog > 100) p.prog = -1; }
  const char* fn = d["filename"] | d["file_root_path"] | "";
  if (fn && fn[0]) { strncpy(p.file, fn, sizeof(p.file) - 1); p.file[sizeof(p.file) - 1] = 0; p.have = true; }
}

static void acCb(char* topic, uint8_t* payload, unsigned int len) {
  static char buf[4096];
  if (len >= sizeof(buf)) len = sizeof(buf) - 1;
  memcpy(buf, payload, len); buf[len] = 0;
  Serial.printf("[LAN] AC msg %s len=%u\n", topic, len);
  acIngest(topic, buf);
}

static void acDiscoverAndConnect() {
  // 1) GET /info → token + ctrlInfoUrl
  HTTPClient http;
  String infoUrl = String("http://") + gCfg[1].ip + ":18910/info";
  http.begin(infoUrl);
  http.setReuse(false);   // keep-alive 关闭：实测默认 reuse 时 end() 不真正关 socket，每请求漏 ~224B
  http.setTimeout(6000);
  int code = http.GET();
  if (code != HTTP_CODE_OK) { Serial.printf("[LAN] AC fail: GET /info code=%d\n", code); http.end(); gAcSt = AC_FAIL; return; }
  String info = http.getString();
  http.end();

  StaticJsonDocument<512> idoc;
  if (deserializeJson(idoc, info) != DeserializationError::Ok) { Serial.println("[LAN] AC fail: /info json"); gAcSt = AC_FAIL; return; }
  const char* token = idoc["token"] | "";
  const char* ctrlUrl = idoc["ctrlInfoUrl"] | "";
  if (!token[0] || !ctrlUrl[0]) { Serial.printf("[LAN] AC fail: /info missing token/ctrl (tok=%d url=%d)\n", (int)strlen(token), (int)strlen(ctrlUrl)); gAcSt = AC_FAIL; return; }

  // 2) POST ctrlInfoUrl?ts=&nonce=&sign=&did= → 密文凭据
  //    sign = MD5( MD5(token[:16]) + ts + nonce )  ← 与 pc/printers.py 实测可用版一致，
  //    内层 MD5 只取 token 前 16 字符（曾错用整串 token，/ctrl 会拒签）。
  char ts[24], nonce[8], inner[33], outer[33];
  char tok16[17];
  strlcpy(tok16, token, sizeof tok16);        // token[:16]
  md5hex(tok16, inner);
  const char* alpha = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
  for (int i = 0; i < 6; i++) nonce[i] = alpha[esp_random() % 62];
  nonce[6] = 0;
  uint64_t tsMs = epochMs();                  // 尽量用真实纪元毫秒（对时后）
  snprintf(ts, sizeof ts, "%llu", (unsigned long long)tsMs);
  String signSrc = String(inner) + String(ts) + String(nonce);
  md5hex(signSrc.c_str(), outer);

  String full = String(ctrlUrl);
  full += (strchr(ctrlUrl, '?') ? '&' : '?');
  full += "ts="; full += ts; full += "&nonce="; full += nonce;
  full += "&sign="; full += outer; full += "&did="; full += gAcDid;

  HTTPClient h2;
  h2.begin(full);
  h2.setReuse(false);
  h2.setTimeout(8000);
  h2.addHeader("Content-Type", "application/x-www-form-urlencoded");
  int c2 = h2.POST("");                         // 空 body，参数在 URL
  if (c2 != HTTP_CODE_OK) { Serial.printf("[LAN] AC fail: POST ctrl code=%d\n", c2); h2.end(); gAcSt = AC_FAIL; return; }
  String ctrl = h2.getString();
  h2.end();
  Serial.printf("[LAN] AC ctrl: hdrSize=%d bodyLen=%d\n", c2, (int)ctrl.length());

  // ★/ctrl 响应里 data.info 是 ~4032 字符的 b64 串 —— 池小了字符串会被静默截断，
  //  解出来就是「非 16 倍数的假密文」（实测踩坑：512 池 → clen=2655）。放 static 防爆栈。
  static StaticJsonDocument<8192> cdoc;
  if (deserializeJson(cdoc, ctrl) != DeserializationError::Ok) { Serial.println("[LAN] AC fail: ctrl json"); gAcSt = AC_FAIL; return; }
  if ((int)(cdoc["code"] | 0) != 200) { Serial.printf("[LAN] AC fail: ctrl code=%d %s\n", (int)(cdoc["code"] | 0), ctrl.c_str()); gAcSt = AC_FAIL; return; }
  const char* b64 = cdoc["data"]["info"] | "";
  const char* ivs = cdoc["data"]["token"] | "";
  Serial.printf("[LAN] AC b64len=%d ivlen=%d\n", (int)strlen(b64), (int)strlen(ivs));
  if (!b64[0] || !ivs[0] || strlen(ivs) != 16) { Serial.printf("[LAN] AC fail: ctrl fields b64=%d iv=%d\n", (int)strlen(b64), (int)strlen(ivs)); gAcSt = AC_FAIL; return; }

  // ★凭据密文实测 3024B（明文含 devicecrt+devicepk 两张 PEM，~3KB）。
  //  缓冲必须够大且放 static（栈只有 ~8KB，HTTP 调用链深，禁不起 3KB 局部数组）。
  static uint8_t cipher[3200];
  int clen = b64dec(b64, cipher, sizeof cipher);
  if (clen <= 0 || clen % 16) {
    int blen = (int)strlen(b64);
    char tail[41]; strncpy(tail, b64 + (blen > 40 ? blen - 40 : 0), 40); tail[40] = 0;
    Serial.printf("[LAN] AC fail: b64 clen=%d skips=%d at", clen, gB64Skips);
    for (int k = 0; k < gB64Skips && k < 5; k++) Serial.printf(" %d:%02X", gB64SkipAt[k], (unsigned)gB64SkipCh[k]);
    Serial.printf(" | tail=%s\n", tail);
    gAcSt = AC_FAIL; return;
  }
  static uint8_t plain[3200];
  uint8_t key[16], iv[16];
  memcpy(key, token + 16, 16);                 // key = token[16:32]
  memcpy(iv, ivs, 16);
  int plen = aesCbcDec(key, iv, cipher, clen, plain, sizeof plain);
  if (plen <= 0) { Serial.printf("[LAN] AC fail: aes plen=%d (clen=%d)\n", plen, clen); gAcSt = AC_FAIL; return; }

  // 凭据 JSON 解析池也要大（两张 PEM 字符串 ~3KB）；10KB 池放 static，避免栈爆
  static StaticJsonDocument<12288> cred;
  if (deserializeJson(cred, plain, plen) != DeserializationError::Ok) { Serial.println("[LAN] AC fail: cred json"); gAcSt = AC_FAIL; return; }
  const char* user  = cred["username"]  | "";
  const char* pass  = cred["password"]  | "";
  const char* crt   = cred["devicecrt"] | "";
  const char* pk    = cred["devicepk"]  | "";
  strncpy(gAcModel, cred["modelId"]  | "", sizeof gAcModel - 1);
  strncpy(gAcDev,   cred["deviceId"] | "", sizeof gAcDev - 1);
  strncpy(gAcUser,  user,  sizeof gAcUser  - 1);
  strncpy(gAcPass,  pass,  sizeof gAcPass  - 1);
  strncpy(gAcCrt,   crt,   sizeof gAcCrt   - 1);
  strncpy(gAcPk,    pk,    sizeof gAcPk    - 1);
  gAcUser[sizeof gAcUser - 1] = 0;
  gAcPass[sizeof gAcPass - 1] = 0;
  gAcCrt[sizeof gAcCrt - 1]   = 0;
  gAcPk[sizeof gAcPk - 1]     = 0;
  if (!gAcUser[0] || !gAcCrt[0] || !gAcPk[0] || !gAcModel[0] || !gAcDev[0]) {
    Serial.printf("[LAN] AC fail: cred fields user=%d crt=%d pk=%d model=%d dev=%d\n",
                  (int)strlen(gAcUser), (int)strlen(gAcCrt), (int)strlen(gAcPk),
                  (int)strlen(gAcModel), (int)strlen(gAcDev));
    gAcSt = AC_FAIL; return;
  }

  // 3) 连 MQTT-TLS（自签名客户端证书）
  gAcWcs.stop();
  gAcWcs.setInsecure();                        // 跳过 CA/主机名校验（打印机自签）
  gAcWcs.setCertificate(gAcCrt);
  gAcWcs.setPrivateKey(gAcPk);
  gAcWcs.setTimeout(8000);
  gAcMqtt.setServer(gCfg[1].ip, 9883);
  gAcMqtt.setBufferSize(4096);     // info/report ~1.5KB，留余量
  gAcMqtt.setKeepAlive(30);
  gAcMqtt.setCallback(acCb);
  gAcMqtt.setSocketTimeout(8);
  gAcSt = AC_CONNECT;
  gAcT0 = millis();
}

static void pollAnycubic(uint32_t now) {
  switch (gAcSt) {
    case AC_IDLE:
      if (now >= gAcNextTry) { gAcSt = AC_DISCOVER; }
      break;
    case AC_DISCOVER:
      acDiscoverAndConnect();                   // 内部失败会置 AC_FAIL
      if (gAcSt == AC_DISCOVER) gAcSt = AC_CONNECT;   // 发现成功 → 去连
      if (gAcSt == AC_CONNECT) gAcT0 = now;
      break;
    case AC_CONNECT:
      if (gAcMqtt.connect(("pc-monitor-" + String(gAcDid)).c_str(), gAcUser, gAcPass)) {
        bool subOk = gAcMqtt.subscribe("anycubic/#", 1);
        gAcSt = AC_RUN;
        gAcBackoff = 3;
        gAcQueryT = now;
        pr[1].have = false;                     // 等首个事件/查询回填
        Serial.printf("[LAN] Anycubic MQTT connected (sub=%d)\n", subOk);
      } else if (now - gAcT0 > 12000) {
        Serial.printf("[LAN] AC fail: mqtt connect rc=%d\n", gAcMqtt.state());
        gAcSt = AC_FAIL;
      }
      break;
    case AC_RUN:
      if (!gAcMqtt.connected()) { gAcSt = AC_FAIL; pr[1].state = 0; break; }
      gAcMqtt.loop();                          // 处理订阅推送
      if (now - gAcQueryT >= 30000) {           // 每 30s 主动查询（温度是这条链唯一来源）
        gAcQueryT = now;
        StaticJsonDocument<160> q;
        q["type"] = "info"; q["action"] = "query";
        q["msgid"] = String(gAcDid) + "-" + String((unsigned long)millis());
        q["timestamp"] = (long long)epochMs();   // 纪元毫秒（与 pc/printers.py 一致；曾误用 32 位截断值）
        String qt = "anycubic/anycubicCloud/v1/slicer/printer/";
        qt += gAcModel; qt += "/"; qt += gAcDev; qt += "/info";
        String payload; serializeJson(q, payload);
        bool pubOk = gAcMqtt.publish(qt.c_str(), payload.c_str(), false);
        Serial.printf("[LAN] AC pub=%d conn=%d rc=%d topic=%s\n",
                      pubOk, gAcMqtt.connected(), gAcMqtt.state(), qt.c_str());
      }
      // 名字：配置名优先，否则默认
      strncpy(pr[1].name, gCfg[1].name[0] ? gCfg[1].name : "KOBRA X", sizeof pr[1].name - 1);
      pr[1].name[sizeof pr[1].name - 1] = 0;
      break;
    case AC_FAIL:
      gAcWcs.stop();
      gAcMqtt.disconnect();
      pr[1].state = 0;
      gAcNextTry = now + (uint32_t)gAcBackoff * 1000;
      gAcBackoff = (gAcBackoff < 60) ? gAcBackoff * 2 : 60;
      gAcSt = AC_IDLE;
      break;
  }
}

// =====================================================================
// 对外接口
// =====================================================================
void plBegin() {
  loadCfg();
  // 客户端标识 did：md5("pc-monitor") 前 16 位（发现时用，打印机据此识别会话）
  md5hex("pc-monitor", gAcDid);
  gAcDid[16] = 0;
  Serial.printf("[LAN] begin cfg: e0=%d t0=%d ip0=%s | e1=%d t1=%d ip1=%s\n",
                 gCfg[0].enabled, gCfg[0].type, gCfg[0].ip,
                 gCfg[1].enabled, gCfg[1].type, gCfg[1].ip);
}

void plPoll(uint32_t now, bool online) {
  if (online) {
    // 在线：串口拥有打印机数据，本模块完全不动作；释放 LAN 的 WiFi hold 需求
    gSrc[0] = gSrc[1] = 0;
    netSetLanHold(false);
    return;
  }
  // 离线：只要任一 slot 启用，就要 WiFi 常开来轮询
  bool anyEnabled = gCfg[0].enabled || gCfg[1].enabled;
  netSetLanHold(anyEnabled);

  if (!anyEnabled) return;

  // 离线：启用的 slot 来源标记为局域网；未启用的清掉旧串口残留，避免显示过期数据
  for (int i = 0; i < 2; i++) {
    if (!gCfg[i].enabled) { pr[i].have = false; gSrc[i] = 0; }
    else                  { gSrc[i] = 1; }
  }

  // ★WiFi 就绪门控：全新开机时 netclock 可能还没把 lwIP 协议栈带起来，
  //  这时发起 HTTP/TCP 会踩 lwIP 断言 tcpip_send_msg_wait_sem (Invalid mbox)
  //  直接重启死循环（2026-09-30 真机实测）。WiFi 没连上就等下一轮。
  if (WiFi.status() != WL_CONNECTED) return;

  if (gCfg[0].enabled && gCfg[0].type == PL_TYPE_CREALITY && now - gCrT0 >= CR_PERIOD) {
    gCrT0 = now;
    pollCreality(0);
  }
  if (gCfg[1].enabled && gCfg[1].type == PL_TYPE_ANYCUBIC) {
    pollAnycubic(now);
  }
}

bool plCfgEnabled(int slot) {
  if (slot < 0 || slot > 1) return false;
  return gCfg[slot].enabled;
}

bool plSetPrinter(int slot, int type, const char* ip, const char* name) {
  if (slot < 0 || slot > 1) return false;
  if (type != PL_TYPE_CREALITY && type != PL_TYPE_ANYCUBIC) return false;
  if (!ipOk(ip)) return false;

  gPrefs.begin(PL_NS, false);
  char ke[8], kt[8], ki[8], kn[8];
  snprintf(ke, sizeof ke, "e%d", slot + 1);
  snprintf(kt, sizeof kt, "t%d", slot + 1);
  snprintf(ki, sizeof ki, "i%d", slot + 1);
  snprintf(kn, sizeof kn, "n%d", slot + 1);
  gPrefs.putInt(ke, 1);
  gPrefs.putInt(kt, type);
  gPrefs.putString(ki, ip);
  if (name && name[0]) gPrefs.putString(kn, name);
  gPrefs.end();

  // 即时生效（内存 + 重置对应轮询状态）
  gCfg[slot].enabled = true;
  gCfg[slot].type = type;
  strncpy(gCfg[slot].ip, ip, sizeof gCfg[slot].ip - 1); gCfg[slot].ip[sizeof gCfg[slot].ip - 1] = 0;
  if (name && name[0]) { strncpy(gCfg[slot].name, name, sizeof gCfg[slot].name - 1); gCfg[slot].name[sizeof gCfg[slot].name - 1] = 0; }
  if (slot == 1) { gAcSt = AC_IDLE; gAcNextTry = 0; gAcWcs.stop(); gAcMqtt.disconnect(); }
  if (slot == 0) gCrT0 = 0;
  Serial.printf("[LAN] set slot=%d type=%d ip=%s name=%s\n", slot, type, ip, gCfg[slot].name);
  return true;
}

void plClearConfig() {
  gPrefs.begin(PL_NS, false);
  gPrefs.clear();
  gPrefs.end();
  gCfg[0].enabled = gCfg[1].enabled = false;
  gCfg[0].ip[0] = gCfg[1].ip[0] = 0;
  gAcSt = AC_IDLE; gAcWcs.stop(); gAcMqtt.disconnect();
  Serial.println("[LAN] config cleared");
}

void plPrintStatus(Stream& out) {
  for (int i = 0; i < 2; i++) {
    const char* t = gCfg[i].type == PL_TYPE_ANYCUBIC ? "Anycubic" : "Creality";
    out.printf("[LAN] slot%d enabled=%d type=%s ip=%s\n", i + 1, gCfg[i].enabled, t, gCfg[i].ip);
  }
  const char* acs = "?";
  switch (gAcSt) { case AC_IDLE: acs = "IDLE"; break; case AC_DISCOVER: acs = "DISCOVER"; break;
                   case AC_CONNECT: acs = "CONNECT"; break; case AC_RUN: acs = "RUN"; break;
                   case AC_FAIL: acs = "FAIL"; break; }
  out.printf("[LAN] anycubic state=%s model=%s dev=%s\n", acs, gAcModel, gAcDev);
}

int plSrc(int slot) {
  if (slot < 0 || slot > 1) return 0;
  return gSrc[slot];
}
