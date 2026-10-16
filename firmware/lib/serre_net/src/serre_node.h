// Socle commun des nœuds (docs/06 §3) : Wi-Fi, MQTT vers mosquitto sur le Pi avec LWT
// `serre/<noeud>/status = offline`, horloge NTP (horodatage ISO 8601 UTC du contrat),
// mises à jour OTA, watchdog matériel, publication des mesures validées.
#pragma once

#include <Arduino.h>
#include <PubSubClient.h>
#include <WiFi.h>

#include <functional>

namespace serre {

using MessageHandler = std::function<void(const char* topic, const uint8_t* payload, size_t len)>;

class Node {
 public:
  Node(const char* nodeId, const char* zone) : id_(nodeId), zone_(zone), mqtt_(wifi_) {}

  void begin();
  // À appeler à chaque tour de loop() : connexions, OTA, watchdog.
  void loop();

  const char* id() const { return id_; }
  const char* zone() const { return zone_; }

  bool connected() { return mqtt_.connected(); }
  // Durée depuis la dernière connexion MQTT active (0 si connecté).
  uint32_t msSinceMqtt() const;
  // Heure valide (NTP synchronisé au moins une fois depuis le démarrage).
  bool timeValid() const;
  String isoNow() const;  // "2026-10-12T14:03:00Z"

  // Mesure du contrat sur serre/<zone>/capteur/<type> ; qualité par la plage physique.
  // Rien n'est publié sans heure valide (le contrat exige `ts`) ni pour une valeur NaN
  // (lecture échouée : le contrôleur signale le capteur muet).
  bool publishReading(const char* type, float value, const char* emplacement = nullptr,
                      int decimals = 1);
  bool publish(const char* topic, const char* payload, bool retain);
  void subscribe(const char* pattern, MessageHandler handler);

 private:
  void connectWifi();
  bool connectMqtt();
  void onMessage(char* topic, uint8_t* payload, unsigned int len);

  const char* id_;
  const char* zone_;
  WiFiClient wifi_;
  PubSubClient mqtt_;
  static constexpr int kMaxSubs = 4;
  String patterns_[kMaxSubs];
  MessageHandler handlers_[kMaxSubs];
  int nSubs_ = 0;
  uint32_t lastConnectedMs_ = 0;
  uint32_t lastAttemptMs_ = 0;
  bool everConnected_ = false;
};

}  // namespace serre
