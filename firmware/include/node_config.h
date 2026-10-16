// Configuration matérielle des nœuds (docs/06 §1.3). NODE_ID et NODE_ZONE viennent de
// platformio.ini ; le reste se règle ici selon le câblage.
#pragma once

#ifndef NODE_ID
#define NODE_ID "esp32-00"
#endif
#ifndef NODE_ZONE
#define NODE_ZONE "z1"
#endif

// --- commun ------------------------------------------------------------------------
#define READ_PERIOD_MS 30000UL       // lecture des capteurs toutes les 30 s
#define WATCHDOG_TIMEOUT_MS 30000UL  // watchdog matériel (tâche loop)
#define MQTT_LOST_DEGRADED_MS 120000UL  // perte MQTT > 2 min -> mode dégradé

// Brochage XIAO ESP32-C6 : D0=GPIO0 D1=GPIO1 D2=GPIO2 D3=GPIO21 D4=GPIO22 (SDA)
// D5=GPIO23 (SCL) D6=GPIO16 (TX) D7=GPIO17 (RX) D8=GPIO19 D9=GPIO20 D10=GPIO18.

// --- nœud air (esp32-01) -------------------------------------------------------------
#define BMP280_ADDR 0x76            // 0x77 si SDO à VCC
#define BH1750_ADDR 0x23
#define LD2450_BAUD 256000
#define PRESENCE_REMINDER_MS 30000UL  // rappel de `presence` même sans changement

// --- nœud sol (esp32-02) -------------------------------------------------------------
// Une sonde capacitive par emplacement : broche ADC et emplacement (docs/09).
struct SoilProbe {
  int pin;
  const char* emplacement;
};
#define SOIL_PROBES {{D0, "z1-A1"}, {D1, "z1-A2"}}
#define SOIL_POWER_PIN D3            // alimentation commutée des sondes (MOSFET / GPIO)
#define SOIL_WARMUP_MS 200
#define SOIL_SAMPLES 16
// Valeurs brutes par défaut (mV) avant étalonnage `cal sec <i>` / `cal eau <i>`.
#define SOIL_DEFAULT_DRY_MV 2600
#define SOIL_DEFAULT_WET_MV 1100

// --- nœud solution (esp32-03) --------------------------------------------------------
#define EZO_PH_ADDR 0x63
#define EZO_EC_ADDR 0x64
#define ONEWIRE_PIN D3               // DS18B20 (résistance de tirage 4,7 kΩ)
#define FLOAT_PIN D8                 // flotteur : fermé (LOW) = niveau suffisant
#define FLOAT_LOW_IS_OK 1
// Option ultrason JSN-SR04T (niveau en %) au lieu du flotteur : décommenter.
// #define TANK_TRIG_PIN D9
// #define TANK_ECHO_PIN D10
#define TANK_EMPTY_CM 60.0f          // distance capteur -> fond
#define TANK_FULL_CM 10.0f           // distance capteur -> niveau plein

// --- nœud actionneurs (esp32-04) -----------------------------------------------------
// type = segment <actionneur> du topic (common/mqtt/topics.py) ; pwm : LEDC 0..100 %.
struct ActuatorPin {
  const char* zone;
  const char* type;
  int pin;
  bool pwm;
};
#define ACTUATOR_PINS                    \
  {                                      \
    {"z1", "ventilo", D0, true},         \
    {"z1", "chauffage", D1, false},      \
    {"z1", "brumisateur", D2, false},    \
    {"z1", "led", D3, true},             \
    {"z1", "pompe_nutri", D8, false},    \
  }
// Plus d'actionneurs (zone hydro z2 : pompe_ph_down, pompe_nutri_a/b) : un second nœud
// actionneurs avec NODE_ZONE "z2", ou un expandeur I²C (MCP23017) sur D4/D5.
#define MAX_PUMP_S 1800.0f           // limite firmware, >= duree_max_s de serre.yaml
#define PUMP_FLOAT_PIN D9            // flotteur de la cuve câblé en local (-1 : aucun)
#define TANK_MIN_PCT 10.0f           // secours : niveau_cuve reçu par MQTT
#define PWM_FREQ_HZ 25000            // ventilateurs 4 fils ; LED : fréquence du driver
#define PWM_BITS 10

// Mode dégradé (perte MQTT > 2 min) : programme horaire minimal, heure locale.
#define DEGRADED_WATER_HOURS {7, 13, 19}
#define DEGRADED_WATER_S 30
#define DEGRADED_VENT_FROM_H 10      // ventilation 10 min par heure entre 10 h et 18 h
#define DEGRADED_VENT_TO_H 18
#define DEGRADED_VENT_MIN 10
