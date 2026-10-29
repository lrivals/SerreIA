# Pièces imprimées de la serre

Sources des pièces décrites dans [docs/20](../docs/20-impression-3d-structures.md) : scripts
FreeCAD paramétriques (module `Part`). Toutes les cotes sont dans [params.py](params.py), les
cotes mesurées dans [mesures.toml](mesures.toml) ([MESURES.md](MESURES.md)). Les STL et STEP
sont générés dans `hardware/build/` (non versionné). Les modèles de tiers ne sont pas recopiés
(licences) : ce fichier donne leur lien.

> Statut : **tout est rendu, rien n'est imprimé**. `make hardware` (FreeCAD 1.1, snap) produit
> 37 solides valides, d'un seul tenant (sauf les 5 anneaux de jeu), tous dans le volume de la
> CC2, avec les cotes **nominales** : aucune n'est encore mesurée. Contrôle visuel des STEP à
> faire dans FreeCAD avant d'imprimer.

## Mise en route

```bash
sudo snap install freecad                # Ubuntu 24.04 : fournit freecad.cmd (apt : freecadcmd)
pip install -e '.[hardware]'             # segno : QR codes des étiquettes
make etiquettes                          # hardware/build/etiquettes.json depuis serre.yaml
make hardware                            # toutes les pièces -> hardware/build/<module>/*.step|stl
make hardware PIECES=eprouvettes         # une seule famille
python -m pytest -q tests/test_hardware.py   # le rendu est testé si FreeCAD est présent
```

`make hardware` trouve `freecadcmd` (apt) ou `freecad.cmd` (snap) ; sinon
`make hardware FREECAD=/chemin/vers/freecadcmd` (AppImage, conda-forge). Le snap n'écrit que
sous `$HOME` (son `/tmp` est privé) : garder la sortie dans `hardware/build/`.

`make hardware` refuse de rendre si une règle de la doc 20 est violée (`params.verifier` :
jeu, emmanchement, zone aveugle du JSN-SR04T, écart pH/EC, clip, volume d'impression,
disposition de la platine) et liste les cotes encore nominales.

Ordre de travail : imprimer les **éprouvettes** → reporter `jeu` et les Ø mesurés dans
`mesures.toml` → `make hardware` → ouvrir les STEP dans FreeCAD pour un contrôle visuel →
trancher (OrcaSlicer / Elegoo Slicer, profils ASA/PETG de la CC2).

## Nos pièces

| Prio | Fiche | Module | Sous-pièces (qté) | Matériau | Réglages (doc 20 §2.3) | Statut |
|---|---|---|---|---|---|---|
| P0 | — | [pieces/eprouvettes.py](pieces/eprouvettes.py) | anneaux_jeu, tranche_clip, inserts_m3, gabarit_sondes, bague_tpu_ph | PLA admis (gabarits), ASA pour la tranche de clip, TPU pour la bague | 3 parois, 20 % | rendu, non imprimé |
| P0 | A4 | [pieces/couvercle_cuve.py](pieces/couvercle_cuve.py) | platine, bouchon_trappe, bague_ph, bague_ec, bague_ds18b20 | PETG opaque, bagues TPU 95A | 4+ parois, 100 % autour des passages | rendu, non imprimé |
| P0 | D1 | [pieces/abri_stevenson.py](pieces/abri_stevenson.py) | assiette (× `abri_nb_assiettes`), toit, support | ASA blanc | 4 parois, 40 % | rendu, non imprimé |
| P0 | D2 | [pieces/boitier_noeud.py](pieces/boitier_noeud.py) | boite, couvercle, joint, bague_cable (× 2) par nœud | PETG ou ASA, joint et bagues TPU | 4 parois, 40 % | rendu, non imprimé |
| P0 | D4 | [pieces/support_camera.py](pieces/support_camera.py) | pince, boitier par caméra | ASA | 5 parois, 50 % gyroïde | rendu, non imprimé |
| P0 | D5 | [pieces/support_mire.py](pieces/support_mire.py) | cadre par caméra | ASA mat | 3 parois, 20 % | rendu, non imprimé |
| P1 | B1 | [pieces/raccord_tube.py](pieces/raccord_tube.py) | coude_90, te, croix, coin_3, te_poteau, faitage, pied | ASA (ASA-CF aux nœuds chargés) | 5–6 parois, 40–60 % gyroïde | rendu, non imprimé |
| P1 | B2 | [pieces/clip_bache.py](pieces/clip_bache.py) | clip (1 tous les 50–60 cm), patin_tpu | ASA, patin TPU | 4–6 parois, couché sur le flanc | rendu, non imprimé |
| P1 | C1 | [pieces/coulisseau.py](pieces/coulisseau.py) | coulisseau, molette (× 1 par montant) | PETG-CF / ASA-CF, ASA près du driver | 5 parois, 50 % | rendu, non imprimé |
| P1 | C2 | [pieces/crochet_faitage.py](pieces/crochet_faitage.py) | crochet, palonnier, guide_cable | ASA, palonnier PETG-CF | 5 parois, 60 % | rendu, non imprimé |
| P2 | E | [pieces/etiquette.py](pieces/etiquette.py) | etiquette_<emplacement> (depuis serre.yaml) | ASA bicolore (changement de couleur à la hauteur du relief) | 3 parois, 20 % | rendu, non imprimé |

## Modèles de tiers (non recopiés)

À télécharger depuis le site d'origine, en vérifiant la licence (souvent CC BY-NC) et en
réglant les cotes de `mesures.toml` dans leur Customizer.

| Fiche | Modèle | Usage |
|---|---|---|
| A1 | [Tour Hydroponique (Creality Cloud)](https://www.crealitycloud.com/fr/model-detail/hydro-tower-growing-tower?source=8&profileId=69260fadfcc65ef5eda0d705), [Modular Hydroponic Tower (Printables 720081)](https://www.printables.com/model/720081-modular-hydroponic-tower), [MakerWorld 2415282](https://makerworld.com/en/models/2415282-modular-hydroponic-tower-vertical-growing-system) | tours de culture |
| A2 | [Parametric Net Pot](https://www.printables.com/model/50326-parametric-net-pot-remix-with-closed-bottom), [2x3 Channel Cap](https://www.makerworld.com/en/models/1416620), [Parametric Pipe Adapter](https://www.printables.com/model/132932-parametric-pipe-adapter-openscad) | net-pots, embouts NFT |
| A3 | [5-gallon modular bucket lid](https://www.makerworld.com/en/models/1443063) | DWC |
| B3 | [DIY GREENHOUSE by KMS](https://www.printables.com/model/62627-diy-greenhouse-by-kms) | ouvrant de toit |
| D3 | [LD2450 + ESP32](https://www.printables.com/model/1514952-mmwave-sensor-ld2450-d1-mini-esp32) | support radar |
| D6 | [boîtier modulaire Pi 5](https://makerworld.com/models/1020178) | Pi 5 + Hailo |
| E | [Adaptable Plant Clip](https://printables.com/model/221320-adaptable-plant-clip-tomato-clip/comments), [Seedling support](https://www.printables.com/model/64716-seedling-support-with-auto-clip-no-wires-needed), [porte-tubes goutte-à-goutte](https://www.printables.com/model/461502-12-and-316-drip-irrigation-holders-for-drip-hoses) | culture |

Liste complète et notes : [docs/20 §4](../docs/20-impression-3d-structures.md#4-catalogue-par-besoin).

## Quincaillerie à acheter

Tout en **inox** (A2/A4), jamais zingué en serre (doc 20 §2.3).

| Article | Pièces |
|---|---|
| Inserts laiton M3 à chaud (Ø 4,0 × 5,7) | boîtier de nœud (6), éprouvette |
| Vis M3 (8–30 mm) + écrous | platine de cuve (4), boîtier (4), support caméra (2) |
| Tige filetée M3 inox + écrous | abri ventilé (3 tiges) |
| Vis M5 + écrous | raccords de tube (1 par branche), coulisseau (1 + molette), palonnier |
| Vis M2 auto-taraudeuses | caméra (4) |
| Colliers (rilsan) 5 mm, anti-UV | clips de bâche, boîtier |
| Verre ou PMMA 20 × 20 × 2 mm | fenêtre de caméra |
| Suspensions à cliquet, câble acier 3 mm + serre-câbles | lampes (doc 20 §4 C2, §7) |
| Piquets ou tige filetée M10 | pieds de structure |
