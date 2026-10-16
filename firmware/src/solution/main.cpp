// Nœud solution nutritive (esp32-03, zone hydro, docs/06 §1.3) : Atlas Scientific EZO-pH et
// EZO-EC en I²C, DS18B20 étanche (1-Wire) pour la compensation de température, niveau de
// cuve par flotteur (0 / 100 %) ou ultrason JSN-SR04T (%).
//
// ⚠️ Isolation galvanique obligatoire entre les sondes pH et EC plongées dans la même cuve
// (cartes d'isolation Atlas) : sans elle, les mesures se perturbent.
// Étalonnage pH 3 points mensuel : commandes EZO "Cal,mid,7.00", "Cal,low,4.00",
// "Cal,high,10.00" envoyées par le port série (`ezo ph <commande>`, `ezo ec <commande>`).

#include <Arduino.h>
#include <DallasTemperature.h>
#include <OneWire.h>
#include <Wire.h>

#include "node_config.h"
#include "serre_node.h"

namespace {

serre::Node node(NODE_ID, NODE_ZONE);
OneWire oneWire(ONEWIRE_PIN);
DallasTemperature ds18b20(&oneWire);
uint32_t lastRead = 0;

// Commande EZO en I²C ; réponse ASCII dans `out`. false si erreur ou pas de réponse.
bool ezo(uint8_t addr, const char* cmd, uint16_t waitMs, char* out, size_t outLen) {
  Wire.beginTransmission(addr);
  Wire.write(reinterpret_cast<const uint8_t*>(cmd), strlen(cmd));
  if (Wire.endTransmission() != 0) return false;
  delay(waitMs);
  if (Wire.requestFrom(addr, static_cast<uint8_t>(32)) == 0) return false;
  const int code = Wire.read();  // 1 : succès, 2 : erreur, 254 : en cours, 255 : sans données
  size_t n = 0;
  while (Wire.available() && n + 1 < outLen) {
    const char c = static_cast<char>(Wire.read());
    if (c == 0) break;
    out[n++] = c;
  }
  out[n] = 0;
  return code == 1;
}

float readEzo(uint8_t addr, float tempC) {
  char buf[40];
  if (!isnan(tempC)) {
    char cmd[16];
    snprintf(cmd, sizeof cmd, "T,%.1f", tempC);  // compensation de température
    ezo(addr, cmd, 300, buf, sizeof buf);
  }
  if (!ezo(addr, "R", 900, buf, sizeof buf)) return NAN;
  return atof(buf);  // EC : premier champ (µS/cm) si plusieurs sorties sont actives
}

float tankLevel() {
#ifdef TANK_TRIG_PIN
  digitalWrite(TANK_TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TANK_TRIG_PIN, HIGH);
  delayMicroseconds(20);
  digitalWrite(TANK_TRIG_PIN, LOW);
  const unsigned long us = pulseIn(TANK_ECHO_PIN, HIGH, 30000);
  if (us == 0) return NAN;
  const float cm = us / 58.0f;
  const float pct = (TANK_EMPTY_CM - cm) / (TANK_EMPTY_CM - TANK_FULL_CM) * 100.0f;
  return constrain(pct, 0.0f, 100.0f);
#else
  const bool low = digitalRead(FLOAT_PIN) == LOW;
  return (low == static_cast<bool>(FLOAT_LOW_IS_OK)) ? 100.0f : 0.0f;
#endif
}

void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  uint8_t addr = 0;
  if (line.startsWith("ezo ph ")) addr = EZO_PH_ADDR;
  if (line.startsWith("ezo ec ")) addr = EZO_EC_ADDR;
  if (addr == 0) {
    Serial.println("usage : ezo ph <commande> | ezo ec <commande>  (ex. ezo ph Cal,mid,7.00)");
    return;
  }
  char buf[40];
  const bool ok = ezo(addr, line.substring(7).c_str(), 1600, buf, sizeof buf);
  Serial.printf("%s : %s\n", ok ? "ok" : "erreur", buf);
}

}  // namespace

void setup() {
  node.begin();
  Wire.begin();
  ds18b20.begin();
#ifdef TANK_TRIG_PIN
  pinMode(TANK_TRIG_PIN, OUTPUT);
  pinMode(TANK_ECHO_PIN, INPUT);
#else
  pinMode(FLOAT_PIN, INPUT_PULLUP);
#endif
}

void loop() {
  node.loop();
  handleSerial();
  if (millis() - lastRead >= READ_PERIOD_MS || lastRead == 0) {
    lastRead = millis();
    ds18b20.requestTemperatures();
    float tEau = ds18b20.getTempCByIndex(0);
    if (tEau == DEVICE_DISCONNECTED_C) tEau = NAN;
    node.publishReading("temp_eau", tEau);
    node.publishReading("ph", readEzo(EZO_PH_ADDR, tEau), nullptr, 2);
    node.publishReading("ec", readEzo(EZO_EC_ADDR, tEau) / 1000.0f, nullptr, 2);  // µS -> mS/cm
    node.publishReading("niveau_cuve", tankLevel(), nullptr, 0);
  }
  delay(10);
}
