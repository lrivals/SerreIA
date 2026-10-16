// Mode dégradé (perte MQTT > 2 min, docs/06 §3) : programme horaire minimal pour
// l'arrosage et la ventilation, en heure locale ; tout le reste à l'arrêt. Sans heure
// valide (NTP jamais synchronisé), aucun programme : tout reste à off.
#pragma once

#include <cstddef>

namespace serre {

struct DegradedPlan {
  const int* waterHours;
  size_t nWaterHours;
  int waterSeconds;
  int ventFromH;
  int ventToH;
  int ventMinutes;
};

// Pompe d'arrosage : les `waterSeconds` premières secondes des heures prévues.
inline bool degradedWater(const DegradedPlan& p, int hour, int minute, int second) {
  for (size_t i = 0; i < p.nWaterHours; ++i) {
    if (hour == p.waterHours[i] && minute * 60 + second < p.waterSeconds) return true;
  }
  return false;
}

// Ventilation : les `ventMinutes` premières minutes de chaque heure de la plage de jour.
inline bool degradedVent(const DegradedPlan& p, int hour, int minute) {
  return hour >= p.ventFromH && hour < p.ventToH && minute < p.ventMinutes;
}

}  // namespace serre
