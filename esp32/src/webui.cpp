#include "webui.h"
#include "netclock.h"

#include <WebServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <WiFi.h>

// ============================== 内部状态 ====================================
static WebServer   srv(80);
static WebStatusFn gStatusFn = nullptr;
static bool        gMdns     = false;     // mDNS 是否已注册
static bool        gStarted  = false;     // HTTP 监听是否已开（★必须等 WiFi 起来，见 webPoll）
static uint32_t    gLastChk  = 0;

static Preferences gPrefs;
static const char* WS_NS = "prtcfg";      // NVS 命名空间（与 netclock 的 netclk 分开）

void webSetStatusFn(WebStatusFn fn) { gStatusFn = fn; }

// ============================== 凭据存取 ====================================
// 登录码（token）只落 NVS，绝不进源码 —— 本工程要 export_opensource.py 开源导出，
// 硬编码凭据等于直接泄露。
static const char* tokKey(int w) { return (w == 0) ? "ac_tok" : "cr_tok"; }

String webToken(int which) {
  if (which < 0 || which > 1) return String();
  if (!gPrefs.begin(WS_NS, true)) return String();   // 命名空间不存在 → 空串
  String v = gPrefs.getString(tokKey(which), "");
  gPrefs.end();
  return v;
}

static void saveToken(int which, const String& v) {
  if (which < 0 || which > 1) return;
  if (!gPrefs.begin(WS_NS, false)) return;
  if (v.length() == 0) gPrefs.remove(tokKey(which));
  else                 gPrefs.putString(tokKey(which), v);
  gPrefs.end();
}

// ============================== 页面（PROGMEM）===============================
// 两个页面各自内联样式：省一次 FPSTR 拼接，也让每页体积独立可控。

// 状态页：纯前端渲染，每 2 秒向 /api/status 拉一次 JSON
static const char PAGE_STATUS[] PROGMEM =
  "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
  "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
  "<title>桌面监控</title>"
  "<style>"
  ":root{--bg:#0e0e13;--card:#16161e;--line:#2a2a34;--txt:#eeeef2;--dim:#737382;"
  "--acc:#4dd0c4;--warn:#ef9f27}"
  "*{box-sizing:border-box}"
  "body{margin:0;padding:16px;background:var(--bg);color:var(--txt);"
  "font:15px/1.55 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
  "-webkit-text-size-adjust:100%}"
  "h1{font-size:17px;font-weight:600;margin:0 0 14px;letter-spacing:.4px}"
  "a{color:var(--acc);text-decoration:none}"
  ".card{background:var(--card);border:1px solid var(--line);border-radius:12px;"
  "padding:14px;margin-bottom:12px}"
  ".nm{font-size:15px;font-weight:600;margin-bottom:2px}"
  ".st{font-size:12px;color:var(--dim)}"
  ".row{display:flex;gap:14px;margin-top:10px}"
  ".kv{flex:1;min-width:0}"
  ".kv .k{font-size:11px;color:var(--dim)}"
  ".kv .v{font-size:20px;font-weight:600;font-variant-numeric:tabular-nums}"
  ".bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:12px}"
  ".bar i{display:block;height:100%;background:var(--acc);border-radius:3px;transition:width .4s}"
  ".file{font-size:12px;color:var(--dim);margin-top:8px;word-break:break-all}"
  ".miss{color:var(--dim);font-size:13px}"
  ".ft{text-align:center;margin-top:18px;font-size:13px}"
  "</style></head><body>"
  "<h1>桌面监控</h1><div id='app'><div class='card miss'>读取中…</div></div>"
  "<div class='ft'><a href='/config'>设置</a></div>"
  "<script>"
  "function esc(s){return String(s==null?'':s).replace(/[<>&\"]/g,"
  "function(c){return{'<':'&lt;','>':'&gt;','&':'&amp;','\"':'&quot;'}[c]})}"
  "function card(d,i){"
  "if(!d||!d.have)return '<div class=\"card\"><div class=\"nm\">打印机 '+(i+1)"
  "+'</div><div class=\"miss\">未配置 / 无数据</div></div>';"
  "return '<div class=\"card\"><div class=\"nm\">'+esc(d.name)+'</div>"
  "<div class=\"st\">'+esc(d.state)+'</div>"
  "<div class=\"row\"><div class=\"kv\"><div class=\"k\">喷头</div><div class=\"v\">'"
  "+d.hot+'&deg;</div></div>"
  "<div class=\"kv\"><div class=\"k\">热床</div><div class=\"v\">'+d.bed+'&deg;</div></div>"
  "<div class=\"kv\"><div class=\"k\">进度</div><div class=\"v\">'+d.prog+'%</div></div></div>"
  "<div class=\"bar\"><i style=\"width:'+d.prog+'%\"></i></div>'"
  "+(d.file?'<div class=\"file\">'+esc(d.file)+'</div>':'')+'</div>';}"
  "function render(d){"
  "var h=card(d.p1,0)+card(d.p2,1);"
  "h+='<div class=\"card\"><div class=\"nm\">本机</div><div class=\"st\">'"
  "+esc(d.net)+' &middot; '+esc(d.ip)+'</div>"
  "<div class=\"row\"><div class=\"kv\"><div class=\"k\">CPU</div><div class=\"v\">'+d.cpu+'%</div></div>"
  "<div class=\"kv\"><div class=\"k\">内存</div><div class=\"v\">'+d.ram+'%</div></div>"
  "<div class=\"kv\"><div class=\"k\">显卡</div><div class=\"v\">'+d.gpu+'%</div></div></div></div>';"
  "document.getElementById('app').innerHTML=h;}"
  "async function tick(){try{var r=await fetch('/api/status',{cache:'no-store'});"
  "render(await r.json());}catch(e){"
  "document.getElementById('app').innerHTML='<div class=\"card miss\">连接失败，重试中…</div>';}}"
  "tick();setInterval(tick,2000);"
  "</script></body></html>";

// 配置页：WiFi + 两台打印机的登录码
static const char PAGE_CONFIG_HEAD[] PROGMEM =
  "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
  "<meta name='viewport' content='width=device-width,initial-scale=1,viewport-fit=cover'>"
  "<title>设置</title>";
static const char PAGE_CONFIG_CSS[] PROGMEM =
  "<style>"
  "body{margin:0;padding:16px;background:#0e0e13;color:#eeeef2;"
  "font:15px/1.55 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif;"
  "-webkit-text-size-adjust:100%}"
  "h1{font-size:17px;font-weight:600;margin:0 0 14px;letter-spacing:.4px}"
  "a{color:#4dd0c4;text-decoration:none}"
  ".card{background:#16161e;border:1px solid #2a2a34;border-radius:12px;padding:14px;margin-bottom:12px}"
  ".nm{font-size:15px;font-weight:600}"
  ".st{font-size:12px;color:#737382;margin-bottom:4px}"
  ".miss{color:#737382;font-size:13px}"
  "label{display:block;font-size:12px;color:#737382;margin:10px 0 4px}"
  "input,textarea,button{width:100%;font:inherit;color:#eeeef2;background:#0b0b10;"
  "border:1px solid #2a2a34;border-radius:8px;padding:9px 10px;outline:none}"
  "input:focus,textarea:focus{border-color:#4dd0c4}"
  "textarea{height:76px;resize:vertical;font-size:12px;font-family:ui-monospace,monospace}"
  "button{background:#4dd0c4;color:#04211f;border:0;font-weight:600;margin-top:16px;"
  "padding:12px;border-radius:10px}"
  ".ft{text-align:center;margin-top:18px;font-size:13px}"
  "</style></head><body>";

// ============================== 路由处理 ====================================
static void handleRoot() {
  srv.sendHeader("Cache-Control", "no-store");
  srv.send_P(200, "text/html; charset=utf-8", PAGE_STATUS);
}

static void handleConfig() {
  String h;
  h.reserve(1800);
  h += FPSTR(PAGE_CONFIG_HEAD);
  h += FPSTR(PAGE_CONFIG_CSS);
  h += "<h1>设置</h1><form method='post' action='/api/save'>";

  // WiFi：已存的 SSID 回填，密码留空（不回显）
  char ssid[33] = "", pass[65] = "";
  bool hasCred = netGetCred(0, ssid, sizeof(ssid), pass, sizeof(pass));
  h += "<div class='card'><div class='nm'>WiFi</div>";
  if (hasCred) h += "<div class='st'>当前已保存：" + String(ssid) + "</div>";
  else         h += "<div class='st'>尚未配置网络</div>";
  h += "<label>无线名称 (SSID)</label><input name='ssid' placeholder='例如 TP-LINK_5G'>";
  h += "<label>无线密码</label><input name='pass' type='password' placeholder='留空则不修改'>";
  h += "</div>";

  // 打印机登录码（不回显，只报是否已设置）
  h += "<div class='card'><div class='nm'>打印机账号</div>";
  h += "<div class='st'>登录码仅保存在设备本地，不会写入源码或上传</div>";
  h += "<label>Anycubic 登录码（Kobra X）</label>";
  h += String("<textarea name='ac' placeholder='") +
       (webToken(0).length() ? "已设置，粘贴新值可覆盖" : "粘贴登录码") + "'></textarea>";
  h += "<label>创想登录码</label>";
  h += String("<textarea name='cr' placeholder='") +
       (webToken(1).length() ? "已设置，粘贴新值可覆盖" : "粘贴登录码") + "'></textarea>";
  h += "</div>";

  h += "<button>保存</button></form>";
  h += "<div class='ft'><a href='/'>返回</a></div></body></html>";
  srv.send(200, "text/html; charset=utf-8", h);
}

static void handleApiStatus() {
  String j;
  j.reserve(420);
  if (gStatusFn) gStatusFn(j);
  else           j = "{}";
  srv.sendHeader("Cache-Control", "no-store");
  srv.send(200, "application/json; charset=utf-8", j);
}

static void handleSave() {
  String msg;
  bool wifiChanged = false;

  String ssid = srv.arg("ssid");
  ssid.trim();
  if (ssid.length()) {
    String pw = srv.arg("pass");
    if (netAddCredential(ssid.c_str(), pw.c_str())) {
      wifiChanged = true;
      msg += "WiFi 已更新<br>";
    } else {
      msg += "WiFi 保存失败（名称或密码超长）<br>";
    }
  }

  if (srv.hasArg("ac")) { saveToken(0, srv.arg("ac")); msg += "Anycubic 登录码已保存<br>"; }
  if (srv.hasArg("cr")) { saveToken(1, srv.arg("cr")); msg += "创想登录码已保存<br>"; }

  if (wifiChanged) msg += "网络变更将在设备重启后生效。";
  else             msg += "即刻生效。";

  String h = "<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>"
             "<meta name='viewport' content='width=device-width,initial-scale=1'>"
             "<title>已保存</title></head>"
             "<body style=\"margin:0;padding:32px;background:#0e0e13;color:#eeeef2;"
             "font:15px/1.6 -apple-system,'PingFang SC','Microsoft YaHei',sans-serif\">"
             "<h1 style='font-size:17px'>已保存</h1><p>" + msg + "</p>"
             "<p style='margin-top:22px'><a href='/' style='color:#4dd0c4'>返回状态页</a>"
             " &nbsp; <a href='/config' style='color:#4dd0c4'>继续设置</a></p>"
             "</body></html>";
  srv.send(200, "text/html; charset=utf-8", h);
}

// ============================== 启动与轮询 ==================================
void webBegin() {
  netSetWifiHold(true);   // ★让 netclock 保持 WiFi 常开（浏览器要能随时打开本页）

  srv.on("/",           HTTP_GET,  handleRoot);
  srv.on("/config",     HTTP_GET,  handleConfig);
  srv.on("/api/status", HTTP_GET,  handleApiStatus);
  srv.on("/api/save",   HTTP_POST, handleSave);
  srv.onNotFound([]() {
    srv.sendHeader("Location", "/", true);
    srv.send(302, "text/plain", "");
  });
  // ★ 这里**绝不能**调 srv.begin()：setup 阶段 WiFi 还没初始化（本固件的 WiFi 由
  //   netclock 在 loop 里懒加载），LwIP 的 TCP 邮箱尚不存在，begin() 会当场
  //   assert failed: tcpip_send_msg_wait_sem (Invalid mbox) 并**无限重启**。
  //   监听推迟到 webPoll() 里「WiFi 已连上」之后 —— 那时协议栈才真正就绪。
  Serial.println("[WEB] routes ready, waiting for wifi");
}

void webPoll(uint32_t now) {
  // ① 等 WiFi 真正连上（TCP/IP 栈就绪）才开监听端口。
  //    提前开一次就是 tcpip_send_msg_wait_sem assert → 设备无限重启，顺序不能动。
  if (!gStarted) {
    if (!netWifiUp()) return;
    srv.begin();
    gStarted = true;
    Serial.printf("[WEB] http server on :80  ip=%s  heap=%u\n",
                  netIpText().c_str(), (unsigned)ESP.getFreeHeap());
  }

  srv.handleClient();          // 非阻塞式：处理完一个请求即返回

  // ② mDNS 也要等 WiFi 起来；失败每 10 秒重试一次。
  if (!gMdns && (gLastChk == 0 || now - gLastChk >= 10000)) {
    gLastChk = now;
    if (MDNS.begin("pcscreen")) {
      MDNS.addService("http", "tcp", 80);
      gMdns = true;
      Serial.println("[WEB] mdns ready -> http://pcscreen.local/");
    } else {
      Serial.println("[WEB] mdns begin failed, retry in 10s");
    }
  }
}

bool webReady() { return gMdns; }
