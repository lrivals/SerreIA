// Nœud air (esp32-01, docs/06 §1.3) : SHT41 (T, HR), BMP280 (pression), GY-302 / BH1750
// (lux), SCD41 (CO₂, option HAS_SCD41) sur le même bus I²C (D4/D5, adresses toutes
// différentes), radar HLK-LD2450 sur l'UART (D6/D7).
//
// - mesures toutes les 30 s -> serre/<zone>/capteur/<type> ;
// - radar : lecture continue des trames, `presence` (nombre de cibles) à chaque changement
//   et rappel toutes les 30 s.
// La température du BMP280 (échauffement de la carte) et celle du SCD41 ne sont pas
// publiées : `temperature` / `humidite` viennent du SHT41.

#include <Adafruit_BMP280.h>
#include <Adafruit_SHT4x.h>
#include <Arduino.h>
#include <BH1750.h>
#include <Wire.h>

#include "ld2450.h"
#include "node_config.h"
#include "serre_node.h"

#if HAS_SCD41
#include <SensirionI2cScd4x.h>
#endif

namespace {

serre::Node node(NODE_ID, NODE_ZONE);
Adafruit_SHT4x sht4;
Adafruit_BMP280 bmp(&Wire);
BH1750 light(BH1750_ADDR);
#if HAS_SCD41
SensirionI2cScd4x scd4x;
#endif
serre::Ld2450Parser radar;

bool hasSht = false, hasBmp = false, hasLux = false, hasScd = false;
uint32_t lastRead = 0, lastPresence = 0;
int presence = -1;

void beginSensors() {
  Wire.begin();  // SDA = D4, SCL = D5
  hasSht = sht4.begin(&Wire);
  if (hasSht) {
    sht4.setPrecision(SHT4X_HIGH_PRECISION);
    sht4.setHeater(SHT4X_NO_HEATER);
  }
  hasBmp = bmp.begin(BMP280_ADDR);
  if (hasBmp) {
    bmp.setSampling(Adafruit_BMP280::MODE_NORMAL, Adafruit_BMP280::SAMPLING_X2,
                    Adafruit_BMP280::SAMPLING_X16, Adafruit_BMP280::FILTER_X16,
                    Adafruit_BMP280::STANDBY_MS_500);
  }
  hasLux = light.begin(BH1750::CONTINUOUS_HIGH_RES_MODE, BH1750_ADDR, &Wire);
#if HAS_SCD41
  scd4x.begin(Wire, SCD41_I2C_ADDR_62);
  scd4x.wakeUp();
  scd4x.stopPeriodicMeasurement();
  scd4x.reinit();
  hasScd = scd4x.startPeriodicMeasurement() == 0;
#endif
  Serial.printf("SHT41 %d, BMP280 %d, BH1750 %d, SCD41 %d\n", hasSht, hasBmp, hasLux, hasScd);
  Serial1.begin(LD2450_BAUD, SERIAL_8N1, D7, D6);  // RX = D7, TX = D6
}

void readSensors() {
  if (hasSht) {
    sensors_event_t hum, temp;
    if (sht4.getEvent(&hum, &temp)) {
      node.publishReading("temperature", temp.temperature);
      node.publishReading("humidite", hum.relative_humidity);
    }
  }
  if (hasBmp) node.publishReading("pression", bmp.readPressure() / 100.0f);
  if (hasLux) {
    const float lux = light.readLightLevel();  // < 0 : erreur de lecture
    if (lux >= 0) node.publishReading("lux", lux, nullptr, 0);
  }
#if HAS_SCD41
  if (hasScd) {
    bool ready = false;
    if (scd4x.getDataReadyStatus(ready) == 0 && ready) {
      uint16_t co2 = 0;
      float t = 0, rh = 0;
      if (scd4x.readMeasurement(co2, t, rh) == 0 && co2 > 0) node.publishReading("co2", co2, nullptr, 0);
    }
  }
#endif
}

void readRadar() {
  while (Serial1.available()) {
    if (!radar.feed(static_cast<uint8_t>(Serial1.read()))) continue;
    const int n = radar.count();
    if (n != presence) {  // changement d'état : publication immédiate
      if (node.publishReading("presence", n, nullptr, 0)) {
        presence = n;
        lastPresence = millis();
      }
    }
  }
  if (presence >= 0 && millis() - lastPresence >= PRESENCE_REMINDER_MS) {
    node.publishReading("presence", presence, nullptr, 0);
    lastPresence = millis();
  }
}

}  // namespace

void setup() {
  node.begin();
  beginSensors();
}

void loop() {
  node.loop();
  readRadar();
  if (millis() - lastRead >= READ_PERIOD_MS || lastRead == 0) {
    lastRead = millis();
    readSensors();
  }
  delay(5);
}
