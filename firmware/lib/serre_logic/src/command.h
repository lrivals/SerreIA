// Commande d'actionneur (contrat MQTT, docs/01 §2) et règles de sécurité locales du
// firmware, indépendantes du Pi (docs/06 §3) :
//   - toute commande de pompe sans `duree_s`, ou au-delà de la durée max, est refusée ;
//   - pompes interdites quand la cuve est vide ;
//   - `pwm` exige `valeur` 0..100, et seulement lui.
#pragma once

#include <ArduinoJson.h>

#include <cmath>
#include <cstring>

namespace serre {

enum class Action { Off, On, Pwm };

struct Command {
  Action action = Action::Off;
  float valeur = NAN;   // pwm : 0..100
  float duree_s = NAN;  // NaN : sans échéance
};

enum class Verdict { Ok, Invalid, PumpWithoutDuration, PumpTooLong, TankEmpty };

inline const char* verdictText(Verdict v) {
  switch (v) {
    case Verdict::Ok: return "ok";
    case Verdict::Invalid: return "commande invalide";
    case Verdict::PumpWithoutDuration: return "pompe sans duree_s";
    case Verdict::PumpTooLong: return "duree_s au-dela du maximum";
    case Verdict::TankEmpty: return "cuve vide";
  }
  return "?";
}

inline bool isPump(const char* type) { return std::strncmp(type, "pompe_", 6) == 0; }

// Les actionneurs du contrat (Actuator de common/mqtt/topics.py).
constexpr const char* kActuators[] = {
    "pompe_nutri", "pompe_ph_down", "pompe_nutri_a", "pompe_nutri_b",
    "ventilo",     "led",           "brumisateur",   "chauffage",
};

inline Verdict parseCommand(const char* json, size_t len, Command& out) {
  JsonDocument doc;
  if (deserializeJson(doc, json, len)) return Verdict::Invalid;
  const char* action = doc["action"] | "";
  if (std::strcmp(action, "off") == 0) {
    out.action = Action::Off;
  } else if (std::strcmp(action, "on") == 0) {
    out.action = Action::On;
  } else if (std::strcmp(action, "pwm") == 0) {
    out.action = Action::Pwm;
  } else {
    return Verdict::Invalid;
  }
  out.valeur = doc["valeur"].isNull() ? NAN : doc["valeur"].as<float>();
  out.duree_s = doc["duree_s"].isNull() ? NAN : doc["duree_s"].as<float>();
  const bool hasValeur = !std::isnan(out.valeur);
  if ((out.action == Action::Pwm) != hasValeur) return Verdict::Invalid;
  if (hasValeur && (out.valeur < 0 || out.valeur > 100)) return Verdict::Invalid;
  if (!std::isnan(out.duree_s) && out.duree_s <= 0) return Verdict::Invalid;
  return Verdict::Ok;
}

// Sécurités locales, appliquées après le décodage.
inline Verdict checkCommand(const char* type, const Command& c, float maxPumpS, bool tankEmpty) {
  if (c.action == Action::Off || !isPump(type)) return Verdict::Ok;
  if (std::isnan(c.duree_s)) return Verdict::PumpWithoutDuration;
  if (c.duree_s > maxPumpS) return Verdict::PumpTooLong;
  if (tankEmpty) return Verdict::TankEmpty;
  return Verdict::Ok;
}

// Niveau 0..1 d'un actionneur (on = 1, pwm = valeur / 100).
inline float level(const Command& c) {
  if (c.action == Action::Off) return 0.0f;
  return c.action == Action::On ? 1.0f : c.valeur / 100.0f;
}

}  // namespace serre
