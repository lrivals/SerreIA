#include "serre_node.h"

#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <esp_task_wdt.h>
#include <time.h>

#include "node_config.h"
#include "ranges.h"
#include "secrets.h"

namespace serre {

namespace {

// Filtre MQTT : '+' = un niveau, '#' = la fin.
bool topicMatches(const String& pattern, const char* topic) {
  const char* p = pattern.c_str();
  const char* t = topic;
  while (*p && *t) {
    if (*p == '#') return true;
    if (*p == '+') {
      while (*t && *t != '/') ++t;
      ++p;
      continue;
    }
    if (*p != *t) return false;
    ++p;
    ++t;
  }
  return (*p == 0 && *t == 0) || (p[0] == '/' && p[1] == '#');
}

void setupWatchdog() {
  esp_task_wdt_config_t cfg = {};
  cfg.timeout_ms = WATCHDOG_TIMEOUT_MS;
  cfg.idle_core_mask = 0;
  cfg.trigger_panic = true;  // reboot
  if (esp_task_wdt_reconfigure(&cfg) != ESP_OK) esp_task_wdt_init(&cfg);
  esp_task_wdt_add(nullptr);  // tâche loop()
}

void selectAntenna() {
  // XIAO ESP32-C6 : GPIO3 à LOW active le commutateur RF, GPIO14 choisit l'antenne.
  pinMode(3, OUTPUT);
  digitalWrite(3, LOW);
  delay(100);
  pinMode(14, OUTPUT);
  digitalWrite(14, EXTERNAL_ANTENNA ? HIGH : LOW);
}

}  // namespace

void Node::begin() {
  Serial.begin(115200);
  selectAntenna();
  setupWatchdog();
  WiFi.mode(WIFI_STA);
  WiFi.setHostname(id_);
  connectWifi();
  configTzTime(TZ_POSIX, NTP_SERVER);
  mqtt_.setServer(MQTT_HOST, MQTT_PORT);
  mqtt_.setBufferSize(MQTT_MAX_PACKET_SIZE);
  mqtt_.setKeepAlive(30);
  mqtt_.setCallback([this](char* t, uint8_t* p, unsigned int n) { onMessage(t, p, n); });
  ArduinoOTA.setHostname(id_);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() { esp_task_wdt_reset(); });
  ArduinoOTA.onProgress([](unsigned int, unsigned int) { esp_task_wdt_reset(); });
  ArduinoOTA.begin();
  lastConnectedMs_ = millis();
  Serial.printf("[%s] démarrage, zone %s\n", id_, zone_);
}

void Node::connectWifi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 15000) {
    esp_task_wdt_reset();
    delay(250);
  }
}

bool Node::connectMqtt() {
  char willTopic[64];
  snprintf(willTopic, sizeof willTopic, "serre/%s/status", id_);
  const char* user = strlen(MQTT_USER) ? MQTT_USER : nullptr;
  const char* pass = strlen(MQTT_PASSWORD) ? MQTT_PASSWORD : nullptr;
  if (!mqtt_.connect(id_, user, pass, willTopic, 1, true, "offline")) return false;
  mqtt_.publish(willTopic, "online", true);
  for (int i = 0; i < nSubs_; ++i) mqtt_.subscribe(patterns_[i].c_str(), 1);
  everConnected_ = true;
  Serial.printf("[%s] MQTT connecté\n", id_);
  return true;
}

void Node::loop() {
  esp_task_wdt_reset();
  ArduinoOTA.handle();
  if (WiFi.status() != WL_CONNECTED && millis() - lastAttemptMs_ > 10000) {
    lastAttemptMs_ = millis();
    WiFi.reconnect();
  }
  if (WiFi.status() == WL_CONNECTED && !mqtt_.connected() && millis() - lastAttemptMs_ > 5000) {
    lastAttemptMs_ = millis();
    connectMqtt();
  }
  if (mqtt_.connected()) {
    mqtt_.loop();
    lastConnectedMs_ = millis();
  }
}

uint32_t Node::msSinceMqtt() const {
  return millis() - lastConnectedMs_;
}

bool Node::timeValid() const {
  return time(nullptr) > 1700000000;  // après novembre 2023 : NTP synchronisé
}

String Node::isoNow() const {
  time_t now = time(nullptr);
  struct tm utc;
  gmtime_r(&now, &utc);
  char buf[24];
  strftime(buf, sizeof buf, "%Y-%m-%dT%H:%M:%SZ", &utc);
  return String(buf);
}

bool Node::publishReading(const char* type, float value, const char* emplacement, int decimals) {
  const SensorRange* range = findRange(type);
  if (range == nullptr || isnan(value) || !timeValid() || !mqtt_.connected()) return false;
  JsonDocument doc;
  doc["ts"] = isoNow();
  doc["noeud"] = id_;
  const float scale = powf(10.0f, decimals);
  doc["valeur"] = roundf(value * scale) / scale;
  doc["unite"] = range->unite;
  doc["qualite"] = quality(type, value);
  if (emplacement != nullptr) doc["emplacement"] = emplacement;
  char payload[256];
  const size_t n = serializeJson(doc, payload, sizeof payload);
  char topic[64];
  snprintf(topic, sizeof topic, "serre/%s/capteur/%s", zone_, type);
  return mqtt_.publish(topic, reinterpret_cast<const uint8_t*>(payload), n, false);
}

bool Node::publish(const char* topic, const char* payload, bool retain) {
  return mqtt_.connected() && mqtt_.publish(topic, payload, retain);
}

void Node::subscribe(const char* pattern, MessageHandler handler) {
  if (nSubs_ >= kMaxSubs) return;
  patterns_[nSubs_] = pattern;
  handlers_[nSubs_] = handler;
  ++nSubs_;
  if (mqtt_.connected()) mqtt_.subscribe(pattern, 1);
}

void Node::onMessage(char* topic, uint8_t* payload, unsigned int len) {
  for (int i = 0; i < nSubs_; ++i) {
    if (topicMatches(patterns_[i], topic)) handlers_[i](topic, payload, len);
  }
}

}  // namespace serre
