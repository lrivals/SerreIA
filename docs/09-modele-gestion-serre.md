# 09 — Modèle de gestion de serre

Ce document décrit la **serre physique** telle que le logiciel la connaît : zones, emplacements, plantes, contenants, mode de culture, capteurs, actionneurs, caméras, recettes et consommations.
C'est la référence commune au contrôleur ([06](06-capteurs-controle.md)), au journal de décisions ([10](10-decisions-tracabilite.md)), à l'agent ([11](11-agent-decision.md)) et à l'interface ([12](12-interface-utilisateur.md)).

> Statut : **conception**. Aucun code n'existe encore ; les noms de tables et de champs ci-dessous sont la cible de `backend/db/`.

## 1. Hiérarchie

```
Serre ─┬─ Zone z1 ─┬─ Emplacement A1 ── Plante (tomate « Cœur de bœuf », floraison)
       │           ├─ Emplacement A2 ── Plante (fraisier, croissance)
       │           ├─ Emplacement B1 ── (vide)
       │           ├─ Capteurs  : SHT45, SCD41, BH1750           (air de la zone)
       │           ├─ Actionneurs : ventilo, led, brumisateur, chauffage
       │           └─ Caméras : cam-z1-a (voit A1, A2, B1)
       └─ Zone z2 (hydroponie NFT) ─┬─ Emplacements G1…G12
                                    ├─ Cuve ── capteurs pH, EC, temp_eau, niveau_cuve
                                    └─ Actionneurs : pompe_nutri, pompe_ph_down, led
```

| Entité | Rôle | Identifiant |
|---|---|---|
| **Serre** | conteneur racine (nom, localisation pour la météo, fuseau horaire) | `serre_id` |
| **Zone** | volume d'air ou circuit d'eau commun ; **unité de contrôle** et segment `<zone>` des topics MQTT | `z1`, `z2`… (regex `^z\d+$` de `common/mqtt/topics.py`) |
| **Emplacement** | position physique d'une plante dans la zone : grille `(rangée, colonne)` ou étagère/niveau | `z1-A1` (zone + code) |
| **Plante** | individu cultivé, rattaché à un emplacement à un instant donné | `plante_id` (UUID) |
| **Cuve** (optionnelle) | réservoir de solution nutritive partagé par une ou plusieurs zones hydro | `cuve_id` |

Règles :
- une zone = un ensemble d'actionneurs qui agissent ensemble (une ventilation, une rampe LED) ; si deux parties de la serre ont des besoins différents, ce sont deux zones ;
- un emplacement accueille **au plus une plante active** ; l'historique (plantes précédentes, rotations) est conservé ;
- déplacer une plante = clôturer son affectation à l'ancien emplacement et en ouvrir une nouvelle (les décisions passées restent liées à l'ancien emplacement).

## 2. Plante

| Champ | Type | Exemple | Remarque |
|---|---|---|---|
| `espece` | clé de `vision/datasets/taxonomy.yaml` | `tomate` | permet de comparer la classification vision à l'espèce déclarée |
| `variete` | texte libre | `Cœur de bœuf` | |
| `date_semis`, `date_plantation` | date | | |
| `stade` | `semis \| croissance \| floraison \| fructification \| recolte` | `floraison` | choisit la ligne de **recette** (§6) |
| `recette_id` | référence | `tomate-standard` | par défaut la recette de l'espèce |
| `emplacement_id` | référence | `z1-A1` | affectation courante |
| `etat_sante` | `sain \| a_surveiller \| malade \| isolee \| retiree` | | mis à jour par les décisions ([10](10-decisions-tracabilite.md)) ou à la main |
| `notes`, `photos` | | | photos manuelles en plus des captures caméra |

Espèces actuellement reconnues par le classifieur : `anacardier, cerisier, courge, fraisier, framboisier, mais, manioc, myrtillier, oranger, pecher, poivron, pomme_de_terre, pommier, soja, tomate, vigne`.
Une plante d'une espèce **hors taxonomie** (salade, basilic… avant l'ajout de nos propres images) est acceptée : ses classifications vision sont alors affichées mais **ne déclenchent aucune décision automatique** (seul `score_anomalie` est exploité, en alerte simple).

## 3. Contenant et mode de culture

### Pot / contenant
| Champ | Exemple |
|---|---|
| `type` | `pot`, `jardiniere`, `sac_de_culture`, `godet`, `canal_NFT`, `bac_DWC`, `pleine_terre` |
| `volume_l` | `11` |
| `materiau` | `plastique`, `terre_cuite`, `geotextile` |
| `drainage` | booléen |

### Mode de culture
Il est porté par l'**emplacement** (une zone peut mélanger terre et substrat, mais une zone hydro partage sa cuve).

| `mode_culture` | Substrat | Mesures pertinentes | Actionneurs typiques |
|---|---|---|---|
| `terre` | terreau, pleine terre | humidité substrat (capacitif), T°/HR air | `pompe_nutri` (arrosage goutte-à-goutte) |
| `substrat` | coco, laine de roche, perlite | humidité substrat, EC du drainage (option) | arrosage fertirrigué |
| `hydro_nft` | aucun (film nutritif) | pH, EC, `temp_eau`, `niveau_cuve` | `pompe_nutri` (continue ou cyclique), `pompe_ph_down` |
| `hydro_dwc` | aucun (racines immergées) | pH, EC, `temp_eau`, `niveau_cuve`, O₂ dissous (option) | bulleur, `pompe_ph_down` |
| `ebb_flow` | billes d'argile | pH, EC, `niveau_cuve` | `pompe_nutri` (cycles marée) |
| `aeroponie` | aucun | pH, EC, pression | pompe haute pression (cycles courts) |

Le mode de culture sert à :
- **filtrer** dans l'interface les capteurs et actionneurs proposés pour un emplacement ;
- **choisir les règles** actives du contrôleur (pas de dosage pH sur un emplacement en terre, pas d'arrosage cyclique sur du DWC) ;
- **contrôler la cohérence** : un emplacement `hydro_*` sans capteur pH/EC dans sa cuve déclenche un avertissement de configuration.

> L'humidité substrat n'existe pas encore dans `SensorType` ; elle est à ajouter au contrat (`humidite_sol`) quand le capteur capacitif sera câblé.

## 4. Équipements

### Capteur
| Champ | Exemple | Remarque |
|---|---|---|
| `id` | `sht45-z1` | |
| `modele` | `SHT45`, `SCD41`, `BH1750`, `EZO-pH`, `EZO-EC`, `DS18B20`, `JSN-SR04T` | BOM de [06 §1](06-capteurs-controle.md#1-capteurs-bom-indicative) |
| `mesures` | liste de `SensorType` (`temperature`, `humidite`…) | un SCD41 publie `co2`, `temperature`, `humidite` |
| `noeud` | `esp32-01` | champ `noeud` du message `SensorReading` |
| `zone`, `cuve_id` | `z1` | |
| `emplacements_couverts` | `[z1-A1, z1-A2]` ou `*` (toute la zone) | sert à rattacher une mesure à une plante |
| `etalonnage` | date, méthode, coefficients | rappel dans l'UI (pH : mensuel) |
| `plage_physique` | min / max | cohérent avec la validation `qualite` du firmware |

### Actionneur
| Champ | Exemple | Remarque |
|---|---|---|
| `id` / `type` | `led-z1` / `Actuator.LED` | type ∈ `Actuator` de `common/mqtt/topics.py` |
| `noeud`, `zone` | `esp32-03`, `z1` | |
| `puissance_w` | `240` | puissance nominale à 100 % ; base du calcul d'énergie |
| `debit_l_h` | `120` | pompes uniquement |
| `ppfd_max` | `450` µmol/m²/s au niveau de la canopée | LED uniquement ; base de l'estimation DLI |
| `duree_max_s` | `60` | pompes ; doit être ≤ la limite firmware |
| `commande` | `on_off \| pwm` | |

### Caméra
| Champ | Exemple |
|---|---|
| `id` | `cam-z1-a` (segment `<camera_id>` du topic vision) |
| `zone` | `z1` |
| `emplacements_visibles` | `[z1-A1, z1-A2, z1-B1]` |
| `regions` | polygone ou bbox normalisée par emplacement dans l'image |

Les `regions` permettent de rattacher un résultat vision à un emplacement :
- **phase 1** (classifieur, `bbox: null`) : on classe une tuile par emplacement, découpée selon `regions` → un `VisionResult` par tuile ;
- **phase 2** (YOLO) : le centre de chaque `bbox` détectée est affecté à la région qui le contient.

## 5. Consommations

Aucune mesure électrique dédiée n'est prévue au départ : la consommation est **estimée** à partir des états d'actionneurs (`serre/<zone>/etat/<actionneur>`, retain) et des caractéristiques déclarées. Un wattmètre (ex. prise Shelly, PZEM-004T) pourra ensuite remplacer l'estimation.

| Grandeur | Calcul | Granularité |
|---|---|---|
| **Énergie** (kWh) | Σ `puissance_w` × facteur d'état (`on` = 1, `pwm` = `valeur`/100, `off` = 0) × durée de l'état | actionneur, zone, jour |
| **Eau** (L) | Σ `debit_l_h` × durée `on` des pompes ; recoupé avec la variation de `niveau_cuve` | pompe, cuve, jour |
| **Lumière** (DLI, mol/m²/j) | lumière artificielle : `ppfd_max` × `valeur`/100 × durée ; lumière naturelle : lux × 0,0185 (facteur indicatif lumière du jour, à remplacer par un capteur PAR) | zone, jour |
| **Intrants** (mL) | volume par impulsion × nombre d'impulsions de `pompe_ph_down` et des pompes nutriments | cuve, jour |
| **Coût** (€) | kWh × tarif déclaré dans la serre (option heures pleines / creuses) | serre, mois |

L'écart entre DLI obtenu et DLI cible de la recette alimente la règle de complément lumineux ([06 §4](06-capteurs-controle.md#niveau-1--règles-et-régulateurs-rulespy)).

## 6. Recettes de culture

Une recette fixe les consignes **par espèce et par stade**. Elle formalise `edge/controller/recettes.yaml` annoncé en doc 06.

```yaml
# edge/controller/recettes.yaml (exemple)
tomate-standard:
  espece: tomate
  stades:
    croissance:
      temperature: {jour: [20, 26], nuit: [16, 18]}
      humidite: [60, 75]
      co2_max: 1200
      photoperiode_h: 16
      dli_cible: 20
      ph: [5.8, 6.3]        # hydro uniquement
      ec: [2.0, 3.0]        # mS/cm, hydro uniquement
    floraison:
      temperature: {jour: [21, 27], nuit: [16, 19]}
      humidite: [55, 70]
      photoperiode_h: 14
      dli_cible: 25
      ph: [5.8, 6.3]
      ec: [2.5, 3.5]
```

Quand une zone contient plusieurs plantes de recettes différentes, la **consigne de zone** est l'intersection des plages ; si elle est vide, l'UI le signale (« plantes incompatibles dans z1 ») et la recette de la plante désignée *prioritaire* de la zone l'emporte.

## 7. Persistance

PostgreSQL + extension TimescaleDB (serveur, cf. [01](01-architecture.md)). Tables de configuration classiques, séries temporelles en hypertables.

```
serre 1─┬─* zone 1─┬─* emplacement 1──* affectation *──1 plante *──1 recette
        │          │        │ *
        │          │        └──1 contenant
        │          ├─* capteur  ─* capteur_emplacement *─ emplacement
        │          ├─* actionneur
        │          └─* camera   ─* camera_region *─ emplacement
        └─* cuve 1─* zone (zones hydro)

Hypertables (ts, zone, …) :
  mesure(ts, zone, capteur_id, type, valeur, unite, qualite)
  vision_resultat(ts, zone, camera, image_id, emplacement_id, modele, espece, espece_conf,
                  sante, sante_conf, classe, classe_conf, bbox, score_anomalie, surface_verte_px)
  etat_actionneur(ts, zone, actionneur_id, action, valeur)
  decision(...)  action(...)          → schémas détaillés en doc 10
  consommation_jour(jour, zone, actionneur_id, kwh, litres, dli)   (agrégat continu)
```

L'ingestion (`backend/ingestion/`) s'abonne aux `SUBSCRIPTIONS` de `common/mqtt/topics.py`, valide avec `decode` et écrit dans ces tables.

## 8. Configuration exportée vers le contrôleur

Le Pi doit rester autonome ([01 §1](01-architecture.md#principes)) : il ne lit pas la base du serveur en continu. L'interface **publie une configuration versionnée** de la serre :

```
UI ──► API ──► serre_config_v<N>.yaml ──► Pi : edge/config/serre.yaml (copie locale)
                                           └─ controller recharge à chaud, journalise la version
```

Contenu : zones, emplacements et plantes actives (espèce, stade, recette), capteurs et actionneurs (avec `duree_max_s`, `puissance_w`), régions caméra, recettes.
Chaque décision enregistre la `config_version` utilisée, ce qui rend les décisions rejouables.
Transport : topic retain `serre/config` (proposition, hors contrat actuel) ou simple copie `rsync` dans un premier temps.
