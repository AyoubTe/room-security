/*
  ESP32 Smoke Detector - AI-Thinker ESP32-CAM firmware
  ------------------------------------------------------
  What this does:
    - Reads an MQ-2 smoke/gas sensor's DIGITAL output (DO) on GPIO13
      (the onboard comparator + potentiometer on the MQ-2 module itself
      decides the trip threshold in hardware - there's no analog ppm
      value to read without an external ADC, which this build doesn't use)
    - Serves a fresh snapshot at /capture, polled by the app every few
      seconds instead of a persistent video stream (see note below)
    - Serves the photo taken at the moment of the last alarm at /alert.jpg
    - Saves every alert photo to the microSD card under /alerts, and
      serves the list at GET /alerts and each photo at GET /alerts/<file>
    - Serves a JSON status blob at /status
    - Accepts your app's Expo push token via POST /register, stores it in flash
    - Sends a push notification through Expo's push API when smoke is detected

  WHY NO LIVE MJPEG STREAM ANYMORE:
    esp_http_server runs each server on a single worker task. A streaming
    handler never returns while a client is connected, so it permanently
    occupies that worker - and a few failed/retried connections (a phone's
    WebView, a browser tab) exhaust the ESP32's small shared socket pool,
    which also broke /status polling on the *other* port. A short request
    that always completes and releases its connection avoids this
    failure mode entirely, at the cost of true live video.

  SD CARD WIRING:
    Uses the onboard microSD slot in 1-bit mode, which only drives
    GPIO2/14/15 - it never touches GPIO12/13, so the MQ-2 on GPIO13 (see
    below) is unaffected whether or not a card is inserted. If no card is
    present, the firmware still runs fine - alert history is just skipped
    (logged once at boot) and /alert.jpg (the single most-recent photo,
    kept in RAM) keeps working as before.

  ------------------------------------------------------
  WIRING (AI-Thinker ESP32-CAM):
    MQ-2  VCC -> 5V
    MQ-2  GND -> GND
    MQ-2  DO  -> GPIO13   (free pin - not used by camera, SD, or boot straps)
    MQ-2  AO  -> not connected (no external ADC in this build)

  ------------------------------------------------------
  TUNING SENSITIVITY:
    Unlike the analog version, sensitivity is set by the small blue
    potentiometer on the MQ-2 module itself, not in this code. Turn it
    while watching the onboard comparator LED: clockwise generally makes
    it MORE sensitive (trips at lower smoke levels), counter-clockwise
    LESS sensitive. Adjust in clean air until it reads "clear", then test
    with a blown-out match or lighter held a short distance away.

  ------------------------------------------------------
  VERIFY THE TRIGGER DIRECTION BEFORE RELYING ON THIS:
    Most LM393-based MQ-2 modules pull DO LOW when gas is above the
    potentiometer's threshold (MQ2_ACTIVE_LOW = true below), but some
    clones wire the comparator the other way. Open the Serial Monitor
    after upload: it prints the raw pin state once a second. Confirm it
    reads "clear" in normal air and flips to "TRIGGERED" when you test
    with smoke/gas. If it's backwards, flip MQ2_ACTIVE_LOW to false.

  ------------------------------------------------------
  ARDUINO IDE SETUP:
    1. File > Preferences > Additional Board URLs, add:
       https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
    2. Tools > Board > install "esp32" by Espressif, then select
       "ESP32 Wrover Module" (newer core versions dropped the dedicated
       "AI Thinker ESP32-CAM" entry - Wrover Module is the closest match)
    3. Tools > Partition Scheme > "Huge APP (3MB No OTA/1MB SPIFFS)"
    4. Fill in WIFI_SSID / WIFI_PASSWORD below, then upload with the
       GPIO0-to-GND jumper in place
*/

#include "esp_camera.h"
#include "esp_http_server.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Preferences.h>
#include "FS.h"
#include "SD_MMC.h"
#include <time.h>

// ---------------- USER CONFIG ----------------
const char* WIFI_SSID     = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* DEVICE_NAME   = "MyRoom";      // shown in push notification text
const char* FW_VERSION    = "0.2.1";

// Used only to name/label saved alert photos with a real date instead of
// "seconds since boot". France standard time is UTC+1; it does NOT
// auto-adjust for summer DST (UTC+2) - if that matters to you, change
// this to 7200 from late March to late October.
#define NTP_SERVER      "pool.ntp.org"
#define GMT_OFFSET_SEC  3600

#define MQ2_PIN            13
#define MQ2_ACTIVE_LOW     true   // see "VERIFY THE TRIGGER DIRECTION" above
#define DEBOUNCE_SAMPLES   5      // consecutive agreeing reads required before trusting a trigger
#define DEBOUNCE_DELAY_MS  50
#define ALARM_COOLDOWN_MS  60000  // don't re-alert more than once a minute
#define WARMUP_MS          60000  // MQ-2 heater warm-up period at boot - ignore triggers until this elapses
// ------------------------------------------------

// AI-Thinker ESP32-CAM pin map
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

Preferences prefs;
httpd_handle_t apiServer = NULL;

String expoPushToken = "";
uint32_t bootMillis = 0;
bool warmedUp = false;
bool alarmActive = false;
unsigned long lastAlarmSentAt = 0;
int lastMq2Reading = 0; // 0 = clear, 1 = triggered

uint8_t* alertJpgBuf = nullptr;
size_t alertJpgLen = 0;

#define SD_ALERTS_DIR "/alerts"
bool sdReady = false;
int alertSeq = 0; // persisted in flash so filenames stay unique across reboots

// ---------------- Camera ----------------
// Image-quality tuning for the OV2640. Its tiny sensor is weak in dim light,
// so these push auto-exposure/gain harder. The trade-off is more grain in the
// dark; adjust ae_level / brightness / gainceiling to taste.
void tuneSensor() {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return;
  s->set_exposure_ctrl(s, 1);               // auto exposure on
  s->set_aec2(s, 1);                        // extra auto-exposure mode (reported to help in low light)
  s->set_ae_level(s, 1);                    // -2..2, bias auto-exposure brighter
  s->set_gain_ctrl(s, 1);                   // auto gain on
  s->set_gainceiling(s, (gainceiling_t)6);  // 0..6 = 2X..128X max amplification in the dark
  s->set_brightness(s, 1);                  // -2..2
  s->set_whitebal(s, 1);                    // auto white balance
  s->set_awb_gain(s, 1);
  s->set_lenc(s, 1);                        // lens correction (darker corners)
  s->set_bpc(s, 1);                         // black pixel correction
  s->set_wpc(s, 1);                         // white pixel correction
  s->set_raw_gma(s, 1);                     // gamma correction
}

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size   = FRAMESIZE_SVGA; // 800x600 - matches the app's 800x600 label
    config.jpeg_quality = 10;             // lower = better quality (0-63); was 12
    config.fb_count     = 2;
    config.fb_location  = CAMERA_FB_IN_PSRAM;
    config.grab_mode    = CAMERA_GRAB_LATEST; // always hand back the newest frame, not an older queued one
  } else {
    config.frame_size   = FRAMESIZE_VGA;  // fallback if no PSRAM detected
    config.jpeg_quality = 12;
    config.fb_count     = 1;
    config.fb_location  = CAMERA_FB_IN_DRAM;
    config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed: 0x%x\n", err);
    return false;
  }
  tuneSensor();
  return true;
}

// ---------------- SD card (alert history) ----------------
bool initSdCard() {
  if (!SD_MMC.begin("/sdcard", true)) { // true = 1-bit mode, keeps GPIO12/13 free for the MQ-2
    Serial.println("SD card mount failed - alert history will not be saved (this is not fatal)");
    return false;
  }
  if (SD_MMC.cardType() == CARD_NONE) {
    Serial.println("No SD card detected - alert history will not be saved (this is not fatal)");
    return false;
  }
  if (!SD_MMC.exists(SD_ALERTS_DIR)) {
    SD_MMC.mkdir(SD_ALERTS_DIR);
  }
  Serial.printf("SD card ready - %lluMB used of %lluMB\n",
    SD_MMC.usedBytes() / (1024ULL * 1024ULL), SD_MMC.cardSize() / (1024ULL * 1024ULL));
  return true;
}

// Real date/time once NTP has synced after boot; otherwise an honest
// fallback based on uptime instead of a fabricated date.
bool timeIsSynced() {
  time_t now;
  time(&now);
  return now > 1700000000; // past ~Nov 2023 means NTP has actually set the clock
}

String timestampForFilename() {
  if (!timeIsSynced()) {
    return "boot" + String((unsigned long)(millis() / 1000));
  }
  time_t now;
  time(&now);
  struct tm timeinfo;
  localtime_r(&now, &timeinfo);
  char buf[20];
  strftime(buf, sizeof(buf), "%Y%m%d_%H%M%S", &timeinfo);
  return String(buf);
}

void captureAlertPhoto() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Alert photo capture failed");
    return;
  }

  if (alertJpgBuf) {
    free(alertJpgBuf);
    alertJpgBuf = nullptr;
  }
  alertJpgBuf = (uint8_t*) malloc(fb->len);
  if (alertJpgBuf) {
    memcpy(alertJpgBuf, fb->buf, fb->len);
    alertJpgLen = fb->len;
  }

  if (sdReady) {
    alertSeq++;
    prefs.putInt("alertSeq", alertSeq);
    String filename = String(SD_ALERTS_DIR) + "/alert_" + String(alertSeq) + "_" + timestampForFilename() + ".jpg";
    File f = SD_MMC.open(filename, FILE_WRITE);
    if (f) {
      f.write(fb->buf, fb->len);
      f.close();
      Serial.println("Saved alert photo to SD: " + filename);
    } else {
      Serial.println("Failed to open file on SD for writing: " + filename);
    }
  }

  esp_camera_fb_return(fb);
}

// ---------------- Expo push notification ----------------
void sendPushNotification(const String& title, const String& body) {
  if (expoPushToken.length() == 0) {
    Serial.println("No Expo push token registered yet - skipping push");
    return;
  }

  WiFiClientSecure client;
  client.setInsecure(); // skip TLS cert validation - fine for a prototype

  if (!client.connect("exp.host", 443)) {
    Serial.println("Failed to connect to exp.host");
    return;
  }

  String payload = "{\"to\":\"" + expoPushToken + "\",";
  payload += "\"title\":\"" + title + "\",";
  payload += "\"body\":\"" + body + "\",";
  payload += "\"sound\":\"default\",";
  payload += "\"priority\":\"high\",";
  payload += "\"data\":{\"type\":\"smoke_alert\",\"device\":\"" + String(DEVICE_NAME) + "\"}}";

  String request = "POST /--/api/v2/push/send HTTP/1.1\r\n";
  request += "Host: exp.host\r\n";
  request += "Accept: application/json\r\n";
  request += "Content-Type: application/json\r\n";
  request += "Content-Length: " + String(payload.length()) + "\r\n";
  request += "Connection: close\r\n\r\n";
  request += payload;

  client.print(request);

  unsigned long start = millis();
  while (client.connected() && millis() - start < 5000) {
    while (client.available()) {
      client.read();
    }
  }
  client.stop();
  Serial.println("Push notification sent");
}

// ---------------- HTTP handlers ----------------
// CORS: the app's web/browser target runs on a different origin
// (localhost:8081) than the ESP32, so the browser requires this header
// on every response or it rejects the fetch - Expo Go on a phone ignores
// this entirely, it's only needed for the web preview.
static void addCors(httpd_req_t* req) {
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");
}

static esp_err_t capture_handler(httpd_req_t* req) {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=capture.jpg");
  addCors(req);
  esp_err_t res = httpd_resp_send(req, (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return res;
}

static esp_err_t alert_handler(httpd_req_t* req) {
  if (!alertJpgBuf || alertJpgLen == 0) {
    httpd_resp_send_404(req);
    return ESP_FAIL;
  }
  httpd_resp_set_type(req, "image/jpeg");
  addCors(req);
  return httpd_resp_send(req, (const char*)alertJpgBuf, alertJpgLen);
}

// ---------------- Alert history (SD card) ----------------
static esp_err_t alerts_list_handler(httpd_req_t* req) {
  addCors(req);
  httpd_resp_set_type(req, "application/json");

  if (!sdReady) {
    const char* body = "{\"sdReady\":false,\"alerts\":[]}";
    httpd_resp_send(req, body, strlen(body));
    return ESP_OK;
  }

  String json = "{\"sdReady\":true,\"alerts\":[";
  File root = SD_MMC.open(SD_ALERTS_DIR);
  bool first = true;
  if (root && root.isDirectory()) {
    File f = root.openNextFile();
    while (f) {
      if (!f.isDirectory()) {
        String name = String(f.name());
        int slash = name.lastIndexOf('/');
        if (slash != -1) name = name.substring(slash + 1); // some cores return the full path
        if (!first) json += ",";
        first = false;
        json += "{\"file\":\"" + name + "\",\"size\":" + String(f.size()) + "}";
      }
      f = root.openNextFile();
    }
  }
  json += "]}";

  httpd_resp_send(req, json.c_str(), json.length());
  return ESP_OK;
}

static esp_err_t alerts_file_handler(httpd_req_t* req) {
  addCors(req);

  // Strip the "/alerts" prefix from the request URI, leaving "/<file>.jpg".
  const char* suffix = req->uri + (sizeof("/alerts") - 1);
  if (suffix[0] != '/' || strstr(suffix, "..") != NULL) {
    httpd_resp_send_404(req);
    return ESP_FAIL;
  }
  String path = String(SD_ALERTS_DIR) + suffix;

  if (!sdReady || !SD_MMC.exists(path)) {
    httpd_resp_send_404(req);
    return ESP_FAIL;
  }

  File f = SD_MMC.open(path, FILE_READ);
  if (!f) {
    httpd_resp_send_404(req);
    return ESP_FAIL;
  }

  httpd_resp_set_type(req, "image/jpeg");
  uint8_t buf[1024];
  size_t n;
  esp_err_t res = ESP_OK;
  while ((n = f.read(buf, sizeof(buf))) > 0) {
    res = httpd_resp_send_chunk(req, (const char*)buf, n);
    if (res != ESP_OK) break;
  }
  if (res == ESP_OK) httpd_resp_send_chunk(req, NULL, 0); // end the chunked response
  f.close();
  return res;
}

static esp_err_t status_handler(httpd_req_t* req) {
  char buf[400];
  unsigned long uptimeSec = (millis() - bootMillis) / 1000;
  const char* sensorState = warmedUp ? "ready" : "warm";
  const char* alarmState  = alarmActive ? "trip" : "nominal";

  // mq2 is now 0 (clear) or 1 (triggered) - there's no continuous ppm
  // value without an external ADC. "trip" is kept at 1 for compatibility
  // with anything that divides by it, but the real threshold now lives
  // in the MQ-2 module's own onboard potentiometer, not in software.
  snprintf(buf, sizeof(buf),
    "{\"device\":\"esp32-cam\",\"location\":\"%s\",\"mq2\":%d,\"trip\":1,"
    "\"alarm\":\"%s\",\"sensor\":\"%s\",\"rssi\":%d,\"uptime\":%lu,"
    "\"heap\":%lu,\"fw\":\"%s\"}",
    DEVICE_NAME, lastMq2Reading,
    alarmState, sensorState, WiFi.RSSI(), uptimeSec,
    (unsigned long) ESP.getFreeHeap(), FW_VERSION);

  httpd_resp_set_type(req, "application/json");
  addCors(req);
  return httpd_resp_send(req, buf, strlen(buf));
}

String extractJsonString(const String& body, const String& key) {
  String needle = "\"" + key + "\"";
  int keyPos = body.indexOf(needle);
  if (keyPos == -1) return "";
  int colonPos = body.indexOf(':', keyPos);
  int firstQuote = body.indexOf('"', colonPos + 1);
  int secondQuote = body.indexOf('"', firstQuote + 1);
  if (firstQuote == -1 || secondQuote == -1) return "";
  return body.substring(firstQuote + 1, secondQuote);
}

static esp_err_t register_handler(httpd_req_t* req) {
  char buf[300];
  int received = httpd_req_recv(req, buf, sizeof(buf) - 1);
  if (received <= 0) {
    httpd_resp_send_500(req);
    return ESP_FAIL;
  }
  buf[received] = '\0';

  String token = extractJsonString(String(buf), "token");
  addCors(req);
  if (token.length() > 0) {
    expoPushToken = token;
    prefs.putString("expotoken", expoPushToken);
    Serial.println("Registered new Expo push token");
    httpd_resp_send(req, "{\"ok\":true}", HTTPD_RESP_USE_STRLEN);
  } else {
    httpd_resp_send_500(req);
  }
  return ESP_OK;
}

// Browsers send an OPTIONS "preflight" request before a POST with a JSON
// body to ask permission first. Expo Go on a phone skips this entirely -
// it only happens when testing in a browser (web target).
static esp_err_t register_options_handler(httpd_req_t* req) {
  addCors(req);
  httpd_resp_set_hdr(req, "Access-Control-Allow-Methods", "POST, OPTIONS");
  httpd_resp_set_hdr(req, "Access-Control-Allow-Headers", "Content-Type");
  httpd_resp_send(req, NULL, 0);
  return ESP_OK;
}

void startServers() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.server_port = 80;
  config.ctrl_port = 32768;
  config.uri_match_fn = httpd_uri_match_wildcard; // needed for the /alerts/* wildcard route below

  httpd_uri_t status_uri       = { "/status",    HTTP_GET,     status_handler,       NULL };
  httpd_uri_t capture_uri      = { "/capture",   HTTP_GET,     capture_handler,      NULL };
  httpd_uri_t alert_uri        = { "/alert.jpg", HTTP_GET,     alert_handler,        NULL };
  httpd_uri_t register_uri     = { "/register",  HTTP_POST,    register_handler,     NULL };
  httpd_uri_t register_opt_uri = { "/register",  HTTP_OPTIONS, register_options_handler, NULL };
  httpd_uri_t alerts_list_uri  = { "/alerts",    HTTP_GET,     alerts_list_handler,  NULL };
  httpd_uri_t alerts_file_uri  = { "/alerts/*",  HTTP_GET,     alerts_file_handler,  NULL };

  if (httpd_start(&apiServer, &config) == ESP_OK) {
    httpd_register_uri_handler(apiServer, &status_uri);
    httpd_register_uri_handler(apiServer, &capture_uri);
    httpd_register_uri_handler(apiServer, &alert_uri);
    httpd_register_uri_handler(apiServer, &register_uri);
    httpd_register_uri_handler(apiServer, &register_opt_uri);
    httpd_register_uri_handler(apiServer, &alerts_list_uri);
    httpd_register_uri_handler(apiServer, &alerts_file_uri);
  }
}

// Reads the DO pin DEBOUNCE_SAMPLES times and only reports a trigger if
// every sample agrees - a single noisy read won't cause a false alarm.
bool readMq2Triggered() {
  int activeLevel = MQ2_ACTIVE_LOW ? LOW : HIGH;
  int agreeing = 0;
  for (int i = 0; i < DEBOUNCE_SAMPLES; i++) {
    if (digitalRead(MQ2_PIN) == activeLevel) agreeing++;
    delay(DEBOUNCE_DELAY_MS);
  }
  return agreeing == DEBOUNCE_SAMPLES;
}

// ---------------- Main ----------------
void setup() {
  Serial.begin(115200);
  pinMode(MQ2_PIN, INPUT);
  bootMillis = millis();

  prefs.begin("smoke", false);
  expoPushToken = prefs.getString("expotoken", "");
  alertSeq = prefs.getInt("alertSeq", 0);

  if (!initCamera()) {
    Serial.println("Camera init failed - halting");
    return;
  }

  sdReady = initSdCard();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected. IP address: ");
  Serial.println(WiFi.localIP());
  Serial.println("(the app talks to this IP for /status, /capture, /alerts, /register)");
  Serial.println("MQ-2 is on GPIO13 (digital). Watch the next lines to confirm trigger direction.");

  configTime(GMT_OFFSET_SEC, 0, NTP_SERVER); // best-effort; alert filenames fall back to uptime if this never syncs

  startServers();
}

void loop() {
  bool triggeredNow = readMq2Triggered();
  lastMq2Reading = triggeredNow ? 1 : 0;

  warmedUp = (millis() - bootMillis) > WARMUP_MS;

  static unsigned long lastPrint = 0;
  if (millis() - lastPrint > 1000) {
    Serial.println(triggeredNow ? "MQ-2: TRIGGERED" : "MQ-2: clear");
    lastPrint = millis();
  }

  bool overThreshold = warmedUp && triggeredNow;

  if (overThreshold && !alarmActive) {
    alarmActive = true;
  } else if (!overThreshold && alarmActive) {
    alarmActive = false;
  }

  if (alarmActive && (millis() - lastAlarmSentAt > ALARM_COOLDOWN_MS)) {
    Serial.println("SMOKE DETECTED - capturing photo and sending alert");
    captureAlertPhoto();
    sendPushNotification(
      String(DEVICE_NAME) + ": smoke detected",
      "MQ-2 digital trigger active"
    );
    lastAlarmSentAt = millis();
  }
}
