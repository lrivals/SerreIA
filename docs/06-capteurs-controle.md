# 06 — Capteurs, électronique et contrôle

## 1. Matériel des nœuds

Matériel choisi par LitWin. Tous les modules (capteurs comme actionneurs) utilisent le même microcontrôleur : un seul firmware de base, une seule carte en stock de rechange.

### 1.1 Microcontrôleur : Seeed Studio XIAO ESP32-C6

Référence : [wiki Seeed — XIAO ESP32C6](https://wiki.seeedstudio.com/xiao_esp32c6_getting_started/).

| Caractéristique | Valeur | Conséquence pour la serre |
|---|---|---|
| Processeur | ESP32-C6, RISC-V 160 MHz + cœur basse consommation 20 MHz | largement suffisant pour lire des capteurs et publier en MQTT |
| Mémoire | 512 Ko SRAM, 4 Mo flash | place pour l'OTA (deux partitions applicatives) |
| Radio | Wi-Fi 6 (2,4 GHz), Bluetooth LE 5, IEEE 802.15.4 (Zigbee, Thread, Matter) | on reste en **Wi-Fi + MQTT** vers mosquitto sur le Pi ; Thread/Zigbee gardés en option |
| Antenne | céramique intégrée (~80 m) ou externe U.FL (GPIO3 à LOW, puis GPIO14 sélectionne l'antenne) | antenne externe si la serre est loin du point d'accès ou derrière une paroi métallique |
| E/S | 11 GPIO (PWM), 7 entrées ADC (dont D0, D1, D2) | peu de broches : **un nœud = un rôle** |
| Bus | 1 I²C (SDA = D4/GPIO22, SCL = D5/GPIO23), 1 UART (TX = D6/GPIO16, RX = D7/GPIO17), 1 SPI, + LP_I²C et LP_UART | tous les capteurs I²C d'un nœud partagent le même bus |
| Alimentation | 5 V USB-C ou batterie Li-ion 3,7 V (chargeur intégré), sortie 3V3 | logique en **3,3 V** : jamais de 5 V sur une broche |
| Consommation | deep sleep ≈ 15 µA, light sleep ≈ 3 mA, modem sleep ≈ 30 mA | un nœud sol sur batterie peut dormir entre deux mesures |
| Format | 21 × 17,8 mm, −40 à 85 °C | tient dans un boîtier étanche de petite taille |

Logiciel : core Arduino `esp32` **≥ 3.0.0** (carte `XIAO_ESP32C6`). Sous PlatformIO, la plateforme officielle `espressif32` n'embarque pas encore le core 3.x : utiliser la plateforme communautaire **pioarduino** avec `board = seeed_xiao_esp32c6`.

### 1.2 Capteurs (BOM)

| Mesure | Capteur | Interface | Statut | Remarques |
|---|---|---|---|---|
| Température / humidité air | Sensirion **SHT41** | I²C (0x44) | acheté | ±0,2 °C, ±1,8 % HR ; abri ventilé contre le soleil direct |
| Pression atmosphérique | Bosch **BMP280** | I²C (0x76 ou 0x77) | acheté | tendance barométrique (arrivée de pluie, coup de froid) en complément de l'API météo ; sa température est perturbée par l'échauffement de la carte, on garde celle du SHT41 |
| Présence / mouvement | Hi-Link **HLK-LD2450** (radar 24 GHz) | UART (256 000 bauds) | acheté | suit jusqu'à 3 cibles (position X/Y, vitesse) ; alimenté en 5 V, sorties en 3,3 V ; voir l'usage en §4 |
| Lumière | **GY-302** (puce BH1750, lux) ; plus tard un capteur PAR | I²C (0x23) | acheté | le lux est mal adapté aux LED horticoles ; le PAR (µmol/m²/s) est préférable |
| Humidité du sol | sondes **capacitives** v1.2 / v2.0 | ADC | acheté | une sonde par emplacement en terre ; étalonnage sec / dans l'eau ; alimentation commutée par un GPIO pour ne l'allumer qu'à la mesure ; jamais résistif (corrosion) |
| CO₂ | Sensirion **SCD41** | I²C (0x62) | prévu | photoacoustique, mesure aussi T/HR |
| pH solution | **Atlas Scientific EZO-pH** + sonde | I²C / UART | prévu (zone hydro) | étalonnage 3 points mensuel |
| EC solution | **Atlas Scientific EZO-EC** + sonde K1.0 | I²C / UART | prévu (zone hydro) | |
| T° eau | **DS18B20** étanche | 1-Wire | prévu (zone hydro) | compensation de température pour le pH et l'EC |
| Niveau cuve | flotteur ou ultrason **JSN-SR04T** | GPIO | prévu (zone hydro) | sécurité « cuve vide » pour les pompes |

Les adresses I²C de SHT41, BMP280, SCD41 et BH1750 sont toutes différentes : les quatre capteurs se partagent le bus du nœud air sans multiplexeur.

⚠️ **Isolation galvanique obligatoire** entre les sondes pH et EC plongées dans la même cuve (cartes d'isolation Atlas, ou alimentations isolées). Sans elle, les mesures se perturbent mutuellement.

### 1.3 Répartition des nœuds

| Nœud | Rôle | Matériel | Broches utilisées |
|---|---|---|---|
| `esp32-01` | air de la zone | SHT41, BMP280, GY-302, SCD41 (prévu) + HLK-LD2450 | I²C D4/D5, UART D6/D7 |
| `esp32-02` | sol | sondes capacitives (jusqu'à 6 à 7 par nœud, limite des ADC) | ADC + 1 GPIO d'alimentation des sondes |
| `esp32-03` | solution nutritive (prévu) | EZO-pH, EZO-EC, DS18B20, niveau cuve | I²C, 1-Wire, GPIO |
| `esp32-04` | actionneurs | relais / MOSFET | GPIO / PWM |

## 2. Actionneurs

| Actionneur | Commande | Remarques |
|---|---|---|
| Pompe nutritive / arrosage | relais ou MOSFET | durée max imposée par le firmware |
| Pompes doseuses pH−, nutriments A/B | MOSFET (péristaltiques 12 V) | dosage par impulsions + temps de mélange |
| Ventilation / extraction | relais ou PWM (ventilos 4 fils) | |
| LED horticoles | driver avec entrée PWM / 0-10 V | photopériode + intensité |
| Brumisateur, chauffage | relais (SSR pour les charges secteur) | ⚠️ **230 V** : boîtier, disjoncteur différentiel, électricien si doute |

Alimentation : séparer la **logique** (5 V / 3,3 V) de la **puissance** (12 / 24 V), avec des masses reliées en étoile ; diodes de roue libre sur les charges inductives.

## 3. Firmware ESP32 — `firmware/` (PlatformIO, Arduino ou ESP-IDF)

Un nœud = un rôle (répartition en [§1.3](#13-répartition-des-nœuds)). Toutes les cartes sont des XIAO ESP32-C6 : PlatformIO avec la plateforme pioarduino, `board = seeed_xiao_esp32c6`.
- lecture des capteurs toutes les 30 s → publication sur `serre/<zone>/capteur/<type>` ;
- radar HLK-LD2450 : lecture continue des trames UART, publication de `presence` (nombre de cibles, 0 à 3) **à chaque changement** d'état, plus un rappel toutes les 30 s ;
- sondes de sol : sonde alimentée seulement pendant la mesure, moyenne de plusieurs lectures ADC, conversion en % avec l'étalonnage sec / eau stocké dans le nœud ;
- validation locale (plage physique → `qualite: erreur`) ;
- abonnement à `serre/<zone>/cmd/#` → exécution → publication de l'état (retain) ;
- **sécurités locales indépendantes du Pi** :
  - toute commande de pompe sans `duree_s`, ou au-delà d'une durée max, est refusée ou coupée ;
  - cuve vide → pompes interdites ;
  - perte MQTT supérieure à 2 min → **mode dégradé** (programme horaire minimal pour l'arrosage et la ventilation) ;
- LWT `serre/<noeud>/status = offline` ; watchdog ; mises à jour OTA.

## 4. Stratégie de contrôle — `edge/controller/`

Le « réseau de neurones » de pilotage s'introduit **progressivement**, sans jamais remplacer les sécurités.

Chaque commande émise par le contrôleur est précédée d'une **décision** enregistrée avec ses preuves (classification vision, mesures, règle, consignes) et référencée dans `Command.raison` — voir [10 — Décisions et arbre des actions](10-decisions-tracabilite.md). La configuration de la serre (zones, plantes, recettes, équipements) provient de l'interface ([09 §8](09-modele-gestion-serre.md#8-configuration-exportée-vers-le-contrôleur)).

### Niveau 0 — sécurité (`safety.py`)
Limites dures, toujours actives : T° max et min, durée max des pompes, cuve vide, pH hors [4,5 ; 8], absence de mesure depuis plus de 5 min → alerte.
Présence détectée par le radar → brumisation et traitements suspendus tant que quelqu'un est dans la serre.

### Niveau 1 — règles et régulateurs (`rules.py`)
- température et humidité : hystérésis → ventilation, brumisation, chauffage ;
- pH : dosage par impulsions (dose, attente du mélange, re-mesure), jamais en continu ;
- EC : ajout de nutriments A/B selon la même logique ;
- lumière : photopériode par culture + complément si la lumière naturelle est insuffisante (intégrale lumineuse journalière, DLI) ;
- humidité du sol : arrosage des emplacements en terre sous un seuil par culture, avec une durée max et un délai minimal entre deux arrosages ;
- présence : une présence la nuit ou hors des plages déclarées → **alerte intrusion** (humain ou animal) ; les présences en journée sont journalisées (visites, entretien) ;
- consignes par culture et par stade dans `edge/controller/recettes.yaml`.

### Niveau 2 — prévision par réseau de neurones (`forecast.py`)
- modèle **GRU** (puis Temporal Fusion Transformer si les données suffisent), entraîné sur l'historique TimescaleDB ;
- entrées : capteurs (fenêtre de 24 h, dont la tendance de pression du BMP280), état des actionneurs, météo extérieure (API), heure et saison, **sorties vision** (score de santé, surface verte) ;
- sorties : T°, HR, pH et EC à +1 h / +6 h ;
- usage : **anticipation** (ex. HR prévue > 85 % la nuit → ventilation préventive contre le mildiou) et **détection d'anomalie capteur** (écart entre mesure et prévision).
- Pré-requis : plusieurs semaines de données réelles. D'ici là, on entraîne sur le simulateur pour valider la mécanique.

### Niveau 3 — optimisation (plus tard)
- **MPC** s'appuyant sur le modèle appris (minimiser énergie + écart aux consignes) ;
- ou **RL** entraîné dans le simulateur, puis déployé en mode « conseil » avant toute action réelle.

### Indice de risque maladie
`risque = f(heures d'humectation foliaire estimées, T° moyenne, détections vision récentes)`.
On commence avec des règles agronomiques connues (ex. mildiou : HR > 90 % pendant plus de 10 h et 10–25 °C), puis on les apprend sur nos données.

## 5. Simulateur — `sim/`
Permet de développer le logiciel **avant** l'électronique :
- modèle thermique simple de la serre (1er ordre : T° intérieure en fonction de la T° extérieure, du rayonnement, de la ventilation et du chauffage) ;
- dynamique HR, pH et EC simplifiée ; bruit et pannes injectables (capteur figé, valeur aberrante, déconnexion) ;
- publie sur les **mêmes topics MQTT** que les ESP32 et réagit aux commandes, via `common.mqtt` (`sensor_topic`, `encode`, `decode`) ;
- sert aussi d'environnement d'entraînement pour le niveau 3.
