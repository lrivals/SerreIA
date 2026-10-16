# 14 — Résultats des phases 1 et 2 : analyse et pistes d'amélioration

**But** : faire le point sur les premiers résultats réels du classifieur (notebooks
`01_donnees` à `04_ablations`, exécutés sur Colab A100 les 12–13/10/2026), puis du détecteur
YOLO et du pipeline deux étages (`05_detection`, §8), en tirer ce qu'ils disent vraiment et
prioriser la suite. Les chiffres viennent des sorties enregistrées dans les
notebooks ; les définitions des métriques sont celles de [03](03-classifieur.md) §4
(`vision/eval/metrics.py`).

## 1. Résumé

- **In-domain : saturé.** F1 `sante` 0,995, F1 `classe` 0,986, `espece` 1,000 sur `test`
  (PlantVillage + CCMT). Ce jeu ne permet plus de départager des variantes.
- **Cross-domain (PlantDoc) : le vrai problème.** Rappel « anormal » 0,986, mais
  **précision 0,679** et **spécificité 0,50** : la moitié des feuilles saines sont signalées
  malades. Le critère de sortie « rappel ≥ 0,80 » est atteint par un biais vers « anormal »,
  pas par une vraie compétence. `espece` tombe à 0,46, `classe` à 0,26 (F1 macro).
- **Ablations : seules les augmentations fortes ont un effet net.** Le remplacement de fond
  (ablation C), annoncé comme le levier principal, **n'a en réalité pas été testé** (§4.2).
  Les autres écarts sont du même ordre que la variance entre deux runs identiques (≈ 0,02).
- **Calibration insuffisante** pour les seuils d'alerte de la phase 3 (ECE PlantDoc 0,13 en
  `sante`, 0,30 en `classe`).
- **Export ONNX : OK** (écart 0,00 point).

## 2. Données (`01_donnees`)

| | images |
|---|---|
| indexées | 88 135 |
| écartées (groupes contradictoires) | 715 (CCMT 612, PlantVillage 64, PlantDoc 39) |
| train / val / test | 62 993 / 7 878 / 7 884 |
| test_xdomain (PlantDoc, crops) | 8 665 |

16 espèces, 56 classes dont 3 ambiguës. Constats :

- **Déséquilibre ×36** en train : `pomme_de_terre/sain` 120 images contre `tomate/virus/tylcv`
  4 285 (compensé à l'échantillonnage par `make_sampler`, `vision/datasets/dataset.py`).
- **Seulement 29 classes sur 56 sont présentes dans PlantDoc.** Toutes les classes propres à
  CCMT (anacardier, manioc, nuisibles du maïs…) ne sont jamais évaluées hors domaine.
- **`data/backgrounds/` absent** : l'aperçu du remplacement de fond n'a pas été produit, et
  aucun entraînement n'a pu l'utiliser.

## 3. Run principal `1e8dfc9c` (`02_entrainement`, `03_evaluation`)

EfficientNet-B0, PV + CCMT, augmentations fortes, sans remplacement de fond, 28 epochs.

### 3.1 Courbe d'entraînement
La métrique de sélection (`val sante/f1_macro`) passe 0,98 dès l'epoch 2 et plafonne à
0,995 ± 0,001 à partir de l'epoch 8 ; `classe` continue de monter doucement jusqu'à ~0,987.
Le meilleur checkpoint (0,9963, epoch 25) n'est pas significativement meilleur que l'epoch
13. **La validation in-domain ne sait pas choisir un modèle qui généralise.**

### 3.2 Métriques

| jeu | n | rappel anormal | précision anormal | F1 sante | AUROC | ECE sante | acc. espece | F1 classe | top-3 classe | ECE classe |
|---|---|---|---|---|---|---|---|---|---|---|
| test / ccmt | 2 453 | 0,993 | 0,996 | 0,979 | 0,999 | 0,049 | 1,000 | 0,962 | 0,998 | 0,086 |
| test / plantvillage | 5 431 | 1,000 | 0,999 | 0,999 | 0,999 | 0,051 | 1,000 | 0,997 | 1,000 | 0,103 |
| **PlantDoc** | 8 665 | **0,986** | **0,679** | **0,733** | 0,882 | 0,130 | **0,460** | **0,264** | 0,437 | 0,301 |

Matrice `sante` sur PlantDoc :

| réel \ prédit | sain | anormal |
|---|---|---|
| sain (4 190) | 2 105 | **2 085** |
| anormal (4 475) | 63 | 4 412 |

### 3.3 Lecture
- **Biais « anormal » hors domaine.** Toute image qui ne ressemble pas à PlantVillage (fond
  naturel, flou, éclairage, filigranes) pousse vers « anormal ». L'AUROC de 0,88 montre qu'il y
  a pourtant du signal : un seuil mieux placé que l'argmax (0,5) améliorerait nettement la
  précision au prix d'un peu de rappel.
- **Grad-CAM PlantDoc** : sur les faux positifs sain → anormal, l'attention se concentre sur de
  petites taches sombres, des bords d'image, du feuillage d'arrière-plan ou des reflets, pas sur
  la feuille entière. Plusieurs crops PlantDoc portent des filigranes (« shutterstock », « RF »)
  sur lesquels le modèle s'attarde parfois.
- **La classe se rabat sur des « classes terrain » de CCMT.** La matrice `classe` PlantDoc
  montre de nombreuses images envoyées vers `manioc/maladie/bacteriose`,
  `manioc/virus/mosaique` ou `anacardier/sain/sain` — des classes qui n'existent pas dans
  PlantDoc. Le modèle a appris en partie « photo de terrain ⇒ CCMT », un raccourci de source
  plutôt que de symptôme. C'est cohérent avec l'effondrement de `espece` (0,46).
- **Confusions entre maladies voisines** : les trois maladies du maïs (cercosporiose,
  helminthosporiose, rouille) sont presque toutes prédites `helminthosporiose` ; les maladies
  foliaires de la tomate convergent vers `septoriose` et `mildiou` ; `tomate/nuisible/tetranyque`
  part vers `manioc/virus/mosaique` et `tomate/maladie/alternariose`.
- **Ligne `test / ambigu` (F1 macro 0,496)** : artefact de métrique (une seule classe `sante`
  vraie dans ce sous-ensemble, le F1 macro est divisé par deux). Seul le rappel (0,986) a un sens.

## 4. Ablations A–E (`04_ablations`)

| ablation | F1 sante (test) | rappel anormal | F1 sante | AUROC | F1 classe | top-3 classe | ECE sante |
|---|---|---|---|---|---|---|---|
| A — baseline, aug. légères, PV | 1,000 | 0,869 | 0,705 | 0,820 | 0,188 | 0,390 | 0,148 |
| B — + aug. fortes | 1,000 | 0,960 | 0,734 | 0,870 | 0,286 | 0,530 | 0,115 |
| C — + fond (*voir §4.2*) | 1,000 | 0,973 | 0,735 | 0,876 | 0,289 | 0,535 | 0,116 |
| D — + CCMT | 0,995 | 0,987 | 0,711 | 0,882 | 0,242 | 0,417 | 0,150 |
| E — ConvNeXt-Nano | 0,995 | 0,970 | 0,734 | 0,866 | 0,271 | 0,400 | 0,143 |
| *run principal (= D)* | *0,995* | *0,986* | *0,733* | *0,882* | *0,264* | *0,437* | *0,130* |

Colonnes PlantDoc sauf « F1 sante (test) ».

### 4.1 Ce qui est établi
- **A → B : seul gain franc.** Rappel +0,09, AUROC +0,05, F1 classe +0,10, top-3 +0,14,
  ECE −0,03. Les augmentations fortes sont indispensables.
- **Variance d'un run à l'autre ≈ 0,02.** D et le run principal ont la même configuration :
  F1 sante PlantDoc 0,711 contre 0,733, F1 classe 0,242 contre 0,264, top-3 0,417 contre 0,437.
  Tout écart inférieur à ~0,02–0,03 entre B, C, D et E est donc **non significatif** avec un
  seul run par variante.
- **E (ConvNeXt-Nano) n'apporte rien** par rapport à EfficientNet-B0 : on garde B0, plus
  simple à porter sur Hailo ([05](05-edge-deploiement.md)).
- **D (+ CCMT)** : rappel et AUROC légèrement en hausse, mais `classe` et top-3 en baisse —
  cohérent avec le raccourci « terrain ⇒ CCMT » du §3.3 (des classes concurrentes en plus,
  absentes de PlantDoc).
- **Comparabilité** : « F1 sante (test) » n'est pas comparable entre A–C (test PlantVillage
  seul) et D–E (test PV + CCMT).

### 4.2 Le remplacement de fond n'a pas été évalué
Le notebook 04 applique `SET = ["augment.background.enabled=false"]` **à toutes les
ablations**, et `data/backgrounds/` n'était pas disponible (`01_donnees` l'indique absent,
et il n'existe pas en local). C a donc très probablement tourné avec la même configuration que B, ce que confirment
des écarts ≤ 0,013 sur toutes les métriques. **À vérifier** dans MLflow : paramètre
`augment.background.enabled` du run `4c9cf2d5`. Tant que ce n'est pas fait, l'hypothèse
centrale de [03](03-classifieur.md) §3.2 reste ouverte, et D et E (qui héritent de C) sont
eux aussi sans remplacement de fond.

## 5. Critères de sortie et calibration

Les critères de [03](03-classifieur.md) §6 sont tous verts pour les cinq variantes, mais ils
ne mesurent pas ce qui compte :
- le **rappel seul** se maximise en prédisant « anormal » partout — ce que fait presque le
  modèle hors domaine (spécificité 0,50). Il faut un critère couplé (précision ou spécificité).
- **ECE in-domain de 0,05 pour ~99,5 % d'exactitude** : le modèle est sous-confiant (confiance
  moyenne ≈ 0,95), effet attendu du `label_smoothing: 0.1`. Hors domaine, l'ECE monte à 0,13
  (`sante`) et 0,30 (`classe`). Les seuils d'alerte de la phase 3, qui s'appuient sur les
  confiances, ne peuvent pas être réglés en l'état.

## 6. Limites de cette analyse
- Un seul run par variante (plus un réplicat involontaire de D) : pas d'intervalle de confiance.
- PlantDoc est connu pour du bruit d'étiquetage et des crops de faible résolution ; une partie
  des erreurs `classe` vient du jeu lui-même. Il reste néanmoins le meilleur proxy disponible
  du réel avant d'avoir des images de la serre.
- Les métriques à seuil (rappel, précision) sont prises à l'argmax ; aucun point de
  fonctionnement n'a été optimisé.

## 7. Pistes d'amélioration (par priorité)

### P0 — avant toute nouvelle ablation
1. **Tester réellement le remplacement de fond.** Constituer `data/backgrounds/` (photos de la
   serre, à défaut fonds de feuillage/terreau/plastique), `tools/get_datasets.sh push
   backgrounds`, puis relancer C, D et E **sans** le `SET` global. Dans le notebook 04, ne plus
   désactiver le fond par défaut : si `backgrounds` manque, sauter C–E avec un message plutôt
   que les lancer sous un faux nom.
2. **Durcir les critères de sortie** ([03](03-classifieur.md) §6, `CRITERIA` dans
   `vision/eval/ablation_report.py`) : garder rappel ≥ 0,80 mais exiger aussi une
   **précision « anormal » ≥ 0,80** (ou spécificité ≥ 0,70) et une AUROC ≥ 0,90 sur PlantDoc.
   Ajouter la précision et la spécificité au tableau `reports/phase1.md`.
3. **Choisir le seuil `sante`** au lieu de l'argmax : rapporter la spécificité à rappel fixé
   (0,90 / 0,95) et le seuil correspondant. L'AUROC de 0,88 laisse une marge réelle.

### P1 — fiabiliser la mesure
4. **Calibration** : temperature scaling post-hoc par tête, ajusté sur `val` (une ligne dans
   `run_eval`, température stockée dans le checkpoint et l'export ONNX) ; rapporter l'ECE avant
   et après. Essayer `label_smoothing` 0,05 ou 0.
5. **Plusieurs seeds** (3) pour B et pour la variante retenue, ou à défaut un intervalle de
   confiance bootstrap sur PlantDoc dans `cross_domain_eval.py`. Afficher « moyenne ± écart ».
6. **Sélection du checkpoint hors domaine** : `val sante/f1_macro` est saturé. Sélectionner
   sur un petit jeu « terrain » distinct de `test_xdomain` (une fraction de PlantDoc mise de côté,
   ou `val` CCMT seul), ou simplement réduire à ~15 epochs.
7. **Rapport** : masquer le F1 macro de la ligne `ambigu` (garder rappel et `espece`) ;
   marquer la non-comparabilité in-domain entre A–C et D–E.

### P2 — améliorer la généralisation
8. **Exploiter l'espèce connue.** En serre, l'espèce cultivée à chaque emplacement est connue
   ([09](09-modele-gestion-serre.md)). Restreindre les logits `classe` aux classes de l'espèce
   déclarée supprime d'un coup les fuites vers manioc/anacardier. À mesurer dès maintenant :
   F1 `classe` PlantDoc « avec espèce oracle ».
9. **Casser le raccourci de source** : équilibrer les sources dans le sampler (pas seulement
   les classes), mixup/cutmix entre sources, ou ajouter un adversaire de domaine (gradient
   reversal sur la source) ; vérifier l'effet sur la matrice `classe` PlantDoc.
10. **Recadrage sur la feuille** : les faux positifs regardent le fond et les bords. Entraîner
    et inférer sur des crops centrés sur la feuille (masques PlantVillage, puis détecteur de la
    phase 2, [04](04-detection-yolo.md)) réduit ce qui reste de fond.
11. **Résolution** 288 px et TTA (flip) pour les petites lésions ; à valider contre le budget
    Hailo.
12. **Données réelles** : quelques centaines d'images de la serre étiquetées (apprentissage
    actif, [07](07-roadmap.md)) valent plus que toute ablation supplémentaire — elles servent à
    la fois de val de sélection (point 6) et de test final.

## 8. Phase 2 — détection YOLO et deux étages (`05_detection`)

Run YOLO `a604f044` (YOLOv8n COCO, 640 px, 100 epochs, teinte LED 30 %, 30 min sur A100),
classe unique `feuille`, jeu `data/yolo/` de [04](04-detection-yolo.md) §2 ; deux étages
évalués sur PlantDoc TEST avec le classifieur `96f8b511`.

### 8.1 Résumé
- **Critère de la feuille de route atteint** ([07](07-roadmap.md) : mAP@0.5 ≥ 0,6) : 0,888 en
  val, 0,956 en test. Mais le chiffre test est **flatté** (§8.3), et le second critère
  (« pipeline de bout en bout sur des photos réelles ») n'est pas évaluable sans images de la serre.
- **Le détecteur n'est pas le maillon faible** : rappel feuille 0,92 en bout de chaîne.
- **Le biais « anormal » de la phase 1 se propage à l'image** : 42 % des images saines sont
  signalées « plante anormale », pour 98 % de rappel sur les malades.
- **Le classifieur évalué n'est pas le bon** : `96f8b511` est l'ablation E (ConvNeXt-Nano),
  choisie parce que c'est le `best.pt` le plus récent, pas le run principal EfficientNet-B0
  `1e8dfc9c` retenu pour Hailo (§4.1).

### 8.2 Détecteur

| jeu | images | boîtes | P | R | mAP@0.5 | mAP@0.5:0.95 |
|---|---|---|---|---|---|---|
| val (PlantDoc + PV) | 420 | 949 | 0,797 | 0,834 | 0,888 | 0,675 |
| test (PlantDoc + PV) | 422 | 637 | 0,891 | 0,901 | 0,956 | 0,778 |

Inférence 3,2 ms/image (A100, fusionné, 3,1 M paramètres, 8,6 GFLOPs).

- **Courbes** : mAP@0.5 plafonne vers l'epoch 60–70 (≈ 0,89), mAP@0.5:0.95 monte encore
  doucement jusqu'à 0,67. Les pertes train **et val** baissent toujours à l'epoch 100 : pas de
  surapprentissage, un peu de marge avec plus d'epochs ou un modèle plus gros. La marche à
  l'epoch 90 est `close_mosaic` (pertes −0,05, rappel val −0,03, mAP inchangée).
- **PR test** : précision ≈ 1 jusqu'à un rappel de 0,8, puis chute franche au-delà de 0,95 —
  les dernières feuilles manquées sont des cas difficiles (petites, occultées, empilées).

### 8.3 Lecture
- **Test plus facile que val, et pas pour de bonnes raisons.** PlantDoc TEST a **1,9 boîte par
  image** contre 3,3 en val et 3,6 en train : moins de scènes denses, des feuilles plus grandes.
  S'y ajoutent les 185 images PlantVillage (une feuille sur fond gris, boîte tirée du masque),
  quasi triviales, qui pèsent 29 % des boîtes test. Le +0,07 de mAP val → test vient de là, pas
  d'une généralisation. Le chiffre à suivre est la mAP **PlantDoc seule**, non rapportée.
- **La précision mesurée est sous-estimée.** En bout de chaîne, précision feuille 0,71 pour
  rappel 0,92 (seuil 0,25, IoU 0,5). Sur la planche d'exemples, beaucoup de « faux positifs »
  sont de vraies feuilles **non annotées** dans PlantDoc (`e33155.jpg`, `prunsero_leaf2.jpg`) :
  PlantDoc n'annote que les feuilles porteuses du label, pas toutes les feuilles. Inversement,
  le détecteur apprend en partie à **ignorer** des feuilles visibles, ce qui sera pénalisant en
  serre où chaque image contient des dizaines de feuilles.
- **Domaine encore loin de la serre** : feuilles isolées sur fond blanc, photos de banques
  d'images (filigranes « alamy », « shutterstock »), diapositives (`Bacterial Spot and
  Speck`). Aucune vue de canopée dense ni sous LED réelle.

### 8.4 Deux étages sur PlantDoc TEST

| métrique | valeur |
|---|---|
| images (anormales / saines) | 236 (146 / 90) |
| détection : rappel / précision feuille | 0,918 / 0,708 |
| feuilles appariées : exactitude `sante` | 0,855 |
| feuilles appariées : rappel anormal | 0,963 |
| **image : rappel « plante anormale »** | **0,979** |
| **image : faux positifs sur images saines** | **0,422** |

- **Exactitude `sante` meilleure sur crops détectés (0,855) que sur crops de vérité en phase 1
  (≈ 0,75 pour E sur tout PlantDoc).** Trois explications possibles, non séparées : la marge de
  10 % autour de la boîte (plus de contexte), le sous-ensemble TEST (une partie de PlantDoc
  seulement), et un biais de sélection (seules les feuilles bien détectées sont appariées). À
  isoler avant d'en conclure quoi que ce soit (§8.5, point 3).
- **Agrégation par le max** : une image est « anormale » dès qu'**une** feuille dépasse
  p = 0,5. Avec un classifieur à spécificité ~0,5 et plusieurs feuilles par image, le taux de
  fausses alertes croît mécaniquement avec le nombre de feuilles détectées ; il serait encore
  plus haut en serre. Sur la planche, les fausses alertes viennent de feuilles saines à reflets,
  nervures marquées ou taches d'ombre (`P1200665`, `blueberry-leaves-normal`), comme les faux
  positifs Grad-CAM de la phase 1 (§3.3).
- **Pour la phase 3, 42 % de fausses alertes est inutilisable** : à une capture toutes les 10 min
  par caméra (`periode_s` de `edge/config.yaml`), cela fait des dizaines d'alertes par jour sur
  une serre saine.

### 8.5 Pistes d'amélioration
Plan détaillé dans [15](15-ameliorations-detection.md). En bref :
- **P0, mesurer juste** : évaluer le classifieur retenu `1e8dfc9c`, mAP PlantDoc seule,
  boîtes de vérité pour séparer détecteur et classifieur, courbe faux positifs / rappel image.
- **P1, décision image** : une seule règle hors ligne et sur le Pi (aujourd'hui 0,5 sur une
  capture contre 0,6 sur 3 captures dans `edge/controller/vision_alerts.py`), agrégation des
  feuilles, crops inexploitables écartés, calibration.
- **P2, données et modèle** : compléter les annotations PlantDoc, images de la serre, moins de
  PlantVillage ; ensuite seulement `yolov8s` / résolution plus haute.
