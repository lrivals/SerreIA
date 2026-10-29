# 20 — Structures imprimées en 3D pour la serre

**But** : répertorier les pièces imprimables qui servent à construire et équiper la serre
physique (hydroponie, structure et bâche, éclairage réglable, supports d'électronique, culture),
avec des modèles existants, les cotes à personnaliser et le matériau à utiliser. La taille de la
serre n'est pas encore fixée : chaque famille de pièces indique à quelle échelle elle sert
([§3](#3-échelles-de-serre)).

> Statut : **pièces P0, P1 (dont D8 et les variantes de lampe C1) et étiquettes rendues par FreeCAD
> ([hardware/](../hardware/README.md), [§5.3](#53-sources--hardware)) avec les cotes nominales ;
> rien n'est mesuré ni imprimé**. Les cotes et les règles de ce document
> sont codées dans [hardware/params.py](../hardware/params.py) (valeurs nominales, remplacées
> par les cotes mesurées de [hardware/mesures.toml](../hardware/mesures.toml)) et testées par
> `tests/test_hardware.py`. Choix des pièces selon la serre et saisie des cotes dans
> l'interface : configurateur [21](21-configurateur-impression-3d.md). Les liens renvoient à des modèles tiers trouvés en octobre 2026 :
> vérifier la licence (souvent CC BY-NC, usage non commercial), les cotes et le matériau
> conseillé avant d'imprimer.

## 1. Principes

- **Le tube porte, l'imprimé raccorde.** La portée vient de pièces achetées (tube PVC, PE ou
  acier/EMT, profilé alu, tasseau, tige filetée, câble). L'impression fournit les raccords,
  clips, supports et adaptateurs **à la cote exacte** du matériel acheté. Une pièce imprimée ne
  doit jamais être le seul élément qui porte une charge suspendue (voir [§7](#7-sécurité)).
- **Mesurer, puis paramétrer.** Les modèles paramétriques (OpenSCAD, Customizer MakerWorld)
  sont préférés aux STL figés : on règle le diamètre du tube, l'épaisseur de la bâche, le
  diamètre du net-pot ([§5](#5-personnalisation-paramétrique)).
- **Imprimer une éprouvette d'abord.** Pour tout ajustement serré (clip sur tube, filetage,
  baïonnette, joint TPU), imprimer un anneau ou un tronçon de 5 mm avant la pièce complète.
- **Pas de PLA dans la serre** ([§2.2](#22-matériaux)).

## 2. Imprimante et matériaux

### 2.1 Elegoo Centauri Carbon 2

| Caractéristique | Valeur | Conséquence |
|---|---|---|
| Volume | 256 × 256 × 256 mm | pièces > 25 cm découpées et assemblées (tenons, vis, baïonnette) |
| Buse | acier trempé, jusqu'à 350 °C | fibres de carbone (PETG-CF, ASA-CF) sans usure de buse |
| Plateau | jusqu'à 110 °C | ASA / ABS imprimables |
| Caisson | fermé | limite le warping de l'ASA/ABS ; ventiler la pièce (styrène) |
| Multicouleur | combo CANVAS (option) | étiquettes lisibles, repères de couleur (cotes, zones) |

Sources : [3DJake](https://www.3djake.com/elegoo/centauri-carbon-2),
[Tom's Hardware](https://www.tomshardware.com/3d-printing/elegoo-centauri-carbon-2-review).

### 2.2 Matériaux

Sous une bâche en plein soleil, l'air dépasse facilement 45–50 °C et une pièce sombre exposée
bien davantage. Les UV, l'humidité permanente et la solution nutritive (pH 5,5–6,5) s'ajoutent.

| Matériau | Tenue T° | UV | Eau / solution | Usage dans la serre |
|---|---|---|---|---|
| **PLA** | ~55 °C, fluage avant | faible | se dégrade | **exclu** (sauf gabarits de mesure, éprouvettes) |
| **PETG** | ~75 °C | moyen | bon | défaut pour l'humide et l'ombragé : hydroponie, supports de sondes, boîtiers intérieurs |
| **ASA** | ~95 °C | **très bon** | bon | tout ce qui voit le soleil : raccords de structure, clips de bâche, abri capteur, ouvrants |
| **ABS** | ~95 °C | faible (jaunit, casse) | bon | pièces chaudes à l'abri des UV (près des drivers LED) ; préférer l'ASA |
| **PETG-CF / ASA-CF** | idem base | idem base | bon | pièces rigides : coulisseaux de lampe, bras, équerres |
| **TPU 95A** | ~60 °C | moyen | bon | joints de boîtiers, patins anti-frottement bâche, colliers souples |

Contact avec la solution nutritive et les racines : PETG ou ASA, jamais de pièce poreuse
(remplissage < 100 % exposé) où les algues et biofilms s'installent. Les pièces en contact avec
l'eau sont **opaques** (une pièce translucide fait pousser les algues).

### 2.3 Réglages type

| Usage | Parois | Remplissage | Remarque |
|---|---|---|---|
| Raccord de structure, clip de bâche | 4–6 | 40–60 % gyroïde | couches perpendiculaires à l'effort principal (un clip qui s'ouvre casse entre deux couches) |
| Pièce étanche (cuve, canal, boîtier) | 4+ | 100 % ou parois épaisses | ou enduit époxy alimentaire à l'intérieur |
| Support de sonde, étiquette | 3 | 20 % | |
| Pièce qui reçoit une vis | 4 + **inserts laiton** posés à chaud | | vis **inox** (A2/A4), jamais zinguée en serre |

## 3. Échelles de serre

| Famille | Petite intérieure (< 1 m², étagère/tente) | Tunnel jardin (1–6 m²) | Grande (> 6 m²) |
|---|---|---|---|
| A. Hydroponie (tour, NFT, DWC) | ✅ tour de table, DWC bocal | ✅ tours, NFT 2–3 canaux | ✅ accessoires seulement (embouts, supports) |
| B. Structure et bâche | ⚪ cadre en tube 16–20 mm, tout en raccords imprimés | ✅ raccords d'arceaux, clips de bâche, porte | ⚪ clips et accessoires ; la structure est achetée |
| C. Éclairage réglable | ✅ cœur du besoin | ✅ rampes au-dessus des bacs | ✅ supports et coulisseaux |
| D. Électronique et capteurs | ✅ | ✅ | ✅ |
| E. Culture (tuteurs, semis, étiquettes) | ✅ | ✅ | ✅ |

✅ pertinent · ⚪ partiel.

## 4. Catalogue par besoin

Chaque fiche donne le problème, les modèles trouvés, les cotes à personnaliser, le matériau et
le lien avec le modèle logiciel de la serre ([09](09-modele-gestion-serre.md)).

### A. Hydroponie

#### A1 — Tour hydroponique verticale
- **Problème** : cultiver salades et aromatiques sur une faible emprise au sol.
- **Modèles** :

  | Modèle | Site | Notes |
  |---|---|---|
  | [Tour Hydroponique – Tour de Culture](https://www.crealitycloud.com/fr/model-detail/hydro-tower-growing-tower?source=8&profileId=69260fadfcc65ef5eda0d705) (Roland Goller) | Creality Cloud | 5 plateaux, ~539 g, ~14 h (0,2 mm, 2 parois, 15 %) ; licence CC BY-NC-SA 4.0 ; pompe et net-pots non décrits |
  | [Modular Hydroponic Tower](https://www.printables.com/model/720081-modular-hydroponic-tower) | Printables | remix ebb & flow, ~553 g, liste de pièces fournie |
  | [Modular Hydroponic Tower – Vertical Growing System](https://makerworld.com/en/models/2415282-modular-hydroponic-tower-vertical-growing-system) | MakerWorld | modules empilables, pompe immergée réservoir → sommet |
  | [Modular Hydroponic Tower](https://makerworld.com/en/models/1382834-modular-hydroponic-tower) | MakerWorld | modules indépendants, 3 trous inclinés, baïonnette |
  | [Tower Hydroponic System Part 1](https://makerworld.com/en/models/1526699-tower-hydroponic-system-part-1) | MakerWorld / Thingiverse 7068243 | système en plusieurs parties |
  | [Threaded Bucket Lid Adapter](https://www.printables.com/model/582197-modular-hydroponics-tower-threaded-bucket-lid-adap) / [Bucket Lid sans colle](https://www.printables.com/model/1325249-modular-hydroponic-tower-bucket-lid-with-no-glue-o) | Printables | poser une tour sur un seau de 20 L (réservoir) |

- **À personnaliser** : nombre d'étages (hauteur sous lampe), diamètre des net-pots, filetage
  ou baïonnette entre modules, diamètre du tube d'arrivée (pompe).
- **Matériau** : PETG ou ASA **opaque** (blanc ou noir, pas translucide) ; 4 parois minimum sur
  les cuvettes pour l'étanchéité.
- **Logiciel** : une tour = une zone `hydro_nft` (circulation cyclique) ou `ebb_flow`, avec sa
  cuve ([09 §3](09-modele-gestion-serre.md#3-contenant-et-mode-de-culture)) ; chaque trou est un
  emplacement (`z2-T1`…). Prévoir dans le couvercle du réservoir le passage des sondes
  ([A4](#a4--couvercle-de-cuve-et-supports-de-sondes)).

#### A2 — NFT : embouts de canaux, net-pots, adaptateurs
- **Problème** : les canaux NFT (tube PVC 75–110 mm ou profilé rectangulaire) ont besoin
  d'embouts avec arrivée et sortie, et les trous doivent recevoir des net-pots de la bonne taille.
- **Modèles** :
  - [Parametric Net Pot Remix with Closed Bottom](https://www.printables.com/model/50326-parametric-net-pot-remix-with-closed-bottom) (OpenSCAD) ;
  - [2" Net Pot Adapter to 2.5" hole](https://www.printables.com/model/1197209-2-net-pot-adapter-to-25-hole) (bague de réduction) ;
  - [2x3 Channel Cap](https://www.makerworld.com/en/models/1416620) (MakerWorld, embout pour profilé) ;
  - [Parametric Pipe Adapter (OpenSCAD)](https://www.printables.com/model/132932-parametric-pipe-adapter-openscad) (réductions de tuyau).
- **À personnaliser** : section du canal (Ø ou L × H), Ø intérieur de l'embout de sortie
  (tuyau de retour, souvent 16 ou 20 mm), pente (cale imprimée sous le canal : 1–4 %),
  Ø des net-pots (50 ou 75 mm).
- **Matériau** : PETG ; joint TPU ou silicone alimentaire entre embout et canal.
- **Logiciel** : `contenant.type: canal_NFT`, un emplacement par trou (`z2-G1…G12`).

#### A3 — DWC : couvercles et bocaux
- **Modèles** : [6-pod 2" net cup pour couvercle de seau](https://www.printables.com/model/1186373-modified-6pod-2inch-net-cup-hydroponic-modular-tow),
  [5-gallon modular bucket lid](https://www.makerworld.com/en/models/1443063) (Kratky, mèche, DWC ; 3 ou 6 sites).
- **À personnaliser** : Ø du seau ou du bac, nombre de sites, passage du tuyau du bulleur et
  d'une sonde.
- **Logiciel** : `contenant.type: bac_DWC`, mode `hydro_dwc` (le bulleur est un actionneur).

#### A4 — Couvercle de cuve et supports de sondes
- **Problème** : les sondes de [06 §1.2](06-capteurs-controle.md#12-capteurs-bom) doivent rester à
  profondeur fixe : pH et EC immergées sans toucher le fond, DS18B20 près d'elles (compensation
  de température), JSN-SR04T **au-dessus** de l'eau, perpendiculaire à la surface, à plus de
  25 cm de la surface (zone aveugle du capteur). Les sondes pH/EC doivent être écartées l'une de
  l'autre (perturbations, en plus de l'isolation galvanique).
- **Pièce à concevoir** (pas de modèle unique trouvé) : couvercle de cuve sur mesure ou platine
  vissée dessus, avec presse-étoupes imprimés pour sondes Ø 12 mm (pH/EC) et Ø 6 mm (DS18B20),
  porte-capteur JSN-SR04T, trappe de remplissage, passage des tuyaux de pompes doseuses.
- **Matériau** : PETG opaque ; joints TPU.
- **Logiciel** : capteurs `cuve: true` de la zone ([09 §4](09-modele-gestion-serre.md#4-équipements)).

### B. Structure et bâche

#### B1 — Raccords de tubes (arceaux, cadre, faîtage)
- **Problème** : relier des tubes du commerce sous des angles qui n'existent pas en raccord
  standard (arceau, toit à deux pentes, pieds).
- **Modèles** :
  - [Parametric dowel and tube joiners](https://makerworld.com/models/2933746) (OpenSCAD, 2 à 6 voies, diamètres, longueurs et **angles** réglables, pensé pour des serres légères) ;
  - [Universal Modular Pipe Connector](https://makerworld.com/en/models/2662089-universal-modular-pipe-connector) (Ø 5–50 mm, 5 modes) ;
  - [Parametric n-way pipe fitting](https://www.printables.com/model/638480-parametric-n-way-0-6-way-pipe-fitting) (0 à 6 voies) ;
  - [PVC pipe connectors](https://www.printables.com/model/138222-pvc-pipe-connectors) (5 sommets de cadre de serre, OpenSCAD) ;
  - [Pipe connector for small DIY Greenhouse hoop](https://www.printables.com/model/1011234-pipe-connector-for-small-diy-greenhouse-hoop) (arceau PE 20 mm sur tube de base 21,5 mm) ;
  - [DIY GREENHOUSE by KMS](https://www.printables.com/model/62627-diy-greenhouse-by-kms) (serre bois + pièces imprimées complète, avec ouvrant de toit).
- **À personnaliser** : Ø extérieur réel du tube (mesuré au pied à coulisse, ± 0,3 mm de jeu),
  angle de chaque branche, longueur d'emmanchement (≥ 1,5 × Ø), trou de vis traversante.
- **Matériau** : ASA (ou ASA-CF pour les nœuds chargés) ; 5–6 parois.
- **Ancrage au sol** : pieds imprimés recevant un piquet ou une tige filetée ; c'est le piquet
  qui tient au vent, pas la pièce.

#### B2 — Tension et fixation de la bâche
- **Problème** : tendre le film PE sur les arceaux sans le percer, et pouvoir le retirer.
- **Modèles** :
  - [Greenhouse plastic clamp](https://www.printables.com/model/154773-greenhouse-plastic-clamp) (≈ 100 clips sur film 150 µm, + collier rilsan) ;
  - [C-Clips for PEHD pipe DN16/20/25/32](https://www.printables.com/model/1555068-c-clips-for-pehd-flexible-pipe-dn16202532) ;
  - [Greenhouse Parts Collection](https://3dgo.app/models/printables/1689349) (lot de pièces, conseille le PETG plutôt que le PLA).
- **À personnaliser** : Ø du tube + 2 × épaisseur du film (film 150–200 µm), angle
  d'ouverture du C (≈ 200–220° d'enveloppement), largeur du clip (40–60 mm), fente pour
  collier. Prévoir un espacement d'environ 50–60 cm, plus serré aux angles.
- **Matériau** : ASA ; arêtes arrondies (rayon ≥ 1 mm) pour ne pas entailler le film.
- **Ce qu'on n'imprime pas** : le système profilé + fil zigzag (« wiggle wire ») reste en
  aluminium et acier ; un profilé imprimé serait le point faible au vent. On imprime seulement
  des **embouts** et des **patins TPU** entre tube et film (le frottement use la bâche).
- **Tension** : tendeurs imprimés (came ou cliquet) sur sangle aux pignons, plutôt que tirer
  sur le film.

#### B3 — Porte, ouvrants et aération
- **Problème** : la ventilation (`ventilo`) ne suffit pas toujours ; un ouvrant passif évite la
  surchauffe en cas de panne.
- **Pièces** : charnières et loquets de porte sur cadre tube, cadre d'ouvrant de toit (voir
  KMS ci-dessus), grilles anti-insectes encliquetables sur les entrées d'air (maille à acheter,
  cadre imprimé), déflecteur pour le ventilateur.
- **Vérin** : un ouvre-fenêtre à cire du commerce (sans électricité) est plus fiable qu'un
  mécanisme imprimé ; imprimer seulement les **supports** adaptés au tube de la serre.
- **Logiciel** : un ouvrant motorisé deviendrait un actionneur de la zone ; un ouvrant à cire
  n'est pas piloté mais influe sur la T° (à noter dans la description de la zone).

#### B4 — Gouttières de condensation
- **Problème** : la condensation ruisselle sur les plantes et l'électronique (favorise le
  mildiou, surveillé par la règle de [06](06-capteurs-controle.md)).
- **Pièces** : profils en L clipsés sous le faîtage ou en bas de pente, déflecteurs au-dessus
  des boîtiers et des caméras. À dessiner (pas de modèle générique trouvé) : section en L,
  pince sur tube au Ø de la structure.

### C. Éclairage réglable en hauteur

La lampe doit suivre la croissance : trop haute, le PPFD chute (inverse du carré de la
distance environ) ; trop basse, elle brûle les apex. La cible de PPFD vient de la recette
([09 §6](09-modele-gestion-serre.md#6-recettes-de-culture)).

#### C1 — Supports et coulisseaux
- **Modèles** :
  - [Plant box LED holder (adjustable)](https://www.printables.com/model/58670-plant-box-led-holder-adjustable) (segments empilables, fentes pour profilé alu LED, clip sur bac) ;
  - [Barrina T8 Plant Grow Light Stand](https://www.printables.com/model/773928-barrina-t8-plant-grow-light-stand) (support de tubes T8 réglable) ;
  - [LED support](https://makerworld.com/en/models/1741488-led-support) (réglage rapide de la hauteur) ;
  - [Adjustable grow light stand](https://makerworld.com/it/models/2544911-adjustable-grow-light-stand).
- **Variantes conçues** (dans [hardware/pieces/](../hardware/README.md)) :
  - **coulisseau sur montant** (profilé 2020 ou tube carré) avec vis M5 à molette et écrou
    captif : simple et rigide, pour étagère ou tente — `coulisseau.py` ;
  - **tige filetée M8** (une tige par coin, suspendue au tube par `fixation_tige`) : l'équerre
    de la lampe repose sur une molette à écrou M8 captif, une seconde molette bloque ;
    réglage au millimètre (1,25 mm par tour), lampe horizontale à nombre de tours égal —
    `support_tige.py` ;
  - **crémaillère à crans** : barre vissée au montant, fentes tous les `cran_pas`
    (20–50 mm, 25 par défaut), crochet qui s'accroche par gravité, réglage sans outil —
    `cremaillere.py`.
- **À personnaliser** : section du montant, entraxe et section de la rampe LED (profilé alu,
  barre, panneau), hauteur max, pas des crans.
- **Matériau** : PETG-CF ou ASA-CF (rigidité) ; **ASA ou ABS** à moins de 5 cm du driver ou
  du dissipateur.

#### C2 — Suspension à cliquet
- Les suspensions à cliquet (« ratchet hanger », corde 3 mm) se vendent quelques euros et sont
  certifiées pour la charge : **les acheter**. Imprimer seulement les crochets d'accroche au
  Ø du tube de faîtage et les palonniers qui répartissent sur deux points.

#### C3 — Hauteur motorisée (évolution)
- **Idée** : un moteur pas-à-pas (NEMA 17) entraîne une vis trapézoïdale T8 ou un enrouleur de
  câble ; poulies, supports moteur et guides imprimés ; fins de course en haut et en bas.
- **Lien avec le logiciel** : nouvel actionneur `led_hauteur` (consigne en cm) piloté par le
  nœud actionneurs `esp32-04`. La consigne vient de la **hauteur de plante** mesurée par la
  caméra latérale ([04 §5](04-detection-yolo.md#5-suivi-de-croissance)) + une distance cible
  par recette. Durée max et fins de course gérées par le firmware, comme les pompes.
- **Prérequis** : C1 manuel validé ; câble de sécurité indépendant du mécanisme ([§7](#7-sécurité)).

### D. Électronique et capteurs

Ces pièces conditionnent la **justesse des mesures** : un SHT41 au soleil direct ou une caméra
qui bouge faussent les données et la vision.

| Pièce | Problème | Modèles / piste | À personnaliser | Matériau |
|---|---|---|---|---|
| **D1 — Abri ventilé (écran de Stevenson)** pour SHT41, BMP280, SCD41 | le soleil direct ajoute plusieurs °C à la mesure ([06 §1.2](06-capteurs-controle.md#12-capteurs-bom)) | [Solar Radiation Shield](https://www.printables.com/model/235525-solar-radiation-shield) ; [design paramétrique Fusion 360 + ESP32](https://hiltsu.codeberg.page/en/posts/stevenson-shield-esp32-lorawan/) ; [comparatif d'abris imprimés](https://hackaday.com/2022/02/04/3d-printed-radiation-shields-get-put-to-the-test) | nombre d'assiettes, Ø intérieur (carte capteur + XIAO), fixation sur tube | **ASA blanc** (le PLA ne tient pas ; le filament laisse passer l'infrarouge : parois épaisses) |
| **D2 — Boîtiers des nœuds XIAO ESP32-C6** | humidité, condensation, poussière | [boîtier XIAO à couvercle coulissant + antenne](https://www.makerworld.com/en/models/2145189) ; [boîtier paramétrique XIAO + capteurs](https://makerworld.com/models/1646669) ; boîtier étanche générique : [Parameterized Rugged Box (TPU)](https://www.printables.com/model/793850-parameterized-rugged-box-openscad-with-tpu-gasket), [IP65 paramétrique](https://printables.com/model/72839-customizable-parametric-stable-and-waterproof-elec), [Super Customizable Rugged Box](https://www.printables.com/model/1073708-super-customizable-rugged-box-in-openscad) | dimensions carte + borniers, presse-étoupes, sortie antenne U.FL, trou d'évent bas (évacuer la condensation) | PETG ou ASA + joint TPU |
| **D3 — Support radar HLK-LD2450** | orientation fixe et connue de la zone suivie | [boîtier orientable LD2450 + ESP32](https://www.printables.com/model/1514952-mmwave-sensor-ld2450-d1-mini-esp32) ; [boîtier magnétique](https://printables.com/model/962312-esp32-ld2450-case) ; [rotule murale](https://makerworld.com/models/2106350) | angle de site/azimut, carte voisine (XIAO au lieu de D1 mini) ; **pas de métal ni de face épaisse devant l'antenne** | PETG / ASA |
| **D4 — Supports caméra à angle fixe** | la vision suppose un cadrage stable (régions par emplacement, [09 §4](09-modele-gestion-serre.md#4-équipements)) | [support articulé Camera Module 3](https://3dgo.app/models/printables/368788) ; [support pour profilé](https://www.printables.com/model/573073-raspberry-pi-camera-module-mount-for-extrusions) | rotule **verrouillable** (vis + repère gradué), pince au Ø du tube, visière anti-condensation, fenêtre en verre/PMMA | ASA |
| **D5 — Support de mire** (gris neutre / couleurs) | balance des blancs fixe dans le champ ([05 §3](05-edge-deploiement.md#3-service-caméra--edgecamera_servicepy)) et conversion px → cm² ([04 §5](04-detection-yolo.md#5-suivi-de-croissance)) | à concevoir | taille de la carte, distance et angle par rapport à la caméra, repères d'échelle imprimés | ASA mat |
| **D6 — Boîtier Pi 5 + Hailo** | chaleur sous bâche, poussière | [Pi 5 AI Case (snap, AI HAT)](https://test.3dsearch.net/model/pi-5-ai-case-mw1876242) ; [boîtier modulaire Pi 5](https://makerworld.com/models/1020178) | hauteur de la pile HAT, ventilateur 40 mm, filtre à poussière ; placer le Pi **hors** de la serre si possible | ASA |
| **D7 — Supports pompes et ventilateurs** | vibrations, débordements | à concevoir : berceau de pompe péristaltique avec bac de rétention, carénage de ventilateur 120 mm, bride de tuyau | entraxes de fixation, Ø tuyaux | PETG |
| **D8 — Goulottes et passe-câbles** | câbles au sol mouillé, traction sur connecteurs | [hardware/pieces/cables.py](../hardware/pieces/cables.py) : clip de câbles sur tube (3 berceaux), passe-paroi à circlip avec joint plat et bague TPU | Ø tube, nombre de câbles | ASA / TPU |

### E. Culture

| Pièce | Modèles | À personnaliser | Matériau |
|---|---|---|---|
| Clips de tuteur / palissage | [Adaptable Plant Clip (tomate, tuteur 6–16 mm)](https://printables.com/model/221320-adaptable-plant-clip-tomato-clip/comments) ; [Plant clip for climbing plants](https://www.printables.com/model/1210771-plant-clip-for-climbing-plants) ; [Garden string clip](https://www.printables.com/model/232374-garden-string-clip) | Ø du tuteur ou de la ficelle, Ø de tige | PETG / TPU (souple, ne blesse pas la tige) |
| Supports de semis | [Seedling support with auto-clip](https://www.printables.com/model/64716-seedling-support-with-auto-clip-no-wires-needed) | longueur, largeur | PETG |
| Goutte-à-goutte (zone terre) | [porte-tubes 1/2" et 3/16"](https://www.printables.com/model/461502-12-and-316-drip-irrigation-holders-for-drip-hoses) ; [porte-tube Gardena 4,6 mm](https://3dgo.app/models/printables/490508) ; [support de câble pour arrosage automatique](https://www.printables.com/model/152059-cable-holder-for-plant-water-automation) | Ø du tube (4 / 4,6 / 6 mm), longueur du piquet | PETG / ASA ; **ne pas imprimer les raccords sous pression** (fuites signalées en PETG) |
| Étiquettes d'emplacement | [hardware/pieces/etiquette.py](../hardware/pieces/etiquette.py), générées depuis `serre.yaml` : code `z1-A1` en relief bicolore (CANVAS) + QR (id de l'emplacement, plus tard la fiche dans l'interface [12](12-interface-utilisateur.md)) | texte, taille, piquet ou clip | ASA |
| Plateaux de semis, dômes | générateur de bac paramétrique (OpenSCAD) | nombre d'alvéoles, profondeur, drainage | PETG |
| Cales de pente et pieds de bacs | à concevoir | pente (NFT 1–4 %), hauteur, surface d'appui | ASA |

## 5. Personnalisation paramétrique

### 5.1 Outils

| Outil | Usage |
|---|---|
| **FreeCAD scripté** (`Part`, sans interface via `freecadcmd`) | **toutes nos pièces** : un module Python par pièce, cotes communes dans `params.py`, export STEP + STL ([§5.3](#53-sources--hardware)) |
| **OpenSCAD / MakerWorld Parametric Model Maker** | seulement pour régler les modèles de tiers déjà publiés en OpenSCAD (net-pots, embouts, tours) |
| **OrcaSlicer / Elegoo Slicer** | profils matériau ASA/PETG pour la CC2 ; modificateurs de parois locales |

### 5.2 Cotes à mesurer avant d'imprimer

| Cote | Où elle sert | Outil |
|---|---|---|
| Ø extérieur de chaque tube de structure | B1, B2, D4, D8 | pied à coulisse (mesurer à 3 endroits, ovalisation) |
| Épaisseur du film (µm) | B2 | fiche du film (150–200 µm courant) |
| Section des canaux NFT, Ø des net-pots | A1, A2, A3 | pied à coulisse |
| Ø des sondes pH, EC, DS18B20 ; Ø et zone aveugle JSN-SR04T | A4 | fiche technique + mesure |
| Section de la rampe LED, entraxe des fixations, masse | C1, C2 | balance + pied à coulisse |
| Dimensions des cartes (XIAO, LD2450, Pi + HAT) | D2, D3, D6 | fiches + mesure |
| Jeu d'ajustement réel de la CC2 | toutes | éprouvette : anneaux de jeu 0,1 à 0,5 mm |

### 5.3 Sources : `hardware/`

```
hardware/
├── params.py        # toutes les cotes (nominales) + verifier() : règles de ce document
├── mesures.toml     # cotes mesurées, remplacent les nominales (mode d'emploi : MESURES.md)
├── lib/commun.py    # pince sur tube, passe-sonde à bague TPU, inserts M3, graduations, texte
├── pieces/          # un module par pièce : pieces(p) -> {nom: solide}
├── build.py         # freecadcmd : vérifie les cotes, contrôle chaque solide, STEP + STL
├── tiers/           # modèles de tiers téléchargés, par fiche (non versionné : licences)
└── README.md        # pièce → priorité, matériau, réglages, quantité, statut ; modèles tiers
                     #   (liens, licences, tenue sur le plateau) ; quincaillerie à acheter
```

```bash
make etiquettes      # hardware/build/etiquettes.json depuis serre.yaml (QR : extra hardware)
make hardware        # toutes les pièces -> hardware/build/ (non versionné)
```

- Une cote changée dans `mesures.toml` se propage à toutes les pièces ; `make hardware`
  refuse de rendre si une règle est violée (jeu, emmanchement ≥ 1,5 Ø, garde du JSN-SR04T
  ≥ 250 mm, écart pH/EC, enveloppement du clip, arêtes, volume d'impression, trous de la
  platine qui se chevauchent) et liste les cotes encore nominales.
- `tests/test_hardware.py` teste les cotes, les règles et les étiquettes partout ; le rendu de
  chaque pièce seulement si FreeCAD est installé (Ubuntu 24.04 : `sudo snap install freecad`,
  commande `freecad.cmd` ; avec apt : `freecadcmd`).
- Les STL de tiers ne sont pas versionnés (licences) : le README donne le lien. Une fois
  téléchargés, ils sont rangés dans `hardware/tiers/<fiche>/` (ignoré par git) et le README
  note leur licence, s'ils tiennent sur le plateau de la CC2 et ce qui reste à adapter.
  Premier lot (29/10/2026) : A1 tours Creality et Printables, A2 net-pot, A3 Kratky,
  D3 radar, D6 boîtier Pi 5, E clip. À retenir : l'adaptateur de seau de la tour Printables
  (318 mm) ne tient pas sur la CC2, les net-pots sont des STL sans sources OpenSCAD, le
  boîtier Pi 5 téléchargé n'a pas de place pour le Hailo.
- Les étiquettes (E) sont générées depuis les emplacements de `serre.yaml`
  (`tools/hardware/etiquettes.py`) ; le QR contient l'id de l'emplacement (préfixe d'URL en
  option, quand l'interface aura une page par emplacement).

## 6. Priorités

Même convention que [18 §1](18-ameliorations-logicielles.md#1-principes). L'état de chaque
pièce (écrite, rendue, imprimée, validée) est suivi dans [hardware/README.md](../hardware/README.md).

| Priorité | Pièces | Raison |
|---|---|---|
| **P0** | D1 abri ventilé, D2 boîtiers étanches, A4 couvercle de cuve et sondes, D4/D5 caméra et mire fixes | justesse des données et sécurité du matériel, avant toute mise en serre réelle |
| **P1** | B1 raccords, B2 clips de bâche, C1 supports de lampe, A1/A2 hydroponie, D3 radar, D8 câbles | construction de la serre et des cultures |
| **P2** | E culture, B3 ouvrants, B4 gouttières, D6/D7 supports, étiquettes | confort et finition |
| **Évolution** | C3 lampe motorisée | après validation de C1 et du suivi de hauteur par caméra |

## 7. Sécurité

- **Charges suspendues** : toute lampe au-dessus des plantes a un **câble de sécurité
  métallique** indépendant de la pièce imprimée. Les plastiques fluent sous charge permanente
  et à la chaleur : une pièce qui tient un mois peut céder le suivant.
- **Chaleur** : pas de PETG à moins de 5 cm d'un driver LED, d'un dissipateur ou du chauffage ;
  ASA/ABS seulement, et jamais en contact avec une résistance chauffante.
- **Électricité et eau** : boîtiers secteur (relais, alimentations) avec presse-étoupes et
  évent bas ; jamais de boîtier imprimé comme seule enveloppe d'un circuit 230 V sans
  boîtier électrique homologué à l'intérieur ; câbles en goutte (boucle sous le boîtier).
- **Alimentaire** : le FDM est poreux ; pour les pièces en contact durable avec la solution,
  PETG ou ASA, parois épaisses, et enduit époxy alimentaire si besoin. Rincer avant usage.
- **Vent** : en extérieur, la tenue vient des piquets, du tube et des sangles, pas des
  raccords imprimés. Surdimensionner les raccords des angles et du faîtage.
- **Impression** : l'ASA et l'ABS émettent du styrène ; imprimer caisson fermé, pièce ventilée.
