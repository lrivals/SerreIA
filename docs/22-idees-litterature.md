# 22 — Idées à implémenter, tirées de la littérature

**But** : transformer la base de littérature du projet en idées concrètes pour SerreIA. Pour
chaque idée, on part de l'état du code, on lit ce que disent les articles, chiffres et passages à
l'appui, puis on propose des fichiers à modifier, un critère de validation et les risques. Ce
document ne modifie aucun code : il complète [18](18-ameliorations-logicielles.md) (plan logiciel)
et [15](15-ameliorations-detection.md) (détection) sans les répéter, et y renvoie quand un point
y figure déjà.

> **Périmètre** : SerreIA `main` au commit `cac25f9`. Base de littérature
> [`lrivals/PaperDatabase`](https://github.com/lrivals/PaperDatabase), dossier `bases/serre/`, au
> commit `0ff7ce7` (03/11/2026) : 67 articles, toutes les fiches `done`. Lecture seule des deux
> dépôts. Aucun test ni entraînement lancé.

## 1. Introduction

### 1.1 Contexte

Le contrôleur ([06 §4](06-capteurs-controle.md#4-stratégie-de-contrôle--edgecontroller)) applique
des **recettes** par espèce et par stade (`edge/controller/recettes.yaml`,
[09 §6](09-modele-gestion-serre.md#6-recettes-de-culture)). Il y ajoute des règles de risque
(`risk.py`), des règles « classification → action » (`vision_rules.py`, `regles.yaml`,
[10 §5](10-decisions-tracabilite.md#5-routines-et-actions-exceptionnelles)) et une prévision
(`forecast.py`). Les valeurs de ces fichiers ont été posées sans source. L'analyse
([17](17-analyse-systeme.md)) et le plan ([18](18-ameliorations-logicielles.md)) traitent la
justesse du logiciel. Ce document traite la **justesse agronomique et méthodologique** : les
consignes, les seuils de risque et les protocoles d'évaluation sont-ils ceux de la littérature ?

### 1.2 Méthode

1. Lecture de `bases/serre/CLAUDE.md`, `profile.md` et `INDEX.md`, puis des 67 fiches, et
   surtout de leurs sections « Consignes chiffrées », « Écart avec SerreIA » et « Pour SerreIA ».
   Les chiffres de modèles viennent de `benchmarks.csv`.
2. Lecture du code cité (`recettes.yaml`, `regles.yaml`, `risk.py`, `rules.py`, `vision_rules.py`,
   `forecast.py`, `sim/model.py`, `vision/eval/`) et des docs 06, 09, 10, 11, 14, 15, 17 et 18.
3. Une idée n'est retenue que si une fiche la soutient par une valeur ou un résultat lu.

Conventions :

| Notation | Sens |
|---|---|
| `2018-shamshiri#005.0` | passage cité : alias de l'article (§1.3), puis numéro de chunk tel qu'il figure dans la fiche. Quand la fiche donne un numéro nu (`#009.2`), on le préfixe par l'alias |
| `chunk n/r` | la fiche donne la valeur avec sa section ou sa table, mais sans numéro de chunk |
| **n/r** | valeur non rapportée par la fiche. On ne l'estime jamais |
| *déduit* | inférence de la fiche ou de ce document, pas une lecture de l'article |
| ⚠ | source faible : guide commercial, littérature grise, valeur mesurée en essai et non optimale, test in-domain, seuil calibré sur les données d'évaluation |

### 1.3 Sources

Les articles cités ici, avec leur alias. Tous sont dans `bases/serre/papers/<paper_id>/fiche.md`.

| Alias | `paper_id` | Article | Nature, force |
|---|---|---|---|
| `2018-shamshiri` | `2018-shamshiri-review-optimum-temperature-humidity-vapour` | Shamshiri et al., *Review of optimum temperature, humidity, and VPD… tomato*, Int. Agrophysics 2018 | revue ; valeurs de seconde main, dont des blogs et sites commerciaux (Argus, Just4Growers) ⚠ |
| `2017-zhang` | `2017-zhang-vapour-pressure-deficit-control-relation` | Zhang et al., *VPD control… greenhouse tomato during summer*, Sci. Rep. 2017 | essai, un site, une saison, été chaud |
| `2026-fanourakis` | `2026-fanourakis-climate-driven-pest-disease-dynamics` | Fanourakis et al., *Climate-Driven Pest and Disease Dynamics in Greenhouse Vegetables*, Horticulturae 2026 | revue ; plages indicatives, tomate, concombre, poivron |
| `2015-rowlandson` | `2015-rowlandson-reconsidering-leaf-wetness-duration-determination` | Rowlandson et al., *Reconsidering Leaf Wetness Duration Determination*, Plant Disease 2015 | revue, plein champ ; transfert à la serre non couvert |
| `2022-liu` | `2022-liu-model-methodology-early-warning-detection` | Liu et al., *Early warning detection of cucumber downy mildew in greenhouses*, COMPAG 2022 | concombre, une serre, un événement ; seuil 92,85 % calibré sur les données d'évaluation ⚠ |
| `2019-santiago` | `2019-santiago-integrated-pest-management-manual-greenhouses` | Santiago et al., *IPM Manual for Greenhouses*, UNL 2019 | rapport de master, compilation ⚠ |
| `2021-nikolaou` | `2021-nikolaou-energy-water-related-parameters-tomato` | Nikolaou et al., *Irrigation and Fertigation* (tomate, concombre), Horticulturae 2021 | revue ; EC de la solution **apportée** |
| `1990-hochmuth` | `1990-hochmuth-fertilizer-management-greenhouse-vegetables-florida` | Hochmuth, *Fertilizer Management for Greenhouse Vegetables*, UF/IFAS (révision 2012) | guide de vulgarisation, Floride ⚠ |
| `2018-savvas` | `2018-savvas-application-soilless-culture-technologies-modern` | Savvas & Gruda, *Soilless culture technologies*, Eur. J. Hortic. Sci. 2018 | revue ; Table 3 (EC tomate) sans corps extrait |
| `2020-miller` | `2020-miller-maximizing-productivity-greenhouse-grown-hydroponic` | Miller et al., *Hydroponic Lettuce during Winter*, HortScience 2020 | essai d'hiver ; T° air et DLI solaire mesurés **sous** l'optimum ⚠ |
| `2023-ertle` | `2023-ertle-reduced-daily-light-integral-end` | Ertle & Kubota, *Reduced DLI… Tipburn… Indoor Lettuce*, HortScience 2023 | chambre de culture, conditions choisies pour **induire** le tipburn ⚠ |
| `2013-brechner` | `2013-brechner-cornell-hydroponic-lettuce-handbook` | Brechner & Both, *Hydroponic Lettuce Handbook*, Cornell CEA 2013 | handbook, « ce qui a marché chez nous » ⚠ |
| `2021-hosseini` | `2021-hosseini-nutrient-use-vertical-farming-optimal` | Hosseini et al., *Optimal EC… Lettuce and Basil*, Horticulturae 2021 | essai ebb-flow ; T°, HR, CO₂ fixes, non testés |
| `2018-walters` | `2018-walters-effects-nutrient-solution-concentration-daily` | Walters & Currey, *Nutrient Solution Concentration and DLI… Basil*, HortScience 2018 | essai NFT, hiver, 3 semaines |
| `2023-walters` | `2023-walters-modeling-purple-basil-sage-spearmint` | Walters, Tarr & Lopez, *Basil, sage, spearmint… DLI and MDT*, PLOS ONE 2023 | essai ; T° moyenne seule (pas de jour/nuit) |
| `2022-johnnys` | `2022-johnnys-hydroponic-container-basil-guide` | Johnny's Selected Seeds, *Hydroponic & Container Basil*, 2022 | guide commercial ⚠ |
| `2016-depardieu` | `2016-depardieu-sawdust-bark-substrates-soilless-strawberry` | Depardieu et al., *Soilless Strawberry Production*, PLOS ONE 2016 | essai ; T°/HR sont des consignes, pas des optimums testés |
| `2026-garcia` | `2026-garcia-berries-controlled-environment-agriculture` | Garcia, *Berries in CEA* (diapositives), UA-CEAC 2026 | cours, diapositives ⚠ |
| `2024-grodan` | `2024-grodan-irrigating-high-tech-greenhouse-strawberries` | Grodan, *Irrigating high-tech greenhouse grown strawberries*, 2024 | livre blanc commercial, seuils contradictoires ⚠ |
| `2020-preciado-rangel` | `2020-preciado-rangel-interactive-effects-potassium-nitrogen-relationship` | Preciado-Rangel et al., *K/N… Strawberry Soilless* | essai N × K ; T° observées, pas des consignes |
| `2020-moin-eddin-rezvani` | `2020-moin-eddin-rezvani-iot-sensor-data-fusion-determining` | Moin-Eddin Rezvani et al., *IoT sensor data fusion… tomato*, Sensors 2020 | quatre journées, valeurs reprises de la littérature |
| `2019-hemming` | `2019-hemming-remote-control-greenhouse-vegetable-production` | Hemming et al., *Remote Control… with AI* (AGC 2018, concombre), Sensors 2019 | concours, un site, sans répétition |
| `2020-hemming` | `2020-hemming-cherry-tomato-production-intelligent-greenhouses` | Hemming et al., *Cherry Tomato Production in Intelligent Greenhouses* (AGC 2019), Sensors 2020 | concours, un site, sans répétition ; incohérence interne sur les profits |
| `2020-katzin` | `2020-katzin-greenlight-e-open-source-model` | Katzin et al., *GreenLight*, Biosyst. Eng. 2020 | modèle validé sur 112 jours, mêmes données en calibration et en évaluation |
| `2022-katzin` | `2022-katzin-process-greenhouse-climate-models-genealogy` | Katzin et al., *Process-based greenhouse climate models: genealogy*, Agric. Syst. 2022 | revue |
| `2025-cebolla-alemany` | `2025-cebolla-alemany-short-term-forecasting-predictive-control` | Cebolla-Alemany et al., *Short-term forecasting… rooftop greenhouse*, Smart Agric. Tech. 2025 | une serre, un an ; sans baseline de persistance |
| `2025-yu` | `2025-yu-prediction-control-greenhouse-temperature-methods` | Yu et al., *Prediction and control of greenhouse temperature*, COMPAG 2025 | revue ; RMSE agrégés non comparables |
| `2024-jain` | `2024-jain-design-implementation-iot-automated-ec` | Jain & Kaur, *IoT-based automated EC and pH Control… NFT*, ETASR 2024 | prototype |
| `2023-wu` | `2023-wu-laboratory-field-unsupervised-domain-adaptation` | Wu et al., *Unsupervised Domain Adaptation for Plant Disease Recognition in the Wild*, Plant Phenomics 2023 | test transductif, chiffres flattés ⚠ |
| `2305.11533` | `arxiv-2305.11533-embrace-limited-imperfect-training-datasets` | Xu et al., *Embrace Limited and Imperfect Training Datasets*, 2023 | preprint, revue |
| `2021-fuentes` | `2021-fuentes-open-set-self-across-domain` | Fuentes et al., *Open Set Self and Across Domain Adaptation for Tomato Disease*, Front. Plant Sci. 2021 | jeu propre aux auteurs |
| `2025-kwong` | `2025-kwong-tomato-leaf-detection-segmentation-extraction` | Kwong et al., *Tomato Leaf Detection, Segmentation…*, AgriEngineering 2025 | test in-domain, pseudo-labels ⚠ |
| `2022-shoaib` | `2022-shoaib-deep-learning-segmentation-classification-leaf` | Shoaib et al., *Segmentation and classification of leaf images*, Front. Plant Sci. 2022 | in-domain PlantVillage ⚠ |
| `2016-mohanty` | `2016-mohanty-deep-learning-image-plant-disease` | Mohanty et al., *Deep Learning for Image-Based Plant Disease Detection*, Front. Plant Sci. 2016 | référence |
| `1911.10317` | `arxiv-1911.10317-plantdoc-dataset-visual-plant-disease` | Singh et al., *PlantDoc*, 2019 | preprint |
| `1706.04599` | `arxiv-1706.04599-calibration-modern-neural-networks` | Guo et al., *On Calibration of Modern Neural Networks*, 2017 | preprint, référence ; in-domain |
| `2106.07998` | `arxiv-2106.07998-revisiting-calibration-modern-neural-networks` | Minderer et al., *Revisiting the Calibration…*, 2021 | preprint |
| `1906.02530` | `arxiv-1906.02530-can-you-trust-your-model` | Ovadia et al., *Can You Trust Your Model's Uncertainty?*, 2019 | preprint |
| `2026-juniar` | `2026-juniar-edge-seismic-denoising-benchmarking-hailo` | Juniar et al., *Benchmarking the Hailo-8L on Raspberry Pi 5*, 2026 | même matériel, autre tâche (signal) |
| `2022-feng` | `2022-feng-benchmark-analysis-yolo-performance-edge` | Feng et al., *YOLO Performance on Edge Devices*, Cryptography 2022 | autre matériel |
| `2401.10019` | `arxiv-2401.10019-r-judge-benchmarking-safety-risk` | Yuan et al., *R-Judge*, 2024 | preprint |
| `2405.14411` | `arxiv-2405.14411-large-language-models-explainable-decisions` | Zhang et al., *LLMs for Explainable Decisions in Dynamic Digital Twins*, 2024 | preprint |
| `2601.08308` | `arxiv-2601.08308-agriagent-contract-driven-planning-capability` | Yang et al., *AgriAgent*, 2026 | preprint |

Les autres fiches de la base (anomalies, MIL, apprentissage actif, conformal prediction, RL et
MPC) n'apportent pas de valeur nouvelle aux idées ci-dessous. Elles restent la référence de
[15](15-ameliorations-detection.md) et du niveau 3 de [06 §4](06-capteurs-controle.md).

## 2. Synthèse

Priorités au sens de [18 §1](18-ameliorations-logicielles.md#1-principes) : **P0** avant toute
mise en serre réelle (consigne ou règle qui peut nuire aux plantes, mesure faussée), **P1** avant
les 7 jours sans intervention, **P2** au fil de l'eau. L'effort (S, M, L) est une estimation
de ce document.

| # | Idée | Domaine | Prio | Effort | Fichiers principaux |
|---|---|---|---|---|---|
| [L1](#l1--laitue--stades-par-âge-programme-dec-et-plafond-de-dli-p0) | Laitue : stades par âge, programme d'EC, plafond de DLI | consignes et recettes | P0 | M | `recettes.yaml`, `recipes.py`, `rules.py` |
| [L2](#l2--recette-fraise-p1) | Recette fraise | consignes et recettes | P1 | S | `recettes.yaml` |
| [L3](#l3--t-de-la-solution-et-des-racines-p1) | T° de la solution et des racines | consignes et recettes | P1 | S | `recettes.yaml`, `recipes.py`, `rules.py` |
| [L4](#l4--consignes-vpd-p0) | Consignes VPD | VPD | P0 | M | `psychro.py` (nouveau), `recettes.yaml`, `rules.py` |
| [L5](#l5--mildiou--infection-incubation-et-préavis-p0) | Mildiou : infection, incubation, préavis | risque maladie | P0 | M | `risk.py`, `pathogenes.yaml` (nouveau), `forecast.py` |
| [L6](#l6--seuil-dhumectation-calibré-sur-le-site-p1) | Seuil d'humectation calibré sur le site | risque maladie | P1 | M | `serre.yaml`, `tools/` |
| [L7](#l7--botrytis-et-oïdium-p1) | Botrytis et oïdium | risque maladie | P1 | M | `risk.py`, `vision_rules.py` |
| [L8](#l8--brumisation-réservée-à-lacarien-p0) | Brumisation réservée à l'acarien | ravageurs | P0 | S | `vision_rules.py`, `rules.py` |
| [L9](#l9--ec-de-la-tomate--apport-et-drainage-p0) | EC de la tomate : apport et drainage séparés | nutrition | P0 | M | `recettes.yaml`, `recipes.py`, `rules.py` |
| [L10](#l10--irrigation-en-tension-ou-en-fraction-deau-disponible-p1) | Irrigation en tension ou en fraction d'eau disponible | irrigation | P1 | M | `serre.yaml`, `rules.py`, `sim/model.py` |
| [L11](#l11--vision--classes-de-contrôle-crop-masqué-adaptation-de-domaine-p1) | Vision : classes de contrôle, crop masqué, adaptation de domaine | vision | P1 | L | `vision/models/`, `vision/train/`, `vision/eval/` |
| [L12](#l12--vision--calibration-par-tête-et-après-int8-p0) | Vision : calibration par tête et après INT8 | vision | P0 | M | `vision/eval/`, `regles.yaml` |
| [L13](#l13--simulateur-en-bilans-physiques-p1) | Simulateur en bilans physiques | simulateur | P1 | L | `sim/model.py` |
| [L14](#l14--baselines-de-prévision-avant-la-gru-p1) | Baselines persistance et LightGBM avant la GRU | prévision | P1 | M | `forecast.py` |
| [L15](#l15--leçons-de-lautonomous-greenhouse-challenge-p2) | Leçons de l'Autonomous Greenhouse Challenge | commande | P2 | M | `rules.py`, `backend/` |
| [L16](#l16--agent--consignes-sourcées-p1) | Agent : consignes sourcées | agent LLM | P1 | M | `recettes.yaml`, `backend/agent/` |

## 3. Consignes et recettes

### L1 — Laitue : stades par âge, programme d'EC et plafond de DLI (P0)

**Constat.** `laitue-hydro` n'a qu'un stade, `croissance` (`edge/controller/recettes.yaml:40-49`),
avec `ec: [1.0, 1.6]` et `dli_cible: 14` du semis à la récolte. La règle `ec.nutriments` dose sous
la borne basse (`edge/controller/rules.py:220-232`) : une jeune laitue reçoit donc au moins
1,0 mS/cm. La règle `lumiere.photoperiode` vise la cible de DLI, mais aucun plafond ne déclenche
d'alerte quand la lumière naturelle la dépasse (`rules.py:253-309`). Les plantes ont une
`date_semis` (`edge/controller/serre.yaml:24`), mais le stade est saisi à la main.

**Littérature.**
- EC par âge : 0,25 dS/m en pépinière (`2020-miller#003.1`) ; 0,5–0,75 (j 1–20), 0,75–1,0
  (j 21–30), 1,0–2,0 (j 31–40) (`2020-miller#006.0`). Programme appliqué, non comparé à
  d'autres ⚠.
- EC optimale 0,9 dS/m, plage équivalente 0,9–1,5, chute nette à 0,5 ; dépasser l'optimum
  pénalise moins que rester en dessous (`2021-hosseini#010.0`). Ebb-flow : non transférable tel
  quel à NFT ou DWC, d'après les auteurs.
- Seuil de tipburn : symptômes au-delà de 13 mol/m²/j en lumière continue et de 15 en 16 h
  (`2023-ertle#000.2`). Valeurs citées de Caplan 2018 et Sago 2016, non mesurées par Ertle ⚠.
- Fin de cycle : DLI réduit à 9,5 (55 %) pendant les 12 derniers jours, seul niveau rentable et
  pour un cultivar sur deux (`2023-ertle#003.1`, `2023-ertle#008.0`). Perte de rendement jusqu'à
  26 % (`2023-ertle#006.0`).
- DLI 17 avec flux d'air vertical, 15 déjà au maximum pour certains cultivars, 12 sans flux
  d'air (`2013-brechner#011`, `2013-brechner#012`) ⚠.
- DLI 12–15 (`2020-miller#001.0`), valeur de revue citée par Miller.
- Pépinière : 11 j à 24 h et 250 µmol/m²/s (`2013-brechner#007`, `2013-brechner#002`) ⚠.

**Proposition.**
1. `recettes.yaml` : trois stades pour `laitue-hydro`, `pepiniere` (EC [0.25, 0.5] *déduit*,
   photopériode à reprendre de Brechner), `croissance` (EC [0.5, 1.0]), `finition` (EC
   [0.9, 1.5], `2021-hosseini`).
2. `recipes.py` (`StageSetpoints`) : champ facultatif `duree_j`. La transition de stade se calcule
   depuis `date_semis` à l'export de la configuration (`backend/config/export.py`), et le stade
   manuel reste prioritaire. Le changement de stade devient une décision tracée
   ([10](10-decisions-tracabilite.md)).
3. `StageSetpoints` : champ `dli_max`, 13 pour la laitue (`2023-ertle#000.2`) ou 15 avec un
   ventilateur de brassage déclaré (`2013-brechner#011`). Dans `rules.py`, la règle `light` lève
   une alerte `info` si le DLI mesuré dépasse `dli_max`, et coupe tout complément LED au-delà.
4. La réduction de fin de cycle (`2023-ertle#003.1`) reste une proposition de l'agent : elle coûte
   du rendement.

**Validation.**
- Tests unitaires de `recipes.py` : stade calculé pour des `date_semis` à J5, J25, J35.
- Scénario `sim/scenarios/laitue_cycle.yaml` (40 jours simulés) : l'EC suit le programme, et
  aucune impulsion A/B n'a lieu avant J20 au-dessus de 1,0.
- Test : `dli_max` dépassé par le soleil → alerte et aucun complément LED.

**Risques.** Programme mesuré pour un hiver en Indiana ; les seuils de tipburn sont cités de
seconde main ; la pépinière à 0,25 suppose une solution diluée (22 mg/L de N,
`2020-miller#003.1`), pas une cuve commune avec d'autres cultures. En zone mixte,
`recipes.merge` ne peut pas satisfaire deux EC différentes. C'est un argument pour une cuve par
culture.

### L2 — Recette fraise (P1)

**Constat.** Le README annonce la fraise, mais `recettes.yaml` ne contient que tomate, laitue et
basilic (`edge/controller/recettes.yaml:5-61`). La taxonomie vision n'a pas de fraise non plus.

**Littérature.**
- T° air, consignes de l'essai (non testées comme optimum) : jour 21–23 / nuit 17 °C, HR 50 %
  (`2016-depardieu#006.0`) ; en janvier–mars, 16 / 12 °C et HR 60 % ; en mars–avril,
  19–20 / 12–14 °C et HR 50 % (`2016-depardieu#006.3`).
- EC apportée 1,0–1,5 dS/m (recommandation du Québec, `2016-depardieu#016.1`) ; 0,6 à la reprise
  puis jusqu'à 1,6, et 1,2 en floraison et fructification (programme CTIFL, `2016-depardieu#007.0`) ;
  0,6–1,8 cité (`2016-depardieu#002.0`).
- EC ≤ 1 dS/m, prudence au-delà de 1,2 (goût « water-rich ») (`2026-garcia#000.0`) ⚠ diapositives.
- pH 5,5 (`2020-preciado-rangel#011.0`) ; plage observée 5,0–6,6, non un optimum
  (`2016-depardieu#007.1`).
- DLI 17–20 mol/m²/j en serre (`2026-garcia#001.0`) ⚠.
- Drainage ~20 % (`2016-depardieu#007.1`) ; 20–30 % (`2026-garcia#000.0`) ⚠ ; 6 à 12 apports par
  jour d'environ 30 ml (`2026-garcia#000.0`) ⚠.
- Déclenchement de l'irrigation en potentiel matriciel : −1,0 à −1,8 kPa selon le substrat et le
  stade (`2016-depardieu#007.0`, `2016-depardieu#007.1`). Voir [L10](#l10--irrigation-en-tension-ou-en-fraction-deau-disponible-p1).
- Brumisation de nuit, HR 95 % au niveau des plantes pendant au moins 3 h, en climat sec
  (`2026-garcia#005.0`) ⚠.
- Photopériode, CO₂, T° racines, VPD : **n/r** dans les quatre fiches.

**Proposition.** Ajouter `fraise-substrat` à `recettes.yaml`, un seul stade `production` au départ :
`temperature: {jour: [19, 23], nuit: [12, 17]}`, `humidite: [50, 60]`, `ec: [1.0, 1.5]`,
`ph: [5.5, 6.2]`, `dli_cible: 17`. La borne pH 6,2 est un choix prudent (*déduit*). Le conflit d'EC
reste à trancher : 1,0–1,5 (Depardieu, revue par les pairs) contre ≤ 1,0 et alerte à 1,2 (Garcia,
diapositives). Proposition : garder 1,0–1,5 et noter Garcia comme source faible ([L16](#l16--agent--consignes-sourcées-p1)).
`photoperiode_h` reste vide tant qu'aucune source ne la donne. Pas de brumisation nocturne par
défaut (risque Botrytis, [L7](#l7--botrytis-et-oïdium-p1)).

**Validation.** `tests/test_recipes.py` charge la recette. Le scénario `journee` rejoué avec une
zone fraise donne une part du temps dans les plages T°/HR mesurée et rapportée.

**Risques.** Recette assemblée à partir d'essais aux consignes non optimisées et d'une source
faible. La vision ne reconnaîtra pas la fraise (README) : les règles `vision_rules.py` ne s'y
appliqueront pas, ce que `Greenhouse.vision_auto` gère déjà.

### L3 — T° de la solution et des racines (P1)

**Constat.** `recettes.yaml` n'a aucune consigne de T° racinaire. Le capteur `temp_eau` existe
(`common/mqtt/topics.py:20`) et sert d'entrée à la prévision (`edge/controller/forecast.py:44-54`),
mais aucune règle ne le lit. Le simulateur fait suivre l'air à l'eau, sans chauffage
(`sim/model.py:121`), et aucun actionneur ne chauffe la solution (`common/mqtt/topics.py:27-35`).

**Littérature.**
- Laitue : solution à 18,8 °C (consigne 20) → masse sèche maximale avec éclairage d'appoint ;
  13,2 °C non chauffée ; sans éclairage d'appoint, pas de gain significatif
  (`2020-miller#004.3`, `2020-miller#007.0`, `2020-miller#009.0`).
- Basilic : solution à 22,1 ± 0,5 °C, O₂ dissous 8,3 ppm (`2018-walters#002.4`), un seul niveau
  testé.
- Tomate : 27 (Jones), 25 (Ntatsi), 23 en été (Li) ; 15 °C sous-optimal (`2018-shamshiri#004.0`).
- Fusariose favorisée à 24–28 °C en zone racinaire, cible < 25 °C ; Pythium favorisé à 15–20 °C,
  cible 20–24 °C (`2026-fanourakis#027.1`, `2026-fanourakis#027.2`).
- Semis : ne pas rester longtemps sous 60 °F, environ 15,6 °C (`1990-hochmuth#002.1`) ⚠.
- Solution chaude en système flottant : moins d'O₂, sans seuil chiffré (`2018-savvas#009.0`).
- Oxygène dissous ≥ 4 ppm satisfaisant, cible 7–10 (`2013-brechner#022`) ⚠.

**Proposition.**
1. `StageSetpoints` : champ `temp_racines: [min, max]` (tomate [22, 25], laitue [18, 22],
   basilic [20, 24]). Ces plages sont *déduites* : elles bornent les valeurs lues par le risque
   Fusarium et Pythium.
2. `rules.py` : règle `hydro.temperature_solution`, alerte seule tant qu'aucun actionneur ne chauffe
   ou ne refroidit la cuve. Si un chauffe-eau est ajouté, couplage avec le DLI
   (`2020-miller#007.0`) : ne chauffer que si le DLI du jour dépasse ~12 (*déduit*).
3. `sim/model.py` : la constante de 3 h (`:121`) devient un paramètre et la cuve reçoit l'apport
   solaire et la chaleur de la pompe ([L13](#l13--simulateur-en-bilans-physiques-p1)).

**Validation.** Test unitaire de la règle (alerte au-dessus et au-dessous, fin d'alerte). Scénario
`canicule` de [18 S4](18-ameliorations-logicielles.md#s4--scénarios-saisonniers-p1) : alerte de
solution chaude émise.

**Risques.** Sans actionneur, la règle reste une alerte. Les plages sont propres à un cultivar et à
un système (CFT, NFT) ; la tomate et la Fusariose donnent des optimums qui se recouvrent mal
(23–27 contre < 25).

## 4. VPD

### L4 — Consignes VPD (P0)

**Constat.** Aucune occurrence de `vpd` dans le code Python ni dans les YAML. Les consignes
d'humidité sont des HR (`recettes.yaml:10, 16, 25, 33, 45, 56`). La brumisation se déclenche sur
HR < min, de jour comme de nuit (`rules.py:156-169`). [18 S3](18-ameliorations-logicielles.md#s3--modèle-physique-plus-réaliste-p2)
prévoit seulement d'exposer le VPD dans le simulateur.

**Littérature.**
- Tomate : VPD 0,5–1,2 kPa, marginal 0,45–1,25 ; seuils de commande < 0,45 déshumidifier,
  > 1,25 brumiser (`2018-shamshiri#006.0`). Sources Argus et blog de producteur ⚠.
- Tomate : 0,5–0,8 (Barker) ; 0,4–0,79 (Omafra) (`2018-shamshiri#005.3`).
- Le VPD seul ne peut pas servir de retour en boucle fermée : 0,85 kPa = 15 °C à 50 % ou
  34 °C à 84 % (`2018-shamshiri#008.0`).
- Risque : VPD < 0,43 kPa → champignons et carences ; < 0,2 → infection la plus grave ; < 0,2 ou
  > 2,2 → risque accru (`2018-shamshiri#011.0`).
- Référence de calcul : HR 90 % à 25 °C donne 0,317 kPa (Table 5, `2018-shamshiri#016`).
- Tomate, été chaud : cible de midi 1–2 kPa ; brumisation on au-dessus de 1,2, off à 0,5
  (`2017-zhang#009.2`). Rendement +22,7 % (`2017-zhang#004.1`), effet confondu avec la baisse de
  T° (fiche, Limites).
- Gestion phytosanitaire : HR 60–75 % et VPD ≈ 0,6–1,0 kPa (`2026-fanourakis#013.2`,
  `2026-fanourakis#035.0`) ; VPD < 0,4 favorise Botrytis, Phytophthora, Cladosporium ; > 1,2
  favorise acariens et thrips (`2026-fanourakis#035.0`).
- Laitue : consigne de jour 0,87 kPa, mesuré 0,50–0,75 (`2023-ertle#013.0`), dans un essai qui
  induit le tipburn ⚠.
- Basilic : **n/r**. Fraise : **n/r**.

**Proposition.**
1. `edge/controller/psychro.py` (nouveau) : `vpd(t, hr)`, `point_de_rosee(t, hr)` et
   `humidite_absolue(t, hr)`. Même code dans `sim/` ([18 S3](18-ameliorations-logicielles.md#s3--modèle-physique-plus-réaliste-p2))
   et dans l'ingestion, pour exposer le VPD dans Grafana et à l'agent (`get_mesures`).
2. `StageSetpoints` : champ facultatif `vpd: [min, max]` (tomate [0.5, 1.2], laitue [0.5, 0.9]
   *provisoire*, basilic et fraise vides).
3. `rules.py` : le VPD **contraint** les actionneurs mais ne les pilote pas seul
   (`2018-shamshiri#008.0`). La brumisation `climat.humidite.brumisation` est refusée si
   VPD < `vpd.min` et autorisée en dessous de l'HR min seulement si VPD > `vpd.max`. La ventilation
   d'humidité démarre aussi si VPD < `vpd.min`. Les consignes T° et HR restent les régulateurs.
4. Les preuves des décisions portent le VPD calculé (`agregat: "vpd"`), pour l'agent et la fiche
   décision.

**Validation.**
- `tests/test_psychro.py` : 90 % à 25 °C → 0,317 kPa ± 0,005 (`2018-shamshiri#016`), plus quelques
  points de la même table.
- Scénario `journee` : part du temps dans la plage VPD, nombre de brumisations refusées.
  Scénario `canicule` : VPD > 2,2 kPa signalé.

**Risques.** L'erreur d'un capteur HR près de la saturation donne une grosse erreur de VPD. On
utilise la T° d'air faute de T° de feuille. Les seuils viennent en partie de sources faibles et
d'un seul été chaud (`2017-zhang`).

## 5. Risque maladie et ravageurs

### L5 — Mildiou : infection, incubation et préavis (P0)

**Constat.** `mildew_risk` (`edge/controller/risk.py:89-100`) déclenche si la T° moyenne sur 12 h
est dans [10, 25] °C et si l'humectation (HR > 90 % continue) dure au moins 10 h, ou si la vision
confirme le mildiou et que HR > 85 %. Les seuils sont dans `serre.yaml:96` et `config.py:191-197`.
Pas d'incubation, pas de date de symptômes : l'alerte arrive après 10 h d'humectation, donc après
le début de l'infection. La prévision ventile la nuit si l'HR prévue à +6 h dépasse 85 %
(`forecast.py:437-450`), sans passer par le modèle de risque.

**Littérature.**
- Modèle en deux étages (mildiou du concombre, *Pseudoperonospora cubensis*) : infection si
  LWD ≥ 2 h, T° pendant l'humectation dans [5, 30] °C et LWD × TLWD ≥ 40 h·°C ; incubation par
  cumul horaire, 0,015 h⁻¹ à 20 °C, soit 67 h jusqu'aux symptômes (`2022-liu#004.0`).
- Recalcul horaire sur un horizon glissant de 72 h (`2022-liu#007.0`) ; préavis de 2 à 3 jours
  avec la prévision météo (`2022-liu#013.0`).
- Sur l'unique événement, fin d'incubation prévue le 24 avril 11:15 (capteurs), symptômes observés
  le 24 avril ; 2 faux positifs les 15 et 16 avril (`2022-liu#009.0`) ⚠ un événement.
- *Phytophthora infestans* (tomate) : 18–24 °C, HR > 90 %, VPD < 0,4, eau libre nécessaire ; durée
  **n/r** (`2026-fanourakis#027.1`).
- Le seuil « 10 h » n'est retrouvé dans aucune fiche (`2026-fanourakis`, `2015-rowlandson`,
  `2022-liu` : n/r).

**Proposition.**
1. `edge/controller/pathogenes.yaml` (nouveau) : un bloc par couple (pathogène, culture), avec
   `lwd_min_h`, `t_humectation: [min, max]`, `degres_heures_min`, `incubation` (taux par T° ou
   tableau) et la source de chaque valeur. Valeurs de `2022-liu` pour le concombre, à ne pas
   appliquer à la tomate sans source : pour `tomate/mildiou`, seuls la plage de T° et le VPD de
   `2026-fanourakis#027.1` sont sourcés, la durée reste n/r et l'on garde 10 h, marqué « non sourcé ».
2. `risk.py` : `RiskIndex` passe à une machine à états `sain → infection → incubation → symptomes_attendus`,
   la T° étant prise **pendant** l'humectation. La date de symptômes prévue va dans les preuves.
   La vision confirme l'état, elle ne le crée pas.
3. Préavis : le même calcul tourne sur la trajectoire prévue par `forecast.py` (+1 h à +6 h, puis
   plus loin quand [L14](#l14--baselines-de-prévision-avant-la-gru-p1) le permettra). La règle
   `prevision.humidite.ventilation_preventive` en devient un cas particulier.

**Validation.**
- Test unitaire : à 20 °C constant, l'incubation atteint 1 en 67 h ± 1 h (`2022-liu#004.0`).
- `sim/scenarios/mildiou.attendus.yaml` : état `infection` à l'heure attendue, date de symptômes
  dans la fenêtre du scénario, pas d'alerte sur une humectation de moins de 2 h.
- Métrique sur données réelles : avance de l'alerte sur l'observation, faux positifs par mois.

**Risques.** Paramètres d'un autre pathogène et d'une autre culture ; un seul événement validé ;
erreur de prévision d'HR de 15 à 35 % RMSE chez Liu (`2022-liu#011.1`), alors que le seuil d'HR
est net. Plus de faux positifs possibles si l'on abaisse la durée de 10 h à 2 h.

### L6 — Seuil d'humectation calibré sur le site (P1)

**Constat.** `hr_humectation: 90` est fixe (`serre.yaml:96`, `config.py:192`). Le second seuil,
85 %, est codé en dur dans `vision_rules.py:238` et dans `risk.py:96`.

**Littérature.**
- Proxy LWD = heures avec HR ≥ 90 % (`2015-rowlandson#006.4`). Seuils recalibrés par site : 83 %
  (Ames), 85 % (Elora), 92 % (Florence), 90 % (Piracicaba) (`2015-rowlandson#006.5`).
- Seuil local attendu entre 80 et 95 %, à établir par observation visuelle sur au moins cinq
  occasions : début à l'apparition des gouttelettes, fin quand ≥ 80 % de la canopée est sèche
  (`2015-rowlandson#009.2`).
- Rosée maximale vers 3/4 de la hauteur de canopée (`2015-rowlandson#004.4`). Capteur de feuille
  peint gris très clair, repeint au moins une fois par an (`2015-rowlandson#004.2`,
  `2015-rowlandson#005.1`) ; écart capteur–observation < 1 h (`2015-rowlandson#005.0`).
- Serre de Beijing : 92,85 % calibré (`2022-liu#012.0`) ⚠ calibré sur les données d'évaluation.
- Tout cela vient du plein champ ; la serre n'est pas traitée (fiche `2015-rowlandson`, *déduit*).

**Proposition.**
1. `serre.yaml` : `risque.hr_humectation` par zone (le seuil global devient la valeur par défaut),
   et le 85 % de `vision_rules.py:238` et `risk.py:96` vient de la même clé
   (cohérent avec [18 C7](18-ameliorations-logicielles.md#c7--une-source-unique-pour-les-seuils-vision-p1)).
2. Saisie d'observations : un événement « feuilles mouillées / sèches » posé depuis l'UI ou
   l'agent (`proposer_etat_plante` étendu, ou nouvel outil), horodaté par emplacement.
3. `tools/calibrer_humectation.py` : pour chaque seuil de 80 à 95 % par pas de 1, l'erreur en heures
   entre la LWD estimée et la LWD observée ; on retient le minimum. Il faut au moins 5 événements.
4. Optionnel : capteur d'humectation foliaire (`SensorType.HUMECTATION`) sur le nœud climat, posé
   aux 3/4 de la canopée.

**Validation.** Test de l'outil sur des séries synthétiques (le seuil d'origine est retrouvé). Sur
site : ≥ 5 événements, erreur médiane de LWD < 1 h (critère *déduit* de `2015-rowlandson#005.0`).

**Risques.** Les observations manuelles sont rares et biaisées (on regarde le matin). Le capteur
mesure à une hauteur unique. Le seuil peut dériver avec la saison.

### L7 — Botrytis et oïdium (P1)

**Constat.** La seule règle climatique de risque est le mildiou (`risk.py`). L'oïdium n'est qu'une
surveillance vision, conditionnée à HR 40–70 % et 20–27 °C (`vision_rules.py:275-277`). Botrytis
n'a pas de règle. Pour le mildiou, la consigne d'HR max est abaissée de 10 points pendant 72 h
(`regles.yaml:11-12`), sans plancher.

**Littérature.**
- Botrytis : 15–22 °C, HR > 90 %, VPD < 0,5, condensation et tissus sénescents ; cible HR < 85 % et
  VPD 0,6–0,8 (`2026-fanourakis#027.0`) ; HR < 80 % pour la lutte contre Botrytis, contre 70–85 %
  pour le rendement (`2026-fanourakis#036.0`). Durée d'humectation **n/r**.
- Fenêtre critique : la durée de la condensation après le refroidissement nocturne
  (`2026-fanourakis#013.2`). Irrigation de nuit = facteur de risque (`2026-fanourakis#035.2`).
- Oïdium : 20–28 °C, HR 60–80 %, VPD 0,6–1,0, sans eau libre ; favorisé par les fortes variations
  d'HR et le manque d'UV (`2026-fanourakis#027.0`, `2026-fanourakis#003.1`).
- Sous HR 55–60 % : acariens, thrips et Tuta favorisés (`2026-fanourakis#035.0`,
  `2026-fanourakis#031.0`).
- Laitue : HR élevée → Botrytis et mildiou favorisés, sans seuil (`2013-brechner#019`) ⚠.
- Fraise, basilic : **n/r** dans `2026-fanourakis`. Basilic : le mildiou est une des deux maladies
  principales (`2022-johnnys#005.0`) ⚠, sans conditions chiffrées.

**Proposition.**
1. Dans le cadre de [L5](#l5--mildiou--infection-incubation-et-préavis-p0), `pathogenes.yaml`
   reçoit `botrytis` (nuit, 15–22 °C, HR > 90 % ou VPD < 0,5, point de rosée à moins de 1 °C de la
   T° d'air comme proxy de condensation *déduit*) et `oidium` (20–28 °C, HR 60–80 %, amplitude
   d'HR sur 24 h).
2. Réponse Botrytis : cycle chauffage puis ventilation en fin de nuit, comme pour le mildiou
   (`2026-fanourakis#027.0`), à l'intérieur des limites de `safety.py`.
3. `vision_rules.py:277` : remplacer la condition HR 40–70 % par 60–80 % (`2026-fanourakis#027.0`)
   et prendre les seuils dans `pathogenes.yaml`.
4. `regles.yaml` : plancher `hr_min_abaissement: 60` sous lequel l'abaissement mildiou ne descend
   pas (`2026-fanourakis#035.0`).

**Validation.** Scénario `botrytis_nuit` (nuit froide et humide, refroidissement rapide) : alerte et
cycle chauffage-ventilation. Test : la consigne mildiou abaissée ne passe jamais sous 60 %. Test :
la surveillance oïdium se déclenche à 75 % d'HR, plus à 45 %.

**Risques.** Plages indicatives, issues de revues ; aucune durée de seuil ; tomate, concombre et
poivron seulement. Un indice de plus, ce sont aussi des alertes en plus : à mesurer sur le
scénario `journee` (zéro alerte attendue par temps sec).

### L8 — Brumisation réservée à l'acarien (P0)

**Constat.** `nuisible.brumisation` propose 30 s de brumisation pour **toute** classe
`*/nuisible/*` si HR < 50 % (`vision_rules.py:316-335`, `regles.yaml:15`), de jour comme de nuit.
La taxonomie compte plusieurs nuisibles, dont `tomate/nuisible/tetranyque`
(`vision/datasets/taxonomy.yaml:46`) et des ravageurs du maïs, de l'anacardier et du manioc.

**Littérature.**
- Acarien : 28–35 °C, HR < 50 %, VPD > 1,2, une génération en 1 à 2 semaines ; levier : HR modérée
  60–70 % (`2026-fanourakis#032.0`) ; une déshumidification excessive favorise les acariens
  (`2026-fanourakis#011.0`).
- *Phytoseiulus persimilis* (prédateur de l'acarien) exige T < 27 °C et HR 60–80 %
  (`2019-santiago#014.0`) ; temps sec et chaud et stress hydrique favorisent l'acarien
  (`2019-santiago#019.1`) ⚠.
- Le manuel ne propose jamais la brumisation comme moyen de lutte ; elle est inutile contre thrips,
  aleurodes et pucerons (fiche `2019-santiago`, *déduit*).
- Thrips : HR < 60 %, VPD > 1,0 ; cible HR > 60 % et VPD 0,6–1,0 (`2026-fanourakis#031.1`).
  Aleurodes : 25–32 °C, HR 50–70 %, cible T < 28 °C (`2026-fanourakis#031.0`).
- Seuils de cartes jaunes (aleurodes) : 0,25–0,5 adulte/cm² → lutte biologique ; 3–4 → lutte
  chimique ; une carte par 3–5 m² (`2019-santiago#008.0`) ⚠.

**Proposition.**
1. `vision_rules.py` `_pest` : brumisation seulement pour une classe d'acarien (`*/nuisible/tetranyque`,
   `*/nuisible/acarien*`), **de jour**, avec HR < 50 % ou VPD > 1,2 ([L4](#l4--consignes-vpd-p0)),
   et jamais si un indice Botrytis ou mildiou est actif ([L5](#l5--mildiou--infection-incubation-et-préavis-p0),
   [L7](#l7--botrytis-et-oïdium-p1)). La cible d'HR est 60–70 % et la règle s'arrête à la borne.
2. Autres nuisibles : inspection, recapture et conseil de dépistage (cartes jaunes ou bleues,
   seuils de `2019-santiago#008.0`) dans le message de décision, sans action.
3. `rules.py:156-169` : pas de brumisation `climat.humidite.brumisation` la nuit (*déduit* de
   `2026-fanourakis#035.2`), sauf recette qui l'autorise explicitement.

**Validation.** Tests de `vision_rules.py` : thrips à HR 40 % → pas d'ordre ; acarien à HR 40 % de
nuit → pas d'ordre ; acarien de jour → 30 s. Scénario `mildiou` : aucune brumisation pendant la
période humide.

**Risques.** Faible : on retire des actions. Il faut une classe d'acarien correctement reconnue ;
hors domaine, la tête `classe` a une F1 de 0,264 ([17 §10.1](17-analyse-systeme.md#101-résultats-mesurés-14)).

## 6. Irrigation et nutrition

### L9 — EC de la tomate : apport et drainage (P0)

**Constat.** `tomate-standard` a une seule plage `ec` : [2.0, 3.0] en croissance et [2.5, 3.5] en
floraison et fructification (`recettes.yaml:21, 29, 37`). Elle **monte** avec le stade. La règle
`ec.nutriments` compare une seule mesure à cette plage (`rules.py:220-250`). Rien ne distingue la
solution apportée de la solution drainée ou de la zone racinaire.

**Littérature.**
- Solution apportée, climat méditerranéen : 2,80 / 2,50 / 2,40 / 2,40 / 2,30 dS/m du stade I
  (départ) au stade V (> 10 grappes), pH 5,6 (Table 10, `2021-nikolaou#027.0`). L'EC **décroît**.
- Europe du Nord : 2,60 (A) et 1,6 (B), systèmes A et B non définis dans l'extrait
  (`2021-nikolaou#026.0`).
- Drainage en boucle fermée à 3 ± 0,8 dS/m (`2021-nikolaou#002.1`), citation de Neto et al.
- Formule 4 (Floride), stades A à E : EC 0,8 / 1,0 / 1,4 / 1,6 / 2,0, pH 5,5 (`1990-hochmuth#033.2`) ⚠
  climat chaud ; l'auteur prévient que les programmes nordiques sont souvent excessifs.
- Écart EC substrat − EC apportée à garder dans ± 1,0 dS/m (`1990-hochmuth#014.1`) ⚠. Eau
  d'appoint > 1,5 dS/m = mauvaise qualité (`1990-hochmuth#007.1`) ⚠. Ne pas piloter à l'EC seule
  (fiche `1990-hochmuth`, Limites).
- La solution apportée n'est qu'un moyen ; la cible est la zone racinaire, estimée via le drainage
  (`2018-savvas#025.0`, `2018-savvas#025.1`). La Table 3 (EC tomate par stade) n'a pas de corps
  extrait : **n/r**.
- Limite d'EC de l'eau brute : 1,0 dS/m en drain ouvert, < 0,5 en système fermé
  (`2021-nikolaou#005.3`).

**Proposition.**
1. `StageSetpoints` : `ec` devient `ec_apport` (solution de la cuve) ; ajout de `ec_drainage`
   facultatif. Tomate : `ec_apport` 2,8 → 2,3 en décroissant (`2021-nikolaou#027.0`), `ec_drainage`
   [2.2, 3.8] (`2021-nikolaou#002.1`). La clé `ec` reste lue comme alias de `ec_apport` pour ne pas
   casser `serre.yaml` ni les attendus.
2. `SensorType.EC_DRAINAGE` (nouveau, facultatif) pour une sonde dans le bac de drainage.
   `rules.py` : si EC drainage > `ec_drainage.max`, alerte « lessiver ou augmenter la fraction
   drainée » ; si |EC drainage − EC apport| > 1,0, alerte (`1990-hochmuth#014.1`).
3. Recirculation (NFT, DWC) : la cuve est un mélange apport-drainage (*déduit*) ; on y applique
   `ec_apport` seule.
4. pH tomate : [5.6, 6.2] plutôt que [5.8, 6.3] (`2021-nikolaou#027.0`, `2018-savvas#026.2`).

**Validation.** Tests de chargement (ancienne clé `ec` acceptée). Tests de `rules.py` sur
`ec_drainage`. Le scénario `journee` reste vert sans modification de ses attendus.

**Risques.** Les EC citées viennent de serres méditerranéennes et nordiques sur laine de roche ;
la plage de Floride (0,8–2,0) est à l'opposé. Un capteur de plus. Contrat MQTT modifié : passer
par [18 M1](18-ameliorations-logicielles.md#m1--version-du-contrat-p1).

### L10 — Irrigation en tension ou en fraction d'eau disponible (P1)

**Constat.** `humidite_sol` est une teneur en % de sondes capacitives (`recettes.yaml:3, 13, 22`).
`sol.arrosage` arrose une durée fixe dès que la valeur passe sous le min (`rules.py:312-348`).
Le simulateur sèche le sol à taux constant (`sim/model.py:103-106`).

**Littérature.**
- Substrat : déclencher avant −5 kPa, ou dès que 0,2 à 0,4 de l'eau facilement disponible (EAW)
  est consommée ; arrêt à la capacité du conteneur (`2018-savvas#038.0`). Ajouter 20 à 30 % de
  drainage au pilotage par rayonnement (`2018-savvas#036.0`).
- Fraise : −1,0 kPa (coco), −1,5 kPa (écorce, sciure) ; plus sec, moins de rendement
  (`2016-depardieu#007.0`) ; −1,2 / −1,5 en production (`2016-depardieu#007.1`). La teneur en eau
  volumique comme seuil : **n/r**.
- Laine de roche : 5 à 6 arrosages par heure, jusqu'à 30 par jour en été méditerranéen ; petites
  doses fréquentes en perlite (`2021-nikolaou#004.1`, `2021-nikolaou#004.2`).
- Fraise : 6 à 12 apports par jour d'environ 30 ml (`2026-garcia#000.0`) ⚠.
- WC % avant irrigation « minimal (60 %) or maximum (40 %) », re-saturation vers 85 %
  (`2024-grodan#001.0`) ⚠ commercial, libellé contradictoire.
- Tomate : 85–90 % de la capacité au champ, en pots (`2017-zhang#009.1`).

**Proposition.**
1. `serre.yaml`, contenant : courbe d'étalonnage par substrat (deux à quatre points, % sonde ↔
   teneur volumique, plus la capacité du conteneur et la teneur à −10 kPa). Les points sont mesurés
   par pesée (*déduit*, procédure à écrire dans [09](09-modele-gestion-serre.md)).
2. `StageSetpoints` : `eau_consommee_max` (fraction d'EAW, 0,3 par défaut, `2018-savvas#038.0`) à
   la place de `humidite_sol` quand une courbe existe. Le % brut reste le repli.
3. `rules.py` `soil` : dose dimensionnée par l'EAW manquante et le débit, plafonnée par
   `duree_max_s`, fractionnée en petits apports (`2021-nikolaou#004.2`).
4. `sim/model.py` : rétention du substrat (EAW, capacité) et drainage au-delà de la capacité
   ([L13](#l13--simulateur-en-bilans-physiques-p1)).

**Validation.** Test de conversion % → fraction d'EAW sur une courbe connue. Scénario `journee` :
nombre d'arrosages par jour et fraction drainée simulée (cible 20–30 %, `2018-savvas#036.0`).

**Risques.** Les sondes capacitives à bas coût dérivent et dépendent du substrat ; une sonde de %
n'est pas transférable entre substrats (fiche `2024-grodan`). Sans mesure du drainage, la fraction
drainée reste simulée.

## 7. Vision

### L11 — Vision : classes de contrôle, crop masqué, adaptation de domaine (P1)

**Constat.** Hors domaine (PlantDoc) : spécificité 0,50, F1 `classe` 0,264, 42,2 % de faux positifs
sur images saines en deux étages ([17 §10.1](17-analyse-systeme.md#101-résultats-mesurés-14)). Le
remplacement de fond n'a jamais été évalué, faute de `data/backgrounds/`
(`configs/clf_effnet_b0.yaml:15-17`, [14 §4.2](14-resultats-phase1.md)). Le classifieur n'a pas de
classe « fond » ; le détecteur n'a qu'une classe `feuille` ([19](19-notebooks-analyse-datasets.md)).

**Littérature.**
- Écart labo → terrain : 99,34 % en domaine, 31,40 % sur des images de terrain
  (`2016-mohanty#009.3`) ; la version segmentée n'est qu'à peine inférieure en domaine
  (`2016-mohanty#009.2`) : le fond n'explique pas tout.
- Affiner sur des images de terrain : 39,87 → 70,53 % (InceptionResNetV2, PlantDoc recadré,
  `1911.10317#024.0`). Le 70,53 est in-domain ⚠.
- Classes de contrôle « fond » et « feuille saine » pour guider l'apprentissage
  (`2305.11533#017.0`) ; classe de fond apprise comme négative (`2021-fuentes#011.0`).
- Masques SAM : Dice 88 %, sur un test in-domain à pseudo-labels (`2025-kwong#030.3`) ⚠. Aucun
  tableau ne compare images segmentées et non segmentées (`2022-shoaib#019.0`) ⚠.
- Adaptation de domaine non supervisée, PlantVillage → PlantDoc recadré, 27 classes : 30,78 %
  sans adaptation, 56,06 % avec MSUN (`2023-wu#030.0`) ; l'entropie seule apporte 4,4 points
  (51,65 → 56,06, `2023-wu#034.0`). Test transductif ⚠.

**Proposition.** Une ablation à un seul facteur, puis l'adaptation, dans cet ordre :
1. Ablation sur PlantDoc (`vision/eval/cross_domain_eval.py`, `two_stage.py`) : même classifieur,
   trois entrées, crop boîte, crop masqué (masques SAM générés hors ligne), image entière.
   Prérequis : [18 V1](18-ameliorations-logicielles.md#8-modèles-et-données-vision-v) (fonds) et V2
   (val hors domaine).
2. Classe `fond` dans `vision/models/multihead.py` (tête `sante` à trois sorties, ou tête de rejet),
   entraînée sur des crops de fond et sur les faux positifs de YOLOv8n (`2021-fuentes#011.0`).
3. Perte d'entropie sur des images cibles non étiquetées (PlantDoc train, puis captures de serre)
   dans `vision/train/train_classifier.py` ; LMMD seulement si l'entropie aide
   (`2023-wu#034.0`). Évaluation sur un découpage PlantDoc **non utilisé** pour l'adaptation.

**Validation.** Spécificité à rappel fixé (0,95) et faux positifs sur images saines, sur PlantDoc
TEST, avec 3 graines et IC bootstrap ([18 V3](18-ameliorations-logicielles.md#8-modèles-et-données-vision-v)).
Une variante n'est retenue que si son IC ne recouvre pas celui de la base. ECE rapportée à côté.

**Risques.** Gains publiés in-domain ou transductifs, non comparables aux métriques binaires de
SerreIA ; SAM trop lourd pour le Pi (masques hors ligne seulement) ; l'adaptation à PlantDoc n'est
pas l'adaptation à la serre réelle.

### L12 — Vision : calibration par tête et après INT8 (P0)

**Constat.** ECE hors domaine 0,13 (`sante`) et 0,30 (`classe`) ; ECE in-domain 0,05 avec un
modèle sous-confiant, effet attendu du `label_smoothing: 0.1` ([14 §5](14-resultats-phase1.md#5-critères-de-sortie-et-calibration),
`configs/clf_effnet_b0.yaml:33`). `regles.yaml:7` garde `classe_conf_min: 0.6` « à remplacer ».
**Écart avec la demande** : la fiche `1706.04599` (mise à jour du 29/10/2026) et la demande
indiquent que `vision/eval/temperature.py` et `vision/eval/decision_search.py` existent. Ils sont
**absents** de `main` au commit `cac25f9` : `vision/eval/` ne contient que `ablation_report.py`,
`cross_domain_eval.py`, `gradcam.py`, `metrics.py` et `two_stage.py`. Ils sont peut-être sur une
branche non poussée, à vérifier.

**Littérature.**
- Temperature scaling : un seul paramètre, argmax inchangé ; ECE CIFAR-100 ResNet-110 16,53 % →
  1,26 % (`1706.04599#022.0`), en domaine ⚠. T s'ajuste sur la NLL d'un jeu de validation réservé
  (`1706.04599#005.0`, `1706.04599#007.3`).
- Sous décalage, le temperature scaling se dégrade : ECE médiane ImageNet-C 0,072, contre 0,032
  pour les deep ensembles et 0,102 sans calibration (Table G.2, chunk n/r, `confidence: medium`
  dans `benchmarks.csv`) (`1906.02530`).
- Le label smoothing rend le modèle sous-confiant ; mieux vaut entraîner sans, puis calibrer
  (App. D, chunk n/r) (`2106.07998`).
- Hailo-8L INT8 sur Pi 5 : calibration de 128 à 1 024 échantillons, effet marginal
  (ΔPearson 0,003, Table 8, chunk n/r) (`2026-juniar`) ⚠ autre tâche (signal sismique).
- Une conversion vers un accélérateur peut dégrader la détection sans erreur visible : confiance
  moyenne 0 % pour YOLOv3-tiny sur NCS2 (`2022-feng#027.0`, `2022-feng#017.0`).

**Proposition.** Elle complète [18 V2](18-ameliorations-logicielles.md#8-modèles-et-données-vision-v) :
1. `vision/eval/temperature.py` (à créer s'il n'existe pas) : un T par tête (`sante`, `classe`),
   ajusté sur `val_xdomain`, jamais sur PlantDoc TEST.
2. ECE à 15 bins, NLL et diagramme de fiabilité, avant et après, en domaine et hors domaine, dans
   `vision/eval/metrics.py`.
3. Réestimer T sur les logits du **HEF** (même `val_xdomain`, sortie Hailo) et l'écrire dans le
   bundle edge à côté du modèle. Le critère HEF contre ONNX de [05](05-edge-deploiement.md) porte
   aussi sur l'ECE.
4. `regles.yaml:7` : `classe_conf_min` choisi par `decision_search.py` sur la courbe
   confiance–exactitude de `val_xdomain`, à rappel donné.
5. Ablation `label_smoothing: 0` puis temperature scaling (`2106.07998`).

**Validation.** ECE hors domaine sur un test jamais utilisé pour T ; faux positifs sur images
saines au seuil retenu ; écart d'ECE entre ONNX et HEF.

**Risques.** Le temperature scaling ne protège pas sous fort décalage (`1906.02530`) ; un
`val_xdomain` PlantDoc ne représente pas la serre. Les ensembles coûtent environ cinq passes, à
comparer au budget Hailo (non mesuré).

## 8. Simulateur

### L13 — Simulateur en bilans physiques (P1)

**Constat.** `sim/model.py` est un premier ordre : la T° relaxe vers l'extérieur, avec une hausse
solaire fixe, un chauffage et la ventilation (`sim/model.py:75-81`). **Les LED n'apportent aucune
chaleur** : `led` n'apparaît que dans le calcul du lux (`:101`). L'HR relaxe vers un équilibre
empirique (`:83-89`), sans humidité absolue ni condensation. La cuve suit l'air (`:121`).
[18 S3](18-ameliorations-logicielles.md#s3--modèle-physique-plus-réaliste-p2) prévoit la
psychrométrie, mais pas les LED ni les parois.

**Littérature.**
- Sortie des lampes (Table 4, chunk n/r) : LED 31 % PAR, 2 % NIR, 2,37 % FIR, 1,63 % convectif et
  63 % extraits par le refroidissement à l'eau ; HPS 36 % PAR, 22 % NIR, 32,5 % FIR, 9,5 % convectif
  (`2020-katzin`). Pour des LED passives, la chaleur est surtout convective et la lampe monte vers
  55 °C en environ 30 min (`2020-katzin#012.0`) ; un état T_lamp avec capacité thermique
  (`2020-katzin#007.3`).
- Coefficient d'échange couverture–air de 3,5 W m⁻² K⁻¹ dans l'essai (`2020-katzin#009`).
- Erreurs de référence : RMSE T° 1,74–2,04 °C, HR 5,52–8,5 % (`2020-katzin#000.0`) ; RRMSE < 10 %
  (`2020-katzin#018.0`) ; HR surestimée par une transpiration mal modélisée (`2020-katzin#018.2`).
- Sur 9 modèles avec éclairage, 6 font une chaleur proportionnelle à la puissance et 2 modèles LED
  l'ignorent (`2022-katzin#032.0`). Les modèles de commande restent simples (`2022-katzin#035.2`).
- Code ouvert MATLAB : https://github.com/davkat1/GreenLight (`2020-katzin#016.0`), licence n/r.

**Proposition.** Un « Van Henten enrichi », recommandé par la fiche `2022-katzin` (*déduit*) :
1. États : `t_air`, `t_paroi` (couverture), `t_couvert` facultatif, `humidite_absolue`, `t_eau`.
2. LED : P_élec × (1 − η_PAR) vers l'air, avec T_lamp du premier ordre (τ ≈ 30 min,
   `2020-katzin#012.0`). η_PAR vient de la fiche constructeur (µmol/J). Les 63 % de
   refroidissement à l'eau de Katzin ne s'appliquent pas à des LED passives (*déduit*).
3. Paroi : échange air–paroi (3,5 W m⁻² K⁻¹ par défaut, `2020-katzin#009`) et rayonnement vers le
   ciel la nuit ; condensation sur la paroi quand elle passe sous le point de rosée, ce qui
   alimente le proxy Botrytis ([L7](#l7--botrytis-et-oïdium-p1)).
4. Garder le modèle actuel en `--modele simple` (attendus inchangés), comme le dit S3.

**Validation.**
- Test de bilan : serre fermée, nuit, LED à 100 % → hausse de T° égale à P × (1 − η) / (U × A)
  à l'équilibre, à 5 % près.
- Plus tard, sur données réelles : ME, RMSE et RRMSE de T° et d'HR au pas de 5 min, calibration sur
  des nuits fermées, évaluation sur d'autres jours ; cibles de comparaison RMSE ~2 °C et 5,5–8,5 %
  d'HR (`2020-katzin#018.0`).

**Risques.** Paramètres non mesurés pour une mini-serre ; un modèle plus riche n'est pas plus juste
sans calibration (`2022-katzin`) ; le temps de simulation des scénarios augmente.

## 9. Prévision et commande

### L14 — Baselines de prévision avant la GRU (P1)

**Constat.** `forecast.py` n'entraîne qu'une GRU, à +1 h et +6 h (`edge/controller/forecast.py:41-43`,
`:141-166`). Aucune baseline : on ne saura pas si la GRU apporte quelque chose.

**Littérature.**
- LightGBM : MAE 0,280 / 0,310 / 0,311 °C et RMSE 0,638 / 0,703 / 0,728 °C à +5 / +10 / +15 min
  (Table 4, `2025-cebolla-alemany#032.0`, `2025-cebolla-alemany#032.1`) ; entraînement 8,0 s + 1,0 s
  (`2025-cebolla-alemany#012.0`). Pas de baseline de persistance ni de réseau récurrent ⚠.
- Pires erreurs autour de la consigne, aux commutations du ventilateur
  (`2025-cebolla-alemany#013.1`) ; l'état des actionneurs (minutes depuis le dernier on/off) est
  une entrée explicite (`2025-cebolla-alemany#005.2`).
- GRU, 25 min : RMSE 0,5857 °C, R² 0,9848 (Oh 2022, `2025-yu#053.0`) ; deep learning, RMSE
  typique 0,3 à 1,3 °C (`2025-yu#025.0`). Chiffres non comparables entre études (fiche `2025-yu`).

**Proposition.**
1. `forecast.py` : option `--modele persistance|lgbm|gru`. Persistance = dernière valeur (et
   persistance saisonnière à 24 h pour +6 h, *déduit*). LightGBM sur des features construites :
   lags de 10 à 60 min, moyennes glissantes 30/60/120 min, écart intérieur-extérieur, minutes depuis
   le dernier changement de chaque actionneur (`2025-cebolla-alemany#005.2`).
2. `forecast.py evaluate` : découpage temporel (bloc de test contigu final), MAE et RMSE par
   variable et par horizon, et skill score = 1 − RMSE / RMSE_persistance.
3. Horizon court (+10 min) pour la commande, en plus de +1 h et +6 h.
4. La GRU n'est déployée que si elle bat LightGBM sur le test. LightGBM tourne sur le Pi sans torch.

**Validation.** Sur `sim --jours 60` puis sur l'historique réel : tableau MAE/RMSE à trois modèles.
Test unitaire : la persistance a un skill score de 0 par construction.

**Risques.** Sur le simulateur, les modèles apprennent les équations du simulateur ; seule la
comparaison sur données réelles compte. LightGBM ajoute une dépendance ; mauvais réglage possible
des features en ligne (imputation, `2025-cebolla-alemany`, Pièges).

### L15 — Leçons de l'Autonomous Greenhouse Challenge (P2)

**Constat.** La consommation journalière est estimée en kWh, L et € ([09 §5](09-modele-gestion-serre.md#5-consommations)),
mais aucune récolte n'est enregistrée : pas d'indicateur par kg. La règle `light` complète le DLI
quel que soit le stade (`rules.py:253-309`). `co2_max: 1200` pour la tomate (`recettes.yaml:17`).

**Littérature.**
- AGC 2019 (tomate cerise) : les cinq équipes d'IA dépassent la référence humaine
  (`2020-hemming#024.1`) ; référence 33,0 MJ/kg et 27,4 L/kg, meilleure équipe 12,9 MJ/kg et
  25,0 L/kg (Table 2, `2020-hemming#135.0`) ⚠ un site, sans répétition.
- La lumière est le levier le plus fort ; pas de gain de lumière d'appoint sur plantes jeunes,
  limitées par les puits ; rentable sur plante adulte ; lampes pas en été (`2020-hemming#030.2`,
  `2020-hemming#030.3`, `2020-hemming#027.0`).
- CO₂ réalisé 600–900 ppm en milieu de saison ; les équipes étaient près de l'optimum, et en été le
  CO₂ fuit par les ouvrants (`2020-hemming#012.0`, `2020-hemming#025.2`, `2020-hemming#029.4`).
- Aucune équipe n'atteint l'autonomie complète : toutes gardent un humain dans la décision
  (`2020-hemming#032.0`) ; architecture à trois niveaux, stratégique, tactique, opérationnel
  (`2020-hemming#031.3`).
- AGC 2018 (concombre) : profit net de 24,78 €/m² pour la gagnante contre 21,18 pour la référence
  (Table 1, `2019-hemming#065.0`) ; aucune corrélation entre le nombre de capteurs ajoutés et le
  résultat (§4.3, chunk n/r) ; une panne de liaison et une irrigation presque nulle pendant
  plusieurs jours ont ruiné une équipe (§3, chunk n/r).

**Proposition.**
1. `backend/` : table `recolte` (date, plante, masse) saisie dans l'UI, et indicateurs MJ, kWh, L et
   g de nutriments par kg dans l'écran consommation.
2. `StageSetpoints` : `complement_led: false` pour les stades juvéniles (`semis`) ; la règle `light`
   suit alors la photopériode sans complément (`2020-hemming#030.2`).
3. `co2_max` : ramener le plafond utile vers 900 ppm pour la tomate (`2020-hemming#012.0`), et
   aucun dosage ouvrants ouverts quand un actionneur CO₂ existera.
4. Alarme « aucune irrigation depuis N h » quand la recette prévoit des arrosages (`2019-hemming`,
   §3).

**Validation.** Scénario `journee` avec une plante en `semis` : aucun complément LED. Test de
l'alarme d'irrigation absente. Indicateurs par kg calculés sur un historique figé avec récoltes
fictives.

**Risques.** Résultats d'une serre haute technologie avec HPS, chauffage et CO₂ ; prix fixés par
le concours ; incohérence interne sur les profits de la Table 3 de `2020-hemming` (fiche, Limites).

## 10. Agent LLM

### L16 — Agent : consignes sourcées (P1)

**Constat.** L'agent lit les règles et leurs paramètres (`get_regle`, `backend/agent/regles.yaml`)
et propose des consignes (`proposer_consigne`, `backend/agent/tools.py:618`), bornées par les
limites de sécurité (`check_limits`, `tools.py:730`). Il n'a aucune source pour juger qu'une valeur
de recette est raisonnable. Les garde-fous de [11 §4](11-agent-decision.md#4-garde-fous) ne parlent
pas de la littérature.

**Littérature.**
- Patron de plan vérifiable : DAG et contrats avec préconditions, contraintes, critères de succès
  et preuves jointes (`2601.08308`, chunk n/r).
- Sans fine-tuning, les LLM de 7 à 13 B ne distinguent presque pas les actions sûres des actions
  dangereuses (Table 1, chunk n/r) ; demander confirmation même si l'utilisateur le demande (§B.2)
  (`2401.10019`).
- Un LLM d'explication sur un contrôleur à règles a halluciné une condition absente de l'algorithme
  (`2405.14411`, chunk n/r).

**Proposition.**
1. `recettes.yaml` : bloc `sources` par recette, une entrée par grandeur, avec l'alias, le chunk et
   une force (`essai`, `revue`, `guide`, `commercial`), repris du tableau du §11.
2. Outil `get_recette` (ou extension de `get_plante`) : rend la valeur, sa source et sa force.
3. `proposer_consigne` : une valeur hors de la plage sourcée exige une justification marquée
   « hors littérature » sur la carte de proposition. La validation humaine reste la règle.
4. `backend/agent/questions.yaml` : trois questions de référence, par exemple « pourquoi l'EC de la
   laitue est-elle à 0,5 au jour 10 ? ». L'agent doit citer la source et sa force, sans inventer de
   condition.

**Validation.** `make agent-eval` : les trois questions passent avec le LLM scripté, puis avec
Claude réel. Test : `proposer_consigne` hors plage sans justification → refus.

**Risques.** Un catalogue de sources à tenir à jour avec la base. Fausse autorité : une valeur
sourcée par un guide commercial reste faible, d'où le champ `force`.

## 11. `recettes.yaml` contre littérature

Valeurs actuelles : `edge/controller/recettes.yaml` (tous les stades de la recette quand ils
diffèrent). Une valeur sourcée n'est pas un optimum validé : voir la nature de chaque source au
§1.3. « Écart » est la lecture de ce document (*déduit*). L'EC est en mS/cm, soit dS/m.

### 11.1 Tomate (`tomate-standard`)

| Grandeur | Valeur actuelle | Valeur sourcée | Écart | Action |
|---|---|---|---|---|
| T° jour | 20–25 (semis), 20–26 (croissance), 21–27 (floraison, fructification) °C | 17–27 °C (`2018-shamshiri#003.0`) ; jour 21–29,5 (Jones 2013, `2018-shamshiri#003.2`) ; 24–27 (`2020-moin-eddin-rezvani#009.2`) | dans les plages | garder ; plafond d'alerte entre 30 et 35 °C (`2018-shamshiri#003.1`) |
| T° nuit | 18–20 (semis), 16–18 (croissance), 16–19 °C | nuit 18,5–21 (`2018-shamshiri#003.2`) ; chute des fleurs sous 12,7 (`2018-shamshiri#009.0`) ; semis : nuit min 18 (`2018-shamshiri#003.2`) | 2 à 2,5 °C sous Jones en croissance et floraison | tester une nuit à 17–19 en floraison (*déduit*) ; plancher d'alerte 14 °C |
| HR | 65–80 (semis), 60–75 (croissance), 55–70 % | 50–70 %, pollinisation meilleure vers 60 (`2018-shamshiri#005.0`) ; 60–75 en gestion phytosanitaire (`2026-fanourakis#013.2`) ; < 80 contre Botrytis (`2026-fanourakis#036.0`) | +5 à +10 points au semis et en croissance | plafonner à 70–75, garder 80 au semis seulement avec le risque Botrytis actif ([L7](#l7--botrytis-et-oïdium-p1)) |
| VPD | absent | 0,5–1,2 kPa (`2018-shamshiri#006.0`) ⚠ ; 0,6–1,0 (`2026-fanourakis#035.0`) ; 1–2 à midi en été (`2017-zhang#009.2`) | absent | ajouter [0.5, 1.2] ([L4](#l4--consignes-vpd-p0)) |
| DLI | 12 (semis), 20 (croissance), 25 mol/m²/j | n/r (`2018-shamshiri#003.1` : non traité ; `2020-hemming` : n/r) | non sourcé | garder, marquer « non sourcé » ; pas de complément sur plante jeune ([L15](#l15--leçons-de-lautonomous-greenhouse-challenge-p2)) |
| CO₂ | `co2_max` 1200 ppm (croissance) | 600–900 réalisé, gain négligeable au-delà (`2020-hemming#012.0`, `2020-hemming#025.2`) ⚠ ; 700–900 pression parasitaire minimale (`2026-fanourakis#035.0`) | plafond haut sans intérêt démontré | 900 ppm (*déduit*) |
| pH | 5,8–6,3 | 5,6 (`2021-nikolaou#027.0`) ; 5,5–6,5 zone racinaire (`2018-savvas#026.2`) ; 5,5 (`1990-hochmuth#033.2`) ⚠ | +0,2 sur la cible des tables | [5.6, 6.2] ([L9](#l9--ec-de-la-tomate--apport-et-drainage-p0)) |
| EC apportée | `ec` 2,0–3,0 (croissance), 2,5–3,5 (floraison, fructification) | 2,80 → 2,30, décroissante par stade (`2021-nikolaou#027.0`) ; 2,6 / 1,6 en Europe du Nord (`2021-nikolaou#026.0`) ; 0,8 → 2,0 en Floride (`1990-hochmuth#033.2`) ⚠ | borne 3,5 sans support pour la solution ; tendance inverse | `ec_apport` 2,8 → 2,3 ([L9](#l9--ec-de-la-tomate--apport-et-drainage-p0)) |
| EC drainage | absent | 3 ± 0,8 (`2021-nikolaou#002.1`) ; écart drainage − apport ≤ ± 1,0 (`1990-hochmuth#014.1`) ⚠ | absent | `ec_drainage` [2.2, 3.8] et sonde facultative |
| T° racines | absent | 27 / 25 / 23 en été, 15 sous-optimal (`2018-shamshiri#004.0`) ; < 25 contre Fusarium (`2026-fanourakis#027.1`) | absent | [22, 25] (*déduit*, [L3](#l3--t-de-la-solution-et-des-racines-p1)) |

### 11.2 Laitue (`laitue-hydro`)

| Grandeur | Valeur actuelle | Valeur sourcée | Écart | Action |
|---|---|---|---|---|
| T° jour | 16–22 °C | 20–24 (revue citée, `2020-miller#006.1`) ; 20 ± 1 non testé (`2021-hosseini#003.0`) ; 23, consigne qui induit le tipburn (`2023-ertle#013.0`) ⚠ | 2 à 4 °C plus frais que la revue citée | n/r solide ; tester 18–22 (*déduit*) |
| T° nuit | 12–16 °C | 16 ± 2 non testé (`2021-hosseini#003.0`) ; 19 (`2023-ertle#013.0`) ⚠ ; 12,6 mesuré, « bien en dessous de l'optimal » (`2020-miller#003.0`) ⚠ | aucune source d'optimum | garder |
| HR | 50–70 % | 50–60 non testé (`2021-hosseini#003.0`) ; 75 consigne, mesuré 73–83 (`2023-ertle#013.0`) ⚠ ; HR élevée → Botrytis, mildiou (`2013-brechner#019`) ⚠ | aucune source d'optimum | garder |
| VPD | absent | 0,87 consigne, mesuré 0,50–0,75 (`2023-ertle#013.0`) ⚠ | absent | [0.5, 0.9] provisoire ([L4](#l4--consignes-vpd-p0)) |
| DLI | 14 mol/m²/j | 12–15 (`2020-miller#001.0`) ; tipburn > 13 (24 h) ou > 15 (16 h) (`2023-ertle#000.2`) ⚠ cité ; 17 avec flux d'air, 12 sans (`2013-brechner#011`, `2013-brechner#012`) ⚠ | à la limite du seuil de tipburn | `dli_cible` 12–14, `dli_max` 13 sans brassage ([L1](#l1--laitue--stades-par-âge-programme-dec-et-plafond-de-dli-p0)) |
| CO₂ | absent | 1000–1500 en serre fermée (`2013-brechner#020`) ⚠ ; 1000 (`2023-ertle#003.0`) | absent, pas d'actionneur | aucune |
| pH | 5,6–6,2 | 5,8, plage 5,6–6,0 (`2013-brechner#023`) ⚠ ; 5,6–6,0 en hydroponie (`1990-hochmuth#002.0`) ⚠ ; 6,0 ± 0,5 (`2023-ertle#002.3`) | borne haute +0,2 | [5.6, 6.0] |
| EC apportée | 1,0–1,6 (un seul stade) | 0,9, plage 0,9–1,5 (`2021-hosseini#010.0`) ; 0,25 → 2,0 par âge (`2020-miller#003.1`, `2020-miller#006.0`) ⚠ | pas de programme par âge ; borne basse trop haute avant J30 | programme par stade ([L1](#l1--laitue--stades-par-âge-programme-dec-et-plafond-de-dli-p0)) |
| EC drainage | absent | n/r | sans objet en NFT et DWC (*déduit*) | aucune |
| T° racines | absent | 18,8 (consigne 20) avec éclairage d'appoint, contre 13,2 (`2020-miller#004.3`, `2020-miller#009.0`) | absent | [18, 22] (*déduit*, [L3](#l3--t-de-la-solution-et-des-racines-p1)) |

### 11.3 Basilic (`basilic-standard`)

| Grandeur | Valeur actuelle | Valeur sourcée | Écart | Action |
|---|---|---|---|---|
| T° jour | 20–27 °C | 18–21 (`2022-johnnys#008.0`) ⚠ commercial ; T° moyenne optimale 32,6–35,5 pour la masse fraîche (`2023-walters#000.1`) ; 21 ± 1 en moyenne (`2018-walters#002.2`) | sources contradictoires | garder ; T° moyenne selon le DLI à tester (`2023-walters`) |
| T° nuit | 16–20 °C | n/r ; T° de base 10,9–12,1 (`2023-walters#001.3`, valeurs citées) | non sourcé | plancher d'alerte 12 °C (*déduit*) |
| HR | 50–70 % | n/r (toutes les fiches basilic) | non sourcé | garder, marquer « non sourcé » |
| VPD | absent | n/r | — | aucune |
| DLI | 15 mol/m²/j | optimum 11,8–13,2 pour la masse fraîche (`2023-walters#011.3`) ; > 10 pour une bonne qualité (`2018-walters#006.3`) ; 15 donne ×2,4 de masse fraîche par rapport à 7 (`2018-walters#014.1`) ; ≥ 12 (`2022-johnnys#008.0`) ⚠ | cible au-dessus de l'optimum de Walters 2023 | 12–15 ; alerte sous 10 |
| CO₂ | absent | n/r | — | aucune |
| pH | 5,8–6,5 | 6,0 (`2018-walters#002.3`) ; 5,8–6,2 (`2022-johnnys#008.0`) ⚠ | borne haute +0,3 | [5.8, 6.2] |
| EC apportée | 1,0–1,6 | 1,2, plage 0,9–1,5 (`2021-hosseini#010.0`) ; pas d'effet de 0,5 à 4,0 (`2018-walters#000.0`) ; 1,0–1,4 (`2022-johnnys#008.0`) ⚠ | recouvre | garder |
| EC drainage | absent | n/r | sans objet en NFT (*déduit*) | aucune |
| T° racines | absent | 22,1 ± 0,5, un seul niveau (`2018-walters#002.4`) | absent | [20, 24] (*déduit*) |

### 11.4 Fraise (recette absente)

| Grandeur | Valeur actuelle | Valeur sourcée | Écart | Action |
|---|---|---|---|---|
| T° jour | absent | 21–23 ; 16 ; 19–20, consignes d'essai (`2016-depardieu#006.0`, `2016-depardieu#006.3`) ; 29,5 observée (`2020-preciado-rangel#008.0`) | recette absente | [19, 23] ([L2](#l2--recette-fraise-p1)) |
| T° nuit | absent | 17 ; 12 ; 12–14 (`2016-depardieu#006.0`, `2016-depardieu#006.3`) ; 18,4 observée (`2020-preciado-rangel#008.0`) | recette absente | [12, 17] |
| HR | absent | 50 ; 60 (`2016-depardieu#006.0`, `2016-depardieu#006.3`) ; 95 % la nuit pendant 3 h par brumisation, climats secs (`2026-garcia#005.0`) ⚠ | recette absente | [50, 60], sans brumisation de nuit |
| VPD | absent | n/r | — | aucune |
| DLI | absent | 17–20 en serre (`2026-garcia#001.0`) ⚠ | recette absente | 17 |
| CO₂ | absent | n/r | — | aucune |
| pH | absent | 5,5 (`2020-preciado-rangel#011.0`) ; 5,0–6,6 observé, non optimum (`2016-depardieu#007.1`) | recette absente | [5.5, 6.2] (*déduit* pour la borne haute) |
| EC apportée | absent | 1,0–1,5 (`2016-depardieu#016.1`) ; 0,6 à la reprise, 1,2 en floraison (`2016-depardieu#007.0`) ; ≤ 1, prudence au-delà de 1,2 (`2026-garcia#000.0`) ⚠ | conflit entre sources | [1.0, 1.5], conflit à arbitrer par l'utilisateur |
| EC drainage | absent | n/r ; fraction drainée ~20 % (`2016-depardieu#007.1`), 20–30 % (`2026-garcia#000.0`) ⚠ | — | suivre la fraction drainée ([L10](#l10--irrigation-en-tension-ou-en-fraction-deau-disponible-p1)) |
| T° racines | absent | n/r | — | aucune |

## 12. Limites de ce document

- Les fiches sont des lectures critiques d'un LLM vérifiées par `bin/pdb verify`. Plusieurs
  tableaux d'articles n'ont pas de corps extrait (Shamshiri Tables 1, 2, 4 ; Savvas Table 3 ;
  workbook CEAC). Une valeur **n/r** ici peut exister dans le PDF : à relire avant de conclure.
- Les consignes de culture de la base couvrent bien la tomate, moyennement la laitue et le
  basilic, mal la fraise. Le risque maladie est sourcé pour la tomate et le concombre seulement.
- Aucune fiche ne donne d'optimum de T° jour/nuit séparé pour le basilic, ni de photopériode, de
  CO₂ ou de T° racines pour la fraise, ni de durée d'humectation pour le mildiou de la tomate :
  ce sont des gaps de la base (voir `bases/serre/gaps.md`) et des candidats pour `/paper-discover`.
- `vision/eval/temperature.py` et `decision_search.py` sont donnés comme existants par la demande
  et par une fiche, mais sont absents de `main` ([L12](#l12--vision--calibration-par-tête-et-après-int8-p0)).

## 13. Ordre proposé

1. **Sans risque, tout de suite** : L8 (on retire des actions), L4 étape 1 (`psychro.py` et son test
   sur la Table 5).
2. **Consignes P0** : L9 puis L1 (schéma de recette : `ec_apport`, `ec_drainage`, `duree_j`,
   `dli_max`), avec la migration des clés dans `recipes.py` et les attendus de scénario inchangés.
3. **Risque** : L5 (cadre `pathogenes.yaml`), puis L7 dans le même cadre ; L6 dès qu'une serre réelle
   permet des observations.
4. **Vision** : L12 avec [18 V2](18-ameliorations-logicielles.md#8-modèles-et-données-vision-v), puis
   L11.
5. **Modèles** : L14 avant tout entraînement de la GRU sur données réelles ; L13 avec
   [18 S3](18-ameliorations-logicielles.md#s3--modèle-physique-plus-réaliste-p2).
6. **Au fil de l'eau** : L2, L3, L10, L15, L16.
