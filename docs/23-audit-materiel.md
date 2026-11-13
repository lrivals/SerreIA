# 23 — Audit du matériel à acheter

**But** : lister tout le matériel nécessaire pour passer de la serre simulée à la serre réelle
(calcul, nœuds, capteurs, actionneurs, arrosage, hydroponie, éclairage, énergie, structure),
dire ce qui est déjà acheté, ce qui manque, où l'acheter et dans quel ordre. Une section
chiffre l'intérêt de panneaux solaires ([§9](#9-énergie-et-panneaux-solaires)).

> Statut : **audit initial (13/11/2026)**. Les prix sont des **ordres de grandeur** (TTC,
> France, fin 2026) tirés de la connaissance générale des catalogues, **pas relevés en ligne** :
> les vérifier avant de commander (le Raspberry Pi 5 a notamment augmenté avec la mémoire).
> Des liens d'achat et des prix relevés chez les vendeurs sont rassemblés au
> [§15](#15-liens-dachat-et-premiers-prix-vérifiés-13112026).
> Les quantités suivent `edge/controller/serre.yaml` (z1 terre, z2 hydro NFT) et les
> puissances qui y sont déclarées.

## 0. Hypothèses à confirmer

| Hypothèse | Valeur retenue | Pourquoi elle compte |
|---|---|---|
| Taille de la serre | tunnel de jardin **2 à 6 m²**, deux zones (z1 terre, z2 hydro NFT) | nombre de lampes, puissance de chauffage, longueur du goutte-à-goutte |
| Emplacement | extérieur, jardin, à moins de 30 m de la maison | réseau Wi-Fi, câble secteur ou autonomie solaire |
| Électricité | une prise 230 V **disponible** à la serre (rallonge extérieure ou ligne enterrée) | décide si le solaire est un confort ou une nécessité ([§9](#9-énergie-et-panneaux-solaires)) |
| Usage hivernal | culture d'hiver (salades, aromatiques) avec complément LED, hors gel | c'est l'hiver qui dimensionne l'éclairage, le chauffage et l'énergie |
| Outils | imprimante Elegoo Centauri Carbon 2 et PC avec GPU déjà là | pièces de [20](20-impression-3d-structures.md) imprimées maison |

## 1. Synthèse

| Bloc | Déjà là | À acheter (phase A = première serre réelle) | Plus tard |
|---|---|---|---|
| Calcul et vision | — | Raspberry Pi 5 8 Go, alimentation, refroidisseur, SSD USB, 1 caméra | AI HAT+ (Hailo-8), 2ᵉ caméra |
| Nœuds | XIAO ESP32-C6 (à vérifier : 5 nécessaires) | cartes de raccordement, borniers, boîtiers | — |
| Capteurs air | SHT41, BMP280, GY-302, HLK-LD2450 | **SCD41** (CO₂) | capteur PAR, humectation foliaire |
| Capteurs sol | sondes capacitives | — | — |
| Capteurs hydro | — | — | EZO-pH, EZO-EC + isolateurs, DS18B20, JSN-SR04T, flotteur |
| Actionneurs | — | alim 12 V, MOSFET, pompe d'arrosage, ventilateur, Shelly | pompes doseuses, pompe NFT, brumisation |
| Climat passif | — | **ouvre-fenêtre thermique**, toile d'ombrage | — |
| Éclairage | — | — | 2 lampes LED ≈ 240 W, gradables |
| Chauffage | — | — | radiateur antigel + **thermostat de sécurité** + prise pilotée |
| Énergie | réseau | prise pilotée avec mesure (Shelly) | kit solaire « plug & play » si souhaité |

Budget indicatif : **phase A ≈ 500–700 €**, hydroponie ≈ 450–850 €, éclairage et chauffage
≈ 450–750 €, soit **≈ 1 400–2 300 €** hors structure de serre et hors solaire
([§13](#13-ordre-dachat-et-budget)).

## 2. Calcul, vision et réseau (Raspberry Pi)

| Article | Qté | Prix ≈ | Remarques |
|---|---|---|---|
| Raspberry Pi 5, **8 Go** | 1 | 95–130 € | choix de [05 §1](05-edge-deploiement.md#1-matériel) |
| Alimentation officielle 27 W USB-C | 1 | 13 € | indispensable avec HAT + SSD + caméras |
| Active Cooler officiel | 1 | 6 € | le Pi 5 ralentit sans refroidissement, plus encore en serre l'été |
| SSD USB 3 (256–512 Go) **ou** NVMe | 1 | 30–50 € | archives d'images ([05 §3](05-edge-deploiement.md#3-service-caméra--edgecamera_servicepy)) ; voir ⚠ PCIe ci-dessous |
| Carte microSD 32 Go (A2) | 1 | 10 € | démarrage ou secours |
| Camera Module 3 (standard ou *Wide*) | 1 puis 2 | 30–40 € | *Wide* (120°) pour voir un bac entier de près ; NoIR plus tard ([05](05-edge-deploiement.md)) |
| Nappe CSI Pi 5 (22→15 broches) 50 cm à 1 m | 1 par caméra | 3–6 € | **le Pi doit être à moins d'un mètre de chaque caméra CSI** |
| AI HAT+ 26 TOPS (Hailo-8) | 1 | 110–130 € | **reportable** : voir ci-dessous |
| Boîtier ventilé IP54/IP65 ou emplacement hors serre | 1 | 15–40 € | humidité et condensation : abri D3 de [20](20-impression-3d-structures.md) ou boîte de dérivation avec ventilateur filtré |
| Point d'accès Wi-Fi extérieur ou répéteur | 0–1 | 30–80 € | seulement si le Wi-Fi de la maison n'atteint pas la serre (tester avec un téléphone) |

Points d'attention :

- ⚠ **Le Pi 5 n'a qu'un lien PCIe.** L'AI HAT+ et un HAT NVMe le demandent tous les deux.
  Pour avoir les deux : SSD en **USB 3** (le plus simple), ou carte double M.2 avec
  commutateur PCIe (type HatDrive AI, Geekworm X1004), à vérifier compatible Hailo.
- **Le Hailo n'est pas nécessaire au débit** : une capture toutes les 10 min, c'est quelques
  inférences par heure. EfficientNet-B0 en ONNX sur le CPU du Pi 5 suffit pour démarrer (le
  service caméra tourne déjà en ONNX Runtime, [05 §7](05-edge-deploiement.md#7-implémentation-et-test-sur-pc)).
  Le Hailo devient utile pour YOLO + classifieur + PatchCore sur plusieurs caméras, et pour
  l'objectif « IA embarquée » du projet. On peut donc l'acheter en phase B.
  Rester sur **Hailo-8 / Hailo-8L** : la chaîne d'export ([05 §2](05-edge-deploiement.md#2-chaîne-dexport--visionexport))
  produit des HEF pour ces puces ; une carte à Hailo-10H demanderait une autre cible de compilation.
- **Caméra loin du Pi** : au-delà d'un mètre, une webcam USB (câble 3–5 m) ou un deuxième petit
  calculateur (Pi Zero 2 W + caméra, ≈ 40 €) qui envoie ses images au Pi 5.
- **Où mettre le Pi** : de préférence **hors de la serre** (abri, garage) si les caméras sont
  en USB, sinon dans un boîtier ventilé à l'ombre. 40 °C et 90 % HR sous un film plastique
  en été abîment l'électronique.

## 3. Nœuds ESP32 et électronique de puissance

Répartition de [06 §1.3](06-capteurs-controle.md#13-répartition-des-nœuds) et de `serre.yaml` :
esp32-01 (air z1), 02 (sol z1), 03 (solution z2), 04 (actionneurs), 05 (air z2).

| Article | Qté | Prix ≈ | Remarques |
|---|---|---|---|
| Seeed XIAO ESP32-C6 | 5 + 1 de rechange | 5–7 € pièce | vérifier le stock ; antenne externe U.FL (2–3 €) si la serre est loin du point d'accès |
| Alimentations 5 V USB-C (chargeurs de qualité) | 4–5 | 8 € pièce | ou une seule alim 12 V et des convertisseurs 12 → 5 V (buck, type MP1584 / LM2596, 2 € pièce) |
| Alimentation 12 V DIN ou boîtier, **Mean Well** (LRS-100-12 ou HDR-100-12) | 1 | 20–35 € | puissance : pompes, ventilateurs, pompes doseuses, électrovannes |
| Modules MOSFET logique 3,3 V (type D4184 / AOD4184, ou IRLZ44N) | 6–8 | 1–2 € pièce | pour toutes les charges **12 V CC** ; diode de roue libre sur moteurs et électrovannes ([06 §2](06-capteurs-controle.md#2-actionneurs)) |
| Prises ou modules pilotés **Shelly** (Plus Plug S, Plus 1PM, Pro 2PM DIN) | 2–4 | 20–35 € pièce | pour les charges **230 V** (LED, chauffage, brumisateur secteur) : certifiés, mesure de puissance, **MQTT natif** et temporisation d'extinction automatique. Plus sûr qu'un SSR bricolé |
| Convertisseur PWM → 0-10 V | 2 | 5–10 € pièce | gradation des drivers LED depuis l'ESP32 si les lampes n'ont pas d'entrée PWM |
| Plaques à pastilles / cartes porteuses, borniers à vis 5 mm, connecteurs JST ou GX12 | lot | 20–30 € | capteurs démontables sans soudure en serre |
| Boîtiers étanches + **presse-étoupes** PG7/PG9 | 5–6 | 5–10 € pièce | imprimés (D2, PETG/ASA + joint TPU) ou boîtiers de dérivation IP65 du commerce |
| Câble 4 conducteurs (I²C court < 1 m, sinon passer en UART/RS485), câble 2×1,5 mm² pour le 12 V | lot | 20–30 € | I²C ne supporte pas de longues distances : garder les capteurs I²C près de leur nœud |
| Gaine, serre-câbles inox ou UV, gaine thermo | lot | 10–15 € | |

Note logiciel : les Shelly publient sur leurs propres topics MQTT. Il faudra une petite
passerelle (ou un mode « shelly » du nœud actionneurs) qui traduit `serre/<zone>/cmd/<actionneur>`
vers le Shelly et republie `etat/`. Les sécurités locales du firmware ([06 §3](06-capteurs-controle.md#3-firmware-esp32--firmware-platformio-arduino-ou-esp-idf))
sont alors reprises par la temporisation automatique du Shelly.

## 4. Capteurs

### 4.1 Déjà achetés ([06 §1.2](06-capteurs-controle.md#12-capteurs-bom))

SHT41 (×2 prévus dans `serre.yaml` : z1 et z2 — vérifier qu'il y en a deux), BMP280, GY-302
(BH1750), HLK-LD2450, sondes d'humidité du sol capacitives.

### 4.2 À acheter

| Capteur | Qté | Prix ≈ | Phase | Remarques |
|---|---|---|---|---|
| Sensirion **SCD41** (CO₂) | 1 | 35–55 € | A | sur module Grove / Qwiic / Adafruit pour éviter de souder le boîtier |
| 2ᵉ SHT41 + BMP280 + GY-302 (nœud esp32-05) | 1 jeu | 15–25 € | B | si un seul jeu a été acheté |
| Abri ventilé (assiettes, pièce D1 imprimée) | 2 | filament | A | sans abri, le SHT41 mesure le soleil et pas l'air |
| **Atlas EZO-pH** + sonde pH de laboratoire | 1 | 150–200 € | B | référence de [06](06-capteurs-controle.md) ; sonde à changer tous les 12–18 mois |
| **Atlas EZO-EC** + sonde **K 1.0** | 1 | 200–250 € | B | |
| **Isolateurs** Atlas (*Basic EZO Inline Voltage Isolator*) | 2 | 35–45 € pièce | B | ⚠ obligatoires pH + EC dans la même cuve ([06 §1.2](06-capteurs-controle.md#12-capteurs-bom)) |
| *Alternative moins chère* : DFRobot Gravity pH V2 + EC K=1 + isolateur Gravity | 1 jeu | 100–150 € | B | sorties analogiques (ADC), moins précises et moins stables : acceptable pour apprendre, pas pour des consignes fines |
| DS18B20 étanche (gaine inox) + résistance 4,7 kΩ | 1–2 | 3–6 € | B | |
| JSN-SR04T (ultrason étanche) | 1 | 8–12 € | B | ≥ 25 cm au-dessus de l'eau (zone aveugle) |
| **Flotteur** de niveau bas (interrupteur à lame souple) | 1–2 | 3–5 € | B | sécurité « cuve vide » **câblée en dur** en plus de l'ultrason, qui peut se tromper (condensation) |
| Solutions d'étalonnage pH 4 / 7 / 10, EC 1 413 et 12 880 µS/cm, solution de conservation KCl | 1 lot | 30–50 € | B | étalonnage mensuel ([06 §1.2](06-capteurs-controle.md#12-capteurs-bom)) |

### 4.3 Recommandés hors BOM actuelle

| Capteur | Prix ≈ | Pourquoi |
|---|---|---|
| **Capteur PAR** (quantum) : Apogee SQ-500 (≈ 400 €) ou capteur RS485 générique (60–120 €) + transceiver MAX3485 (2 €) | 60–400 € | le lux est faux sous LED horticole ; le complément DLI ([06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc), `lux_vers_ppfd`) gagnerait en justesse. Option bon marché : capteur spectral **AS7341** (≈ 15 €) étalonné une fois contre un vrai PAR |
| **Débitmètre** à effet Hall (YF-S201 ou YF-B5) | 5–10 € | confirme que la pompe tourne réellement (`etat/`), détecte tuyau bouché ou pompe désamorcée |
| **Humectation foliaire** (capteur à peigne, ou LWS Meter ≈ 150 €) | 10–150 € | l'indice de risque mildiou estime l'humectation à partir de l'HR ; une mesure directe valide l'idée L6 de [22](22-idees-litterature.md) |
| T° / HR **extérieure** (SHT41 dans un abri, sur un nœud existant) | 10 € | l'API météo n'est pas encore branchée ([06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc)) ; une mesure locale sert au modèle thermique et au GRU |
| Mesure d'énergie : Shelly (déjà en §3) ou **INA219/INA226** sur le 12 V | 3–5 € | valide la consommation estimée par `backend/consumption` |

## 5. Arrosage de la zone terre (z1)

Choix de `serre.yaml` : `arrosage-z1`, pompe ≈ 20 W, 120 L/h, 45 s par arrosage.

| Article | Qté | Prix ≈ | Remarques |
|---|---|---|---|
| Récupérateur d'eau de pluie ou bidon 50–200 L | 1 | 20–60 € | réservoir d'arrosage ; couvercle opaque (algues) |
| Pompe **12 V CC** à membrane (type 12 V, 2–4 L/min, auto-amorçante) | 1 | 15–25 € | pilotable par MOSFET, compatible avec un futur système solaire |
| *Ou* électrovanne 12 V NF sur le réseau d'eau + réducteur de pression | 1 | 15–30 € | si un robinet est disponible ; prévoir un **filtre** |
| Kit goutte-à-goutte (tuyau 16 mm, capillaires 4/6 mm, goutteurs réglables ou autorégulants, bouchons) | 1 | 25–40 € | un goutteur ou plus par pot ; autorégulants si les pots sont à des hauteurs différentes |
| Filtre à tamis en ligne | 1 | 5 € | les goutteurs se bouchent sans filtre |
| Flotteur bas dans le réservoir | 1 | 4 € | la pompe ne doit jamais tourner à sec |

Fournisseurs : Gardena, Rain Bird, Claber, Hozelock en grande surface de bricolage
(Leroy Merlin, Castorama…) ou en ligne ; pompes 12 V sur Amazon / AliExpress.

## 6. Hydroponie NFT (z2)

Choix de `serre.yaml` : cuve 60 L, `pompe-nft-z2` 25 W, 300 L/h, 3 pompes doseuses 60 mL/min.

| Article | Qté | Prix ≈ | Remarques |
|---|---|---|---|
| Cuve opaque 60 L, alimentaire (bac de rangement noir ou réservoir) | 1 | 15–30 € | opaque contre les algues ; isolée (polystyrène) contre la chaleur l'été |
| Canaux NFT (kit 2–3 gouttières PVC 100 mm à trous) **ou** gouttières et embouts imprimés (A1/A2 de [20](20-impression-3d-structures.md)) | 1 | 50–120 € | pente 1–4 % (cales imprimées) |
| Pompe immergée 300–600 L/h (12 V CC, ou 230 V sur Shelly) | 1 | 15–35 € | |
| Tuyau 13 mm, raccords, vanne de réglage | lot | 10–15 € | |
| **Pompes péristaltiques 12 V** (Kamoer NKP, ou génériques) | 3 | 10–30 € pièce | pH−, nutriments A, nutriments B ; tube Pharmed/silicone résistant aux acides |
| Flacons de 1 L pour les solutions | 3 | 10 € | |
| Pompe à air + diffuseur | 1 | 10–20 € | oxygène de la solution (indispensable en DWC, utile en NFT pour la cuve) |
| Chauffe-eau d'aquarium 50–100 W | 1 | 15–25 € | hiver : solution > 15 °C ; été : au-dessus de 24 °C, risque de pourriture des racines → ombrer et isoler la cuve |
| Engrais hydroponiques A/B (ex. Terra Aquatica, marque française), pH− | 1 lot | 30–50 € | |
| Pots-filets, billes d'argile, cubes de laine de roche | lot | 20–30 € | |

Fournisseurs : growshops en ligne (Culture Indoor, Alchimia…), Amazon ; capteurs Atlas
chez Atlas Scientific (expédition depuis les États-Unis), RobotShop ou Mouser.

## 7. Climat : ventilation, brumisation, chauffage, ombrage

| Article | Qté | Prix ≈ | Remarques |
|---|---|---|---|
| **Ouvre-fenêtre automatique à vérin thermique** (sans électricité) | 1–2 | 30–50 € | sécurité passive : la serre s'aère même si tout le reste tombe en panne. Indispensable en tunnel l'été |
| Ventilateur d'extraction 12 V PWM 4 fils (120–140 mm, IP55+) ou extracteur de gaine 100–125 mm | 2 | 15–60 € | `ventilo-z1`, `ventilo-z2` (40 W prévus) ; une entrée d'air basse opposée |
| Toile d'ombrage 30–50 % | 1 | 20–40 € | l'été, c'est la première régulation de température |
| Brumisation : électrovanne 12 V + buses basse pression **ou** brumisateur ultrasonique | 1 | 30–60 € | `brumisateur-z1` ; eau filtrée (les buses se bouchent) ; suspendue en cas de présence ([06 §4](06-capteurs-controle.md#niveau-0--sécurité-safetypy)) |
| Radiateur soufflant **antigel** 1 500–2 000 W IP24, ou câble/tapis chauffant pour semis | 1 | 30–60 € | `chauffage-z1` ; tapis chauffant (20–50 W) bien plus sobre si seul le semis doit être au chaud |
| **Thermostat mécanique de sécurité** en série (coupure > 30 °C) | 1 | 15–25 € | défense en profondeur contre le risque « chauffage non borné sur sonde muette » de [17](17-analyse-systeme.md) |
| Prise pilotée Shelly (chauffage) | 1 | 20–30 € | voir §3 |

## 8. Éclairage LED

Choix de `serre.yaml` : `led-z1`, `led-z2`, 240 W chacune, PPFD max 450 µmol/m²/s.

| Article | Qté | Prix ≈ | Remarques |
|---|---|---|---|
| Lampe LED « quantum board » ou à barres, ≈ 240 W, efficacité **≥ 2,7 µmol/J**, spectre plein (blanc + rouge 660 nm), **gradable** | 2 | 150–300 € pièce | 240 W × 2,7 µmol/J ≈ 650 µmol/s, soit ≈ 450 µmol/m²/s sur 1,2–1,4 m². Marques courantes : Mars Hydro, Spider Farmer, ViparSpectra ; préférer un **driver Mean Well** (gradation 0-10 V / PWM) |
| Supports réglables en hauteur (C1 imprimé, tige M8 ou crémaillère) | 2 | filament + 10 € | **câble de sécurité** acier sous toute lampe suspendue ([20 §7](20-impression-3d-structures.md#7-sécurité)) |
| Prise Shelly ou relais 230 V + convertisseur PWM → 0-10 V | 2 | 25–40 € | allumage + intensité |

Quand en acheter : seulement si l'on cultive **en hiver**. D'avril à septembre la lumière
naturelle dépasse le DLI cible des salades (12–13 mol/m²/j, plafond de tipburn
`dli_max: 13` dans `recettes.yaml`) ; il faut alors plutôt ombrer. Les LED blanches aident
aussi la vision : capture sous lumière maîtrisée ([05 §3](05-edge-deploiement.md#3-service-caméra--edgecamera_servicepy)).

## 9. Énergie et panneaux solaires

### 9.1 Bilan de consommation (puissances de `serre.yaml`)

| Poste | Puissance | Usage typique | kWh/jour | Saison |
|---|---|---|---|---|
| Pi 5 + AI HAT + SSD + caméras | ≈ 8–12 W | 24 h | 0,25 | toute l'année |
| 5 nœuds ESP32 (Wi-Fi) | ≈ 0,5 W chacun | 24 h | 0,06 | toute l'année |
| Pompe NFT (cycles 15 min / 30 min) | 25 W | ≈ 12 h | 0,30 | saison de culture hydro |
| Arrosage, pompes doseuses | 20 W | quelques minutes | < 0,02 | |
| Ventilateurs (2 × 40 W) | 80 W | 2–6 h | 0,15–0,50 | surtout l'été |
| **Socle « électronique + eau + air »** | | | **≈ 0,8–1,1** | |
| LED (2 × 240 W) en complément d'hiver | 480 W | ≈ 4–6 h | **2–3** | novembre → février |
| Chauffage antigel (1 500 W) | 1 500 W | dépend du froid et de l'isolation | **3–15** | nuits froides |

Au tarif de `serre.yaml` (0,25 €/kWh) : socle ≈ 80–100 €/an ; LED ≈ 70–90 €/an (≈ 120 jours) ;
chauffage très variable, souvent le **premier poste** d'une serre en film simple.

### 9.2 Production solaire attendue (nord de la France, ordre de grandeur)

Un panneau de 1 kWc produit ≈ **0,7–1 kWh/jour en décembre-janvier** et ≈ **4,5–5 kWh/jour
en juin**, soit ≈ 1 000–1 200 kWh/an. La production est **minimale exactement quand les
lampes et le chauffage sont nécessaires**.

### 9.3 Verdict

| Usage | Pertinent ? | Raison |
|---|---|---|
| **Alimenter les lampes en hors-réseau** | ❌ **non** | 2,5 kWh/j en décembre demandent ≈ 3–4 kWc de panneaux + ≈ 5 kWh de batterie (plusieurs jours gris d'affilée), soit 4 000–7 000 € pour économiser ≈ 80 €/an. Les panneaux posés sur la serre lui feraient aussi de l'ombre |
| **Alimenter le chauffage** | ❌ non | puissance et saison incompatibles |
| **Socle (Pi, nœuds, pompes, ventilateurs) en hors-réseau** | ⚠️ seulement **si pas de 230 V à la serre** | l'été ≈ 300–400 Wc + batterie LiFePO4 12 V 100 Ah (1,3 kWh) suffisent ; pour passer décembre sans réseau, ≈ 800 Wc–1 kWc + 2,5 kWh de batterie (≈ 1 200–2 000 €), et pas de LED ni de chauffage |
| **Kit solaire « plug & play » raccordé à la maison** (400–800 Wc, micro-onduleur) | ✅ **oui, si l'objectif est de compenser** | 350–800 €, ≈ 450–900 kWh/an autoconsommés, amorti en ≈ 5–8 ans ; il compense **toute** la consommation annuelle de la serre hors chauffage, sans batterie. Déclaration à Enedis (convention d'autoconsommation sans injection, CACSI) |
| **Petite batterie tampon** pour le Pi et la sécurité (onduleur, ou LiFePO4 12 V 20–50 Ah avec chargeur) | ✅ **oui, même sur réseau** | coupure de courant : le Pi s'éteint proprement, les nœuds gardent leur mode dégradé. Un UPS HAT pour Pi (≈ 30–50 €) suffit pour le Pi seul |

Recommandation : **rester sur le réseau**, choisir des actionneurs **12 V CC** (pompes,
ventilateurs, électrovannes, pompes doseuses) pour pouvoir passer en solaire plus tard sans
racheter, mesurer la consommation réelle pendant un hiver (Shelly, INA219, `backend/consumption`),
puis décider. Si l'envie est de « verdir » la serre, un kit plug & play sur le toit ou le
jardin est le meilleur rapport coût / kWh. Pour réduire la facture, réduire d'abord le
chauffage (double paroi à bulles l'hiver, tapis chauffant pour les semis plutôt que chauffer
l'air, cultures d'hiver froides).

Fournisseurs solaires : kits plug & play (Beem, Sunology…) ; hors-réseau : régulateur MPPT
Victron, batteries LiFePO4, panneaux chez les revendeurs solaires ou en grande surface de
bricolage.

## 10. Structure et consommables

| Article | Prix ≈ | Remarques |
|---|---|---|
| Serre tunnel 2–6 m² (arceaux acier ou tube PVC 20 mm + film) | 100–500 € | bâche **traitée UV** 150–200 µm ; les raccords imprimés (B1, B2) remplacent les pièces cassées |
| Profilé alu 2020 ou tube carré (montants de lampe) | 20–40 € | C1 |
| Tige filetée M8 inox, écrous, visserie **inox A2/A4**, inserts laiton | 20–30 € | jamais de visserie zinguée en serre ([20 §2.2](20-impression-3d-structures.md#22-matériaux)) |
| Filament **ASA** (1–2 kg), **PETG** (1 kg), **TPU** 95A (0,5 kg) | 60–100 € | pas de PLA dans la serre |
| Mire grise / couleur (balance des blancs, px → cm²) | 10–30 € | D5 ; une carte de gris 18 % suffit au début |
| Pots, terreau, tuteurs, étiquettes | 30–60 € | étiquettes générées depuis `serre.yaml` ([20](20-impression-3d-structures.md)) |

## 11. Outillage et sécurité électrique

| Article | Prix ≈ | Remarques |
|---|---|---|
| Multimètre | 20–40 € | si absent |
| Fer à souder régulé, étain, tresse | 30–60 € | si absent |
| Pince à dénuder, pince à sertir (JST, Wago, cosses) | 20–40 € | |
| **Disjoncteur différentiel 30 mA** sur l'alimentation de la serre | 30–50 € (ou prise différentielle) | eau + 230 V : non négociable |
| Rallonge / câble extérieur H07RN-F, prises étanches IP44+ | 30–60 € | si le 230 V vient de la maison |
| Coffret électrique IP65 avec rail DIN | 25–50 € | alimentation 12 V, borniers, Shelly DIN |

Tout ce qui est en 230 V reste dans un coffret fermé ; en cas de doute, faire valider par
un électricien ([06 §2](06-capteurs-controle.md#2-actionneurs)).

## 12. Où acheter

| Catégorie | Fournisseurs (France / UE) |
|---|---|
| Raspberry Pi, caméras, AI HAT+ | revendeurs agréés : Kubii, Melopero, Pimoroni, The Pi Hut |
| XIAO ESP32-C6, modules Grove | Seeed Studio (direct), Mouser, DigiKey |
| Capteurs Sensirion / Bosch en module | Adafruit, SparkFun (via Kubii, Gotronic, Mouser), Seeed (Grove) |
| Atlas Scientific | Atlas Scientific (direct), RobotShop, Mouser |
| Alternative pH / EC | DFRobot (direct ou Gotronic) |
| Modules génériques (MOSFET, JSN-SR04T, DS18B20, convertisseurs) | Gotronic, Amazon, AliExpress (délais, qualité variable : en commander deux) |
| Alimentations Mean Well, borniers, coffrets | Gotronic, RS, Farnell, Conrad, Mouser |
| Shelly | Shelly (direct), Amazon, Domadoo |
| Arrosage, structure, visserie inox | Leroy Merlin, Castorama, Bricomarché, jardineries |
| Hydroponie, LED horticoles, engrais | growshops (Culture Indoor, Alchimia…), sites des marques LED, Amazon |
| Solaire | Beem, Sunology (plug & play) ; Victron et LiFePO4 chez les revendeurs solaires |

## 13. Ordre d'achat et budget

Aligné sur la feuille de route ([07](07-roadmap.md), étape S8 « serre réelle » : premiers
nœuds air et sol, caméra fixe, sécurités, 7 jours sans intervention).

| Phase | Contenu | Budget ≈ |
|---|---|---|
| **A — Première serre réelle (z1 terre)** | Pi 5 + alim + refroidissement + SSD + microSD ; 1 Camera Module 3 + nappe ; SCD41 ; cartes porteuses, borniers, boîtiers ; alim 12 V + MOSFET ; pompe 12 V + goutte-à-goutte + flotteur ; 1 ventilateur ; ouvre-fenêtre thermique ; toile d'ombrage ; différentiel ; 1 Shelly (mesure) | **500–700 €** |
| **B — Hydroponie (z2) et accélérateur** | Atlas EZO-pH/EC + isolateurs + sondes (ou DFRobot) ; DS18B20, JSN-SR04T, flotteur ; cuve, canaux NFT, pompe, 3 péristaltiques, pompe à air ; solutions d'étalonnage, engrais ; AI HAT+ ; 2ᵉ caméra ; 2ᵉ jeu de capteurs air | **650–1 100 €** (dont ≈ 120 € de Hailo) |
| **C — Hiver** | 2 lampes LED gradables + supports ; chauffage antigel ou tapis chauffant + thermostat de sécurité + Shelly ; chauffe-eau de cuve ; débitmètre ; PAR (AS7341 ou RS485) | **450–750 €** |
| **D — Optionnel** | kit solaire plug & play (350–800 €) ; UPS pour le Pi (30–50 €) ; humectation foliaire ; point d'accès extérieur | selon choix |

Avant de commander :
1. **Inventorier** ce qui est déjà là (nombre de XIAO, de SHT41, de sondes de sol) et le noter
   dans ce document.
2. **Fixer la taille de la serre** (elle dimensionne l'éclairage, le goutte-à-goutte et le
   chauffage), puis la saisir dans le configurateur ([21](21-configurateur-impression-3d.md)).
3. Vérifier qu'il y a du **Wi-Fi** et du **230 V** à l'emplacement de la serre (décide §2, §9).

## 14. Questions ouvertes

- Dimensions exactes de la serre, et emplacement (intérieur, véranda, jardin) ?
- 230 V disponible à la serre, à quelle distance de la maison ?
- Culture d'hiver visée, ou saison d'avril à octobre seulement ? (décide l'achat des LED et du chauffage)
- Eau : robinet à proximité ou récupération d'eau de pluie ?
- Atlas Scientific (précis, ≈ 500 €) ou DFRobot (≈ 150 €) pour pH/EC ?

---

## 15. Liens d'achat et premiers prix vérifiés (13/11/2026)

> Cette sélection complète les fournisseurs génériques du §12 avec des références consultables.
> Les prix sont ceux affichés lors de la recherche, TTC lorsqu'indiqué, hors livraison. Ils peuvent
> varier selon le stock, la variante et le vendeur. Un lien vers une famille de produits n'est pas
> une validation de compatibilité : vérifier la référence exacte avant commande.

### 15.1 Phase A — démarrage de la serre réelle

| Article du BOM | Référence / vendeur | Prix relevé | Lien | Commentaire |
|---|---|---:|---|---|
| Raspberry Pi 5 8 Go | MonRaspberry | 216 € affichés | https://monraspberry.com/produits/?product_brand=raspberry-pi&source_id=393&source_tax=product_brand | Prix élevé : comparer avec Kubii, Reichelt et RS avant achat. Ne pas acheter un kit complet si les accessoires ne sont pas nécessaires. |
| XIAO ESP32-C6 | Reichelt, version avec broches | 7,65 € | https://www.reichelt.com/fr/fr/shop/produit/xiao_esp32c6_wifi_6_bt5_0_zigbee_thread_avec_en-tete-406831 | Correspond à la carte déjà prévue dans le projet. Vérifier si les broches soudées sont utiles pour les cartes porteuses. |
| XIAO ESP32-C6 | DigiKey | 5,53 € TTC affichés | https://www.digikey.fr/fr/products/detail/seeed-technology-co-ltd/113991254/24613066 | Version sans broches ; délai fabricant indiqué de 4 semaines. |
| Capteur CO₂ SCD41 nu | DigiKey | 23,86 € affichés | https://www.digikey.fr/fr/products/detail/sensirion-ag/SCD41-D-R1/ | Composant nu : prévoir une carte/module de raccordement et vérifier le format exact. |
| Capteur CO₂ SCD41 | RS France | 43,50 € affichés | https://fr.rs-online.com/ | Rechercher « SCD41 » ; à privilégier si le produit proposé est bien un module prêt à câbler. |
| Prise extérieure avec mesure | Shelly Outdoor Plug S Gen3 | 31,90 € | https://www.shelly.com/fr/products/shelly-outdoor-plug-s-gen3 | IP44, mesure de puissance ; vérifier la charge admissible et l'exposition réelle aux intempéries. |
| Ouvre-fenêtre thermique | Leroy Merlin (vendeur marketplace) | 38,99 € | https://www.leroymerlin.fr/produits/ouvre-fenetre-automatique-pour-serre-ouverture-thermique-sans-electricite-double-ressort-charge-max-14-kg-71732256.html | Vérifier la géométrie de la fenêtre et la charge avant achat. |
| Serre tunnel 6 m² | France Serres | 259 à 299 € | https://www.france-serres.com/145-serres-tunnel-6m2 | Option de structure si aucune serre n'est déjà disponible. |
| Kit goutte-à-goutte 16 mm, 25 m | Leroy Merlin | Prix selon variante | https://www.leroymerlin.fr/produits/16mm-tuyau-goutte-a-goutte-2-0-l-h-33cm-kit-25m-marron-avec-accessoires-watermil-drip-irrigation-jardin-70056446.html | Goutteurs espacés de 33 cm, débit annoncé 2 L/h par goutteur ; vérifier que cet espacement convient aux pots/bacs. |

### 15.2 Phase B — hydroponie et mesure de la solution

| Article du BOM | Référence / vendeur | Prix relevé | Lien | Commentaire |
|---|---|---:|---|---|
| Circuit Atlas EZO-pH (carte seule) | RobotShop Europe | 50,59 € | https://eu.robotshop.com/fr/products/circuit-ph-ezo%E2%84%A2 | Sonde pH vendue séparément. Stock indiqué en réapprovisionnement lors de la recherche. |
| Circuit Atlas EZO-EC (carte seule) | RobotShop Europe | 74,79 € | https://eu.robotshop.com/fr/products/circuit-conductivite-ezo | Sonde EC vendue séparément. Stock indiqué en réapprovisionnement lors de la recherche. |
| Kit Atlas EC K=1.0 | RobotShop Europe | 252,99 € | https://eu.robotshop.com/fr/products/kit-capteur-conductivite-k-10-atlas-scientific | Kit incluant sonde, circuit et solutions d'étalonnage ; à comparer au coût de la carte seule + sonde. |
| Pompe péristaltique 12 V | Kamoer, via Leroy Merlin | 23,50 € | https://www.leroymerlin.fr/produits/pompe-peristaltique-kamoer-pour-aquarium-debit-reglable-de-5-2-a-90-mlmin-12-v-pompe-doseuse-pour-aquarium-diy-laboratoire-analyse-72595751.html | Débit annoncé 5,2 à 90 mL/min : compatible avec l'ordre de grandeur prévu (60 mL/min). Vérifier le matériau du tube avec les solutions acides et nutritives. |
| Sonde EC K=1.0 | Atlas Scientific / RobotShop | Voir kit ci-dessus | https://eu.robotshop.com/fr/products/kit-capteur-conductivite-k-10-atlas-scientific | Confirmer que la sonde fournie est bien K=1.0 et adaptée à la plage de conductivité de la solution nutritive. |

### 15.3 Phase C — éclairage et hiver

| Article du BOM | Référence / vendeur | Prix relevé | Lien | Commentaire |
|---|---|---:|---|---|
| Panneau horticole 240 W | PURELED Q240, GrowLED | Prix à vérifier sur la fiche | https://www.growled.fr/2917-pureled-q240-panneau-led-horticole-pour-croissance-et-floraison-8435405310263.html | Caractéristiques affichées : 240 W, 2,7 µmol/J, gradation 0–10 V, surface annoncée 0,8 × 0,8 à 1 × 1 m. Candidat cohérent avec le cahier des charges ; vérifier disponibilité et prix. |
| Kit solaire plug & play | Beem On Solo 500 W | 429 € | https://beemenergy.fr/collections/panneaux-solaires-plug-and-play-400w | Prix affiché ; précommande signalée. Ne pas dimensionner ce kit pour alimenter le chauffage ou les LED de la serre en autonomie. |
| Kit solaire plug & play | Beem On Duo 1 000 W | 858 € | https://beemenergy.fr/collections/panneaux-solaires-plug-and-play-400w | Option pour compenser une partie de la consommation du logement ; vérifier règles de raccordement et conditions Enedis. |

### 15.4 Références fournisseurs à garder sous la main

- Raspberry Pi et accessoires : https://www.kubii.com/ ; https://www.pimoroni.com/ ; https://www.reichelt.com/fr/fr/
- Cartes et composants électroniques : https://www.digikey.fr/ ; https://www.mouser.fr/ ; https://www.gotronic.fr/ ; https://www.rs-online.com/
- Capteurs et instrumentation : https://www.adafruit.com/ ; https://www.sparkfun.com/ ; https://eu.robotshop.com/fr/
- Domotique et prises pilotées : https://www.shelly.com/fr/
- Irrigation et structure : https://www.leroymerlin.fr/ ; https://www.france-serres.com/
- Éclairage horticole : https://www.growled.fr/
- Solaire : https://beemenergy.fr/

### 15.5 Points à corriger/valider avant de figer le panier

1. **Raspberry Pi 5 :** le prix relevé à 216 € pour la carte 8 Go seule est élevé. Comparer plusieurs revendeurs et ne retenir le prix qu'après vérification du stock.
2. **SCD41 :** distinguer le composant nu (moins cher, mais à intégrer) du module breakout prêt à raccorder. Le prix du composant seul ne doit pas être utilisé comme prix d'un module.
3. **Shelly :** le modèle extérieur IP44 est plus adapté à proximité de la serre qu'une prise intérieure, mais il doit rester protégé de la pluie directe et des projections.
4. **pH/EC :** les prix des circuits seuls n'incluent pas nécessairement les sondes, les isolateurs, les câbles ni les solutions d'étalonnage. Comparer le coût du système complet, pas celui de la carte seule.
5. **LED :** la référence Q240 correspond aux caractéristiques électriques et optiques visées dans le BOM ; confirmer que deux panneaux sont nécessaires après fixation des dimensions et de la surface cultivée.
6. **Solaire :** un kit plug & play raccordé au logement ne rend pas la serre autonome. L'autonomie hors réseau exige batterie, régulateur et dimensionnement saisonnier distincts.
7. **Sécurité 230 V :** les prises connectées ne remplacent ni les protections différentielles, ni un coffret adapté, ni une installation conforme. Faire valider le circuit extérieur par un électricien.
