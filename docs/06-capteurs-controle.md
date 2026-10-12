# 06 — Capteurs, électronique et contrôle

## 1. Capteurs (BOM indicative)

| Mesure | Capteur | Interface | Remarques |
|---|---|---|---|
| Température / humidité air | Sensirion **SHT45** | I²C | précis ; prévoir un abri ventilé contre le soleil direct |
| CO₂ | Sensirion **SCD41** | I²C | photoacoustique, mesure aussi T/HR |
| Lumière | **BH1750** (lux) ; plus tard un capteur PAR | I²C | le lux est mal adapté aux LED horticoles ; le PAR (µmol/m²/s) est préférable |
| pH solution | **Atlas Scientific EZO-pH** + sonde | I²C / UART | étalonnage 3 points mensuel |
| EC solution | **Atlas Scientific EZO-EC** + sonde K1.0 | I²C / UART | |
| T° eau | **DS18B20** étanche | 1-Wire | compensation de température pour le pH et l'EC |
| Niveau cuve | flotteur ou ultrason **JSN-SR04T** | GPIO | sécurité « cuve vide » pour les pompes |
| Humidité substrat (optionnel) | capacitif v2 | ADC | jamais résistif (corrosion) |

⚠️ **Isolation galvanique obligatoire** entre les sondes pH et EC plongées dans la même cuve (cartes d'isolation Atlas, ou alimentations isolées). Sans elle, les mesures se perturbent mutuellement.

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

Un nœud = un rôle (ex. `esp32-01` air, `esp32-02` solution, `esp32-03` actionneurs).
- lecture des capteurs toutes les 30 s → publication sur `serre/<zone>/capteur/<type>` ;
- validation locale (plage physique → `qualite: erreur`) ;
- abonnement à `serre/<zone>/cmd/#` → exécution → publication de l'état (retain) ;
- **sécurités locales indépendantes du Pi** :
  - toute commande de pompe sans `duree_s`, ou au-delà d'une durée max, est refusée ou coupée ;
  - cuve vide → pompes interdites ;
  - perte MQTT supérieure à 2 min → **mode dégradé** (programme horaire minimal pour l'arrosage et la ventilation) ;
- LWT `serre/<noeud>/status = offline` ; watchdog ; mises à jour OTA.

## 4. Stratégie de contrôle — `edge/controller/`

Le « réseau de neurones » de pilotage s'introduit **progressivement**, sans jamais remplacer les sécurités.

### Niveau 0 — sécurité (`safety.py`)
Limites dures, toujours actives : T° max et min, durée max des pompes, cuve vide, pH hors [4,5 ; 8], absence de mesure depuis plus de 5 min → alerte.

### Niveau 1 — règles et régulateurs (`rules.py`)
- température et humidité : hystérésis → ventilation, brumisation, chauffage ;
- pH : dosage par impulsions (dose, attente du mélange, re-mesure), jamais en continu ;
- EC : ajout de nutriments A/B selon la même logique ;
- lumière : photopériode par culture + complément si la lumière naturelle est insuffisante (intégrale lumineuse journalière, DLI) ;
- consignes par culture et par stade dans `edge/controller/recettes.yaml`.

### Niveau 2 — prévision par réseau de neurones (`forecast.py`)
- modèle **GRU** (puis Temporal Fusion Transformer si les données suffisent), entraîné sur l'historique TimescaleDB ;
- entrées : capteurs (fenêtre de 24 h), état des actionneurs, météo extérieure (API), heure et saison, **sorties vision** (score de santé, surface verte) ;
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
- publie sur les **mêmes topics MQTT** que les ESP32 et réagit aux commandes ;
- sert aussi d'environnement d'entraînement pour le niveau 3.
