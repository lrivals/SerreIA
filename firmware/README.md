# Firmware ESP32

Projets PlatformIO des nœuds capteurs et actionneurs (voir [doc 06](../docs/06-capteurs-controle.md)). Toutes les cartes sont des **Seeed XIAO ESP32-C6** : un firmware de base commun et un environnement par rôle.
Les messages respectent le contrat MQTT de [doc 01](../docs/01-architecture.md#2-contrat-mqtt). La cohérence avec `common/mqtt/` (types de capteurs, plages physiques, actionneurs, formes des topics) est vérifiée côté Python par `tests/test_firmware_contract.py`.

> Statut : code écrit, **pas encore compilé sur cible** (PlatformIO absent de la machine de développement). La logique pure (`lib/serre_logic`) est testée sur PC. Premier `pio run` à faire.

## Organisation

| Chemin | Contenu |
|---|---|
| `platformio.ini` | plateforme **pioarduino** `55.03.312-1` (core Arduino 3.x), `board = seeed_xiao_esp32c6`, envs `air`, `sol`, `solution`, `actionneurs`, `native` |
| `include/node_config.h` | brochage et réglages de chaque nœud (sondes, actionneurs, limites, mode dégradé) |
| `include/secrets.example.h` | Wi-Fi, broker, mot de passe OTA, fuseau : à copier en `secrets.h` (ignoré par git) |
| `lib/serre_logic/` | logique pure, sans Arduino : plages → `qualite` (`ranges.h`), trames HLK-LD2450 (`ld2450.h`), commandes et sécurités pompes (`command.h`), programme du mode dégradé (`degraded.h`), conversion des sondes de sol (`soil.h`) |
| `lib/serre_net/` | socle `serre::Node` : Wi-Fi, MQTT avec LWT `serre/<noeud>/status`, NTP (horodatage UTC), OTA, watchdog matériel, `publishReading()` |
| `src/<rôle>/main.cpp` | programme de chaque nœud |
| `test/test_logic/` | tests Unity de `serre_logic` (`pio test -e native`) |

## Nœuds

| Env | Nœud | Matériel | Broches | Publie |
|---|---|---|---|---|
| `air` | `esp32-01` | SHT41 (0x44), BMP280 (0x76), GY-302/BH1750 (0x23), SCD41 (0x62, `HAS_SCD41`), HLK-LD2450 | I²C D4/D5, UART RX D7 / TX D6 (256 000 bauds), radar en 5 V | `temperature`, `humidite`, `pression`, `lux`, `co2` toutes les 30 s ; `presence` à chaque changement + toutes les 30 s |
| `sol` | `esp32-02` | sondes capacitives v1.2 / v2.0 | ADC D0, D1… (`SOIL_PROBES`), alimentation D3 | `humidite_sol` par emplacement (champ `emplacement`) |
| `solution` | `esp32-03` | EZO-pH (0x63), EZO-EC (0x64), DS18B20, flotteur ou JSN-SR04T | I²C, 1-Wire D3, flotteur D8 | `ph`, `ec` (mS/cm), `temp_eau`, `niveau_cuve` (%) |
| `actionneurs` | `esp32-04` | relais / MOSFET / PWM (`ACTUATOR_PINS`) | D0–D3, D8 ; flotteur local D9 | `etat/<actionneur>` (retain) |

Logique en **3,3 V** : jamais de 5 V sur une broche. Le radar est alimenté en 5 V mais ses sorties sont en 3,3 V.

## Sécurités locales (indépendantes du Pi)

- Commande de pompe sans `duree_s`, ou au-delà de `MAX_PUMP_S`, **refusée**. L'échéance `duree_s` est coupée par le nœud lui-même.
- Cuve vide : pompes interdites et coupées. La détection passe par le flotteur câblé sur le nœud actionneurs, et en secours par le dernier `niveau_cuve` reçu.
- Perte MQTT supérieure à 2 min → **mode dégradé**. Arrosage `DEGRADED_WATER_S` aux heures `DEGRADED_WATER_HOURS`, ventilation 10 min par heure entre 10 h et 18 h, tout le reste à l'arrêt. Sans heure NTP valide, tout reste à l'arrêt.
- Démarrage : toutes les sorties à l'arrêt avant toute connexion. Les états réels sont republiés à chaque (re)connexion.
- Watchdog matériel de 30 s sur la boucle principale, LWT `offline` publié par le broker.
- Validation : une valeur hors plage physique est publiée avec `qualite: erreur`. Une lecture échouée n'est pas publiée : le contrôleur signale le capteur muet au bout de 5 min.

Limite connue : PubSubClient publie en QoS 0 (la souscription est en QoS 1). Les états `etat/` sont retenus et republiés à la reconnexion, ce qui compense une perte.

## Mise en route

```bash
pip install platformio                       # ou l'extension VS Code
cp include/secrets.example.h include/secrets.h && $EDITOR include/secrets.h
pio test -e native                           # logique pure, sur le PC
pio run -e air -t upload                     # première programmation en USB-C
pio device monitor                           # 115200 bauds
pio run -e air -t upload --upload-port esp32-01.local   # mises à jour suivantes en OTA
```

Pour l'OTA, ajouter `upload_protocol = espota` et `upload_flags = --auth=<OTA_PASSWORD>` à l'environnement, ou passer par l'extension.

## Étalonnage

- **Sondes de sol**, sur le port série du nœud `sol`. Sonde sèche à l'air : `cal sec 0`. Sonde dans l'eau jusqu'au trait : `cal eau 0`. Contrôle : `cal show`. Les valeurs sont gardées en NVS.
- **pH**, étalonnage 3 points mensuel : `ezo ph Cal,mid,7.00`, puis `ezo ph Cal,low,4.00`, puis `ezo ph Cal,high,10.00`.
- **EC** : `ezo ec Cal,dry`, puis `ezo ec Cal,1413` (solution 1 413 µS/cm, sonde K1.0).
- ⚠️ **Isolation galvanique** obligatoire entre les sondes pH et EC plongées dans la même cuve.
