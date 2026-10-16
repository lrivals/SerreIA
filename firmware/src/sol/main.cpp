// Nœud sol (esp32-02, docs/06 §1.3) : sondes capacitives v1.2 / v2.0 sur les ADC, une par
// emplacement en terre. Les sondes ne sont alimentées que pendant la mesure (GPIO
// SOIL_POWER_PIN), moyenne de SOIL_SAMPLES lectures, conversion en % avec l'étalonnage
// sec / dans l'eau stocké en NVS. Publication : serre/<zone>/capteur/humidite_sol avec le
// champ `emplacement`.
//
// Étalonnage par le port série (115200 bauds), sonde i (0, 1…) :
//   cal sec <i>   sonde à l'air libre, sèche
//   cal eau <i>   sonde plongée dans l'eau jusqu'au trait
//   cal show      valeurs brutes actuelles et étalonnage

#include <Arduino.h>
#include <Preferences.h>

#include "node_config.h"
#include "serre_node.h"
#include "soil.h"

namespace {

serre::Node node(NODE_ID, NODE_ZONE);
Preferences prefs;
const SoilProbe kProbes[] = SOIL_PROBES;
constexpr int kN = sizeof(kProbes) / sizeof(kProbes[0]);
float dryMv[kN], wetMv[kN];
uint32_t lastRead = 0;

void loadCalibration() {
  prefs.begin("sol", false);
  for (int i = 0; i < kN; ++i) {
    char key[8];
    snprintf(key, sizeof key, "sec%d", i);
    dryMv[i] = prefs.getFloat(key, SOIL_DEFAULT_DRY_MV);
    snprintf(key, sizeof key, "eau%d", i);
    wetMv[i] = prefs.getFloat(key, SOIL_DEFAULT_WET_MV);
  }
}

// Moyenne des tensions de toutes les sondes, alimentées le temps de la mesure.
void measure(float* mv) {
  digitalWrite(SOIL_POWER_PIN, HIGH);
  delay(SOIL_WARMUP_MS);
  for (int i = 0; i < kN; ++i) {
    uint32_t sum = 0;
    for (int k = 0; k < SOIL_SAMPLES; ++k) {
      sum += analogReadMilliVolts(kProbes[i].pin);
      delay(2);
    }
    mv[i] = static_cast<float>(sum) / SOIL_SAMPLES;
  }
  digitalWrite(SOIL_POWER_PIN, LOW);
}

void handleSerial() {
  if (!Serial.available()) return;
  String line = Serial.readStringUntil('\n');
  line.trim();
  float mv[kN];
  if (line == "cal show") {
    measure(mv);
    for (int i = 0; i < kN; ++i) {
      Serial.printf("sonde %d (%s) : %.0f mV, sec %.0f, eau %.0f -> %.1f %%\n", i,
                    kProbes[i].emplacement, mv[i], dryMv[i], wetMv[i],
                    serre::soilPercent(mv[i], dryMv[i], wetMv[i]));
    }
    return;
  }
  char which[4];
  int i = -1;
  if (sscanf(line.c_str(), "cal %3s %d", which, &i) != 2 || i < 0 || i >= kN) {
    Serial.println("usage : cal sec <i> | cal eau <i> | cal show");
    return;
  }
  measure(mv);
  char key[8];
  snprintf(key, sizeof key, "%s%d", which, i);
  if (strcmp(which, "sec") == 0) {
    dryMv[i] = mv[i];
  } else if (strcmp(which, "eau") == 0) {
    wetMv[i] = mv[i];
  } else {
    Serial.println("usage : cal sec <i> | cal eau <i> | cal show");
    return;
  }
  prefs.putFloat(key, mv[i]);
  Serial.printf("sonde %d : %s = %.0f mV enregistré\n", i, which, mv[i]);
}

}  // namespace

void setup() {
  node.begin();
  pinMode(SOIL_POWER_PIN, OUTPUT);
  digitalWrite(SOIL_POWER_PIN, LOW);
  analogReadResolution(12);
  for (const auto& p : kProbes) analogSetPinAttenuation(p.pin, ADC_11db);
  loadCalibration();
}

void loop() {
  node.loop();
  handleSerial();
  if (millis() - lastRead >= READ_PERIOD_MS || lastRead == 0) {
    lastRead = millis();
    float mv[kN];
    measure(mv);
    for (int i = 0; i < kN; ++i) {
      node.publishReading("humidite_sol", serre::soilPercent(mv[i], dryMv[i], wetMv[i]),
                          kProbes[i].emplacement);
    }
  }
  delay(10);
}
