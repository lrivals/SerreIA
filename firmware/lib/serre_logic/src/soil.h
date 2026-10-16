// Conversion d'une sonde capacitive en % d'humidité du substrat avec l'étalonnage
// sec / dans l'eau (une sonde capacitive lit une tension plus haute à sec).
#pragma once

namespace serre {

inline float soilPercent(float mv, float dryMv, float wetMv) {
  if (dryMv <= wetMv) return -1.0f;  // étalonnage invalide -> hors plage -> qualite erreur
  float pct = (dryMv - mv) / (dryMv - wetMv) * 100.0f;
  if (pct < 0.0f && pct > -5.0f) pct = 0.0f;  // petite dérive : bornée, pas une erreur
  if (pct > 100.0f && pct < 105.0f) pct = 100.0f;
  return pct;
}

}  // namespace serre
