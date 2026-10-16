// Plages physiques et unités par type de capteur (docs/06 §3 : validation locale).
// Même table que common/mqtt/ranges.py (vérifiée par tests/test_firmware_contract.py) :
// une valeur hors plage est publiée avec `qualite: erreur`.
#pragma once

#include <cmath>
#include <cstring>

namespace serre {

struct SensorRange {
  const char* type;  // segment <type> du topic serre/<zone>/capteur/<type>
  float min;
  float max;
  const char* unite;
};

// clang-format off
constexpr SensorRange kRanges[] = {
    {"temperature",  -40.0f,    85.0f, "°C"},
    {"humidite",       0.0f,   100.0f, "%"},
    {"co2",          400.0f,  5000.0f, "ppm"},
    {"lux",            0.0f, 65535.0f, "lx"},
    {"ph",             0.0f,    14.0f, "pH"},
    {"ec",             0.0f,    20.0f, "mS/cm"},
    {"temp_eau",     -10.0f,    85.0f, "°C"},
    {"niveau_cuve",    0.0f,   100.0f, "%"},
    {"pression",     300.0f,  1100.0f, "hPa"},
    {"presence",       0.0f,     3.0f, "cibles"},
    {"humidite_sol",   0.0f,   100.0f, "%"},
};
// clang-format on

inline const SensorRange* findRange(const char* type) {
  for (const auto& r : kRanges) {
    if (std::strcmp(r.type, type) == 0) return &r;
  }
  return nullptr;
}

// "ok" dans la plage, "erreur" hors plage, NaN ou type inconnu.
inline const char* quality(const char* type, float value) {
  const SensorRange* r = findRange(type);
  if (r == nullptr || std::isnan(value)) return "erreur";
  return (value >= r->min && value <= r->max) ? "ok" : "erreur";
}

}  // namespace serre
