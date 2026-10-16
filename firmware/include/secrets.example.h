// Copier en secrets.h (ignoré par git) et renseigner.
#pragma once

#define WIFI_SSID "serre"
#define WIFI_PASSWORD "changeme"
#define MQTT_HOST "192.168.1.10"  // le Pi (mosquitto)
#define MQTT_PORT 1883
#define MQTT_USER ""              // vide : sans authentification
#define MQTT_PASSWORD ""
#define OTA_PASSWORD "changeme"
// Fuseau POSIX (heure locale du programme horaire du mode dégradé).
#define TZ_POSIX "CET-1CEST,M3.5.0,M10.5.0/3"
#define NTP_SERVER "pool.ntp.org"  // ou l'adresse du Pi s'il sert NTP (chrony)
// Antenne externe U.FL (portée, paroi métallique) : 1 ; céramique intégrée : 0.
#define EXTERNAL_ANTENNA 0
