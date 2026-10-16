// Nœud actionneurs (esp32-04, docs/06 §2–3) : relais, MOSFET et PWM.
//
// - abonnement à serre/<zone>/cmd/# -> exécution -> serre/<zone>/etat/<actionneur> (retain) ;
// - sécurités locales indépendantes du Pi : pompe sans `duree_s` ou au-delà de MAX_PUMP_S
//   refusée, échéance `duree_s` coupée par le nœud, pompes interdites cuve vide (flotteur
//   câblé sur PUMP_FLOAT_PIN, et en secours le topic niveau_cuve de la zone) ;
// - perte MQTT supérieure à 2 min -> mode dégradé : programme horaire minimal d'arrosage et
//   de ventilation (heure locale, seulement si l'heure a été synchronisée), tout le reste
//   à l'arrêt ; retour au pilotage normal (tout à l'arrêt, puis commandes) à la reconnexion.
//
// Au démarrage, tout est à l'arrêt et l'état `off` est publié.

#include <Arduino.h>
#include <ArduinoJson.h>
#include <time.h>

#include "command.h"
#include "degraded.h"
#include "node_config.h"
#include "serre_node.h"

namespace {

serre::Node node(NODE_ID, NODE_ZONE);

struct Output {
  ActuatorPin cfg;
  serre::Command cmd;      // état courant
  uint32_t untilMs = 0;    // échéance (0 : aucune)
  bool degraded = false;   // piloté par le mode dégradé
};

const ActuatorPin kPins[] = ACTUATOR_PINS;
constexpr int kN = sizeof(kPins) / sizeof(kPins[0]);
Output outputs[kN];
float mqttTankPct = NAN;  // dernier niveau_cuve reçu (secours du flotteur)
bool inDegraded = false;
const int kWaterHours[] = DEGRADED_WATER_HOURS;
const serre::DegradedPlan kPlan = {kWaterHours, sizeof(kWaterHours) / sizeof(kWaterHours[0]),
                                   DEGRADED_WATER_S, DEGRADED_VENT_FROM_H, DEGRADED_VENT_TO_H,
                                   DEGRADED_VENT_MIN};

bool tankEmpty() {
  if (PUMP_FLOAT_PIN >= 0 && digitalRead(PUMP_FLOAT_PIN) != LOW) return true;  // flotteur ouvert
  return !isnan(mqttTankPct) && mqttTankPct < TANK_MIN_PCT;
}

void apply(Output& o) {
  const float lvl = serre::level(o.cmd);
  if (o.cfg.pwm) {
    ledcWrite(o.cfg.pin, static_cast<uint32_t>(lvl * ((1 << PWM_BITS) - 1)));
  } else {
    digitalWrite(o.cfg.pin, lvl > 0 ? HIGH : LOW);
  }
}

void publishState(const Output& o) {
  JsonDocument doc;
  doc["ts"] = node.isoNow();
  const bool pwm = o.cmd.action == serre::Action::Pwm;
  doc["action"] = o.cmd.action == serre::Action::Off ? "off" : (pwm ? "pwm" : "on");
  if (pwm) {
    doc["valeur"] = o.cmd.valeur;
  } else {
    doc["valeur"] = nullptr;
  }
  char payload[128], topic[64];
  serializeJson(doc, payload, sizeof payload);
  snprintf(topic, sizeof topic, "serre/%s/etat/%s", o.cfg.zone, o.cfg.type);
  if (node.timeValid()) node.publish(topic, payload, true);
}

void set(Output& o, const serre::Command& c, uint32_t untilMs) {
  const bool changed = o.cmd.action != c.action ||
                       (c.action == serre::Action::Pwm && o.cmd.valeur != c.valeur);
  o.cmd = c;
  o.untilMs = untilMs;
  apply(o);
  if (changed) publishState(o);
}

void off(Output& o) { set(o, serre::Command{}, 0); }

void onCommand(const char* topic, const uint8_t* payload, size_t len) {
  // serre/<zone>/cmd/<actionneur>
  char zone[8], type[24];
  if (sscanf(topic, "serre/%7[^/]/cmd/%23s", zone, type) != 2) return;
  for (auto& o : outputs) {
    if (strcmp(o.cfg.zone, zone) != 0 || strcmp(o.cfg.type, type) != 0) continue;
    serre::Command c;
    serre::Verdict v = serre::parseCommand(reinterpret_cast<const char*>(payload), len, c);
    if (v == serre::Verdict::Ok) v = serre::checkCommand(type, c, MAX_PUMP_S, tankEmpty());
    if (v != serre::Verdict::Ok) {
      Serial.printf("commande refusée %s : %s\n", topic, serre::verdictText(v));
      return;
    }
    if (inDegraded) return;  // ne devrait pas arriver : reçue = connecté
    const uint32_t until = isnan(c.duree_s) ? 0 : millis() + static_cast<uint32_t>(c.duree_s * 1000);
    set(o, c, until);
    return;
  }
}

void onTankLevel(const char* topic, const uint8_t* payload, size_t len) {
  JsonDocument doc;
  if (deserializeJson(doc, payload, len)) return;
  if (strcmp(doc["qualite"] | "erreur", "erreur") == 0) return;
  mqttTankPct = doc["valeur"] | NAN;
}

void enforce() {
  const bool empty = tankEmpty();
  for (auto& o : outputs) {
    if (o.cmd.action == serre::Action::Off) continue;
    const bool expired = o.untilMs != 0 && static_cast<int32_t>(millis() - o.untilMs) >= 0;
    if (expired || (empty && serre::isPump(o.cfg.type))) off(o);
  }
}

void degradedMode() {
  const bool lost = node.msSinceMqtt() > MQTT_LOST_DEGRADED_MS;
  if (lost && !inDegraded) {
    inDegraded = true;
    Serial.println("perte MQTT > 2 min : mode dégradé");
    for (auto& o : outputs) off(o);
  } else if (!lost && inDegraded) {
    inDegraded = false;
    Serial.println("MQTT revenu : fin du mode dégradé");
    for (auto& o : outputs) off(o);
  }
  if (!inDegraded || !node.timeValid()) return;
  time_t now = time(nullptr);
  struct tm local;
  localtime_r(&now, &local);
  const bool water = serre::degradedWater(kPlan, local.tm_hour, local.tm_min, local.tm_sec);
  const bool vent = serre::degradedVent(kPlan, local.tm_hour, local.tm_min);
  for (auto& o : outputs) {
    bool want = false;
    if (strcmp(o.cfg.type, "pompe_nutri") == 0) want = water && !tankEmpty();
    if (strcmp(o.cfg.type, "ventilo") == 0) want = vent;
    const bool isOn = o.cmd.action != serre::Action::Off;
    if (want && !isOn) {
      serre::Command c;
      c.action = o.cfg.pwm ? serre::Action::Pwm : serre::Action::On;
      c.valeur = o.cfg.pwm ? 100.0f : NAN;
      set(o, c, 0);
    } else if (!want && isOn) {
      off(o);
    }
  }
}

}  // namespace

void setup() {
  // Sorties à l'arrêt avant toute connexion.
  for (int i = 0; i < kN; ++i) {
    outputs[i].cfg = kPins[i];
    if (kPins[i].pwm) {
      ledcAttach(kPins[i].pin, PWM_FREQ_HZ, PWM_BITS);
      ledcWrite(kPins[i].pin, 0);
    } else {
      pinMode(kPins[i].pin, OUTPUT);
      digitalWrite(kPins[i].pin, LOW);
    }
  }
  if (PUMP_FLOAT_PIN >= 0) pinMode(PUMP_FLOAT_PIN, INPUT_PULLUP);
  node.begin();
  char pattern[48];
  for (int i = 0; i < kN; ++i) {  // une souscription par zone
    bool seen = false;
    for (int j = 0; j < i; ++j) seen = seen || strcmp(kPins[j].zone, kPins[i].zone) == 0;
    if (seen) continue;
    snprintf(pattern, sizeof pattern, "serre/%s/cmd/#", kPins[i].zone);
    node.subscribe(pattern, onCommand);
    snprintf(pattern, sizeof pattern, "serre/%s/capteur/niveau_cuve", kPins[i].zone);
    node.subscribe(pattern, onTankLevel);
  }
}

void loop() {
  static bool wasConnected = false, mustPublish = false;
  node.loop();
  const bool connected = node.connected();
  if (connected && !wasConnected) mustPublish = true;  // (re)connexion
  wasConnected = connected;
  if (mustPublish && connected && node.timeValid()) {
    // États réels (retain) : au démarrage, et après le mode dégradé ou une coupure.
    for (const auto& o : outputs) publishState(o);
    mustPublish = false;
  }
  enforce();
  degradedMode();
  delay(5);
}
