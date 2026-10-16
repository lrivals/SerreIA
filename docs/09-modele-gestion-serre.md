# 09 — Modèle de gestion de serre

Ce document décrit la **serre physique** telle que le logiciel la connaît : zones, emplacements, plantes, contenants, mode de culture, capteurs, actionneurs, caméras, recettes et consommations.
C'est la référence commune au contrôleur ([06](06-capteurs-controle.md)), au journal de décisions ([10](10-decisions-tracabilite.md)), à l'agent ([11](11-agent-decision.md)) et à l'interface ([12](12-interface-utilisateur.md)).

> Statut : **modèle implémenté hors UI** : tables, seed depuis `serre.yaml` (zones, emplacements, contenants, plantes, cuves, capteurs, actionneurs, caméras et régions), contrôles de cohérence (§2, §3), ingestion MQTT et consommation avec intrants (§5, §7), export versionné de la configuration vers le Pi (§8). Le constructeur de serre (UI, API) et les migrations Alembic arrivent avec G2.

## 1. Hiérarchie

```
Serre ─┬─ Zone z1 ─┬─ Emplacement A1 ── Plante (tomate « Cœur de bœuf », floraison)
       │           ├─ Emplacement A2 ── Plante (fraisier, croissance)
       │           ├─ Emplacement B1 ── (vide)
       │           ├─ Capteurs  : SHT41, BMP280, GY-302, SCD41, LD2450   (air de la zone)
       │           ├─ Sondes sol : capacitives sur A1, A2        (une par emplacement en terre)
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

Implémentation : `Greenhouse.vision_auto(camera)` (`edge/controller/config.py`) est faux pour une caméra déclarée dont toutes les plantes visibles sont hors taxonomie (`vision/datasets/taxonomy.yaml`). Ses résultats ne comptent pas dans la confirmation vision de la règle mildiou (`risk.confirmed`), et `vision_alerts` les lisse sur `score_anomalie` au lieu de la santé du classifieur, sans jamais dépasser le niveau `warning`. Une caméra non déclarée garde le comportement par défaut.

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

Implémentation : `edge/controller/coherence.py` produit des **avertissements** (la configuration reste chargée), journalisés au chargement par le contrôleur, le seed et l'export (`Greenhouse.warnings`) : emplacement hydro sans `ph`/`ec` déclaré dans sa zone ou sa cuve, pompe doseuse dans une zone sans emplacement hydro, caméra qui voit plusieurs emplacements sans région, espèce hors taxonomie. Côté règles, `hydro.circulation` ne tourne pas sur une zone dont les emplacements hydro sont tous en `hydro_dwc`, et `sol.arrosage` ne concerne que les zones sans emplacement hydro (la `pompe_nutri` d'une zone hydro est celle de la solution). Les erreurs bloquantes (emplacement d'une autre zone dans une caméra ou un capteur, région hors de [0, 1], cuve inconnue, deux capteurs sur le même canal) sont refusées par `SerreCfg`.

> Les sondes capacitives d'humidité du sol publient `humidite_sol` avec le champ `emplacement` (une mesure par sonde) ; `pression` et `presence` sont aussi dans le contrat ([06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc)).

## 4. Équipements

### Capteur
| Champ | Exemple | Remarque |
|---|---|---|
| `id` | `sht41-z1` | |
| `modele` | `SHT41`, `BMP280`, `GY-302`, `HLK-LD2450`, `capacitif-sol`, `SCD41`, `EZO-pH`, `EZO-EC`, `DS18B20`, `JSN-SR04T` | BOM de [06 §1.2](06-capteurs-controle.md#12-capteurs-bom) |
| `mesures` | liste de `SensorType` (`temperature`, `humidite`…) | un SHT41 publie `temperature`, `humidite` ; un SCD41 publie `co2`, `temperature`, `humidite` (deux mesures du même type sur un même nœud partagent un canal : n'en déclarer qu'une) |
| `noeud` | `esp32-01` | champ `noeud` du message `SensorReading` |
| `zone`, `cuve` | `z1`, `true` | `cuve: true` : le capteur mesure la cuve de sa zone |
| `emplacement` | `z1-A1` | sonde de sol : champ `emplacement` de ses mesures |
| `emplacements_couverts` | `[z1-A1, z1-A2]` ou `*` (toute la zone, par défaut) | sert à rattacher une mesure à une plante |
| `etalonnage` | date, méthode, coefficients | rappel dans l'UI (pH : mensuel) |
| `plage` | min / max | cohérent avec la validation `qualite` du firmware |

En base, un capteur déclaré donne une ligne `capteur` **par canal** `<noeud>-<mesure>[-<emplacement>]` (l'id que l'ingestion reconnaît), regroupées par `materiel` (l'`id` déclaré), et une ligne `capteur_emplacement` par emplacement couvert.

### Actionneur
| Champ | Exemple | Remarque |
|---|---|---|
| `id` / `type` | `led-z1` / `Actuator.LED` | type ∈ `Actuator` de `common/mqtt/topics.py` |
| `noeud`, `zone` | `esp32-04`, `z1` | |
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
| `regions` | bbox normalisée `[x, y, w, h]` par emplacement dans l'image (polygone : plus tard) |

Les `regions` permettent de rattacher un résultat vision à un emplacement :
- **phase 1** (classifieur, `bbox: null`) : on classe une tuile par emplacement, découpée selon `regions` → un `VisionResult` par tuile ;
- **phase 2** (YOLO) : le centre de chaque `bbox` détectée est affecté à la région qui le contient.

Si aucune région ne convient (image entière, centre hors des régions), le résultat va au seul emplacement visible, s'il n'y en a qu'un ; sinon il reste sans emplacement. Le découpage en tuiles sur le Pi utilise encore les ROI en pixels de `edge/config.yaml` (`plantes[].roi`) ; ces ROI seront générées à partir des `regions` avec l'export G2.

## 5. Consommations

Aucune mesure électrique dédiée n'est prévue au départ : la consommation est **estimée** à partir des états d'actionneurs (`serre/<zone>/etat/<actionneur>`, retain) et des caractéristiques déclarées. Un wattmètre (ex. prise Shelly, PZEM-004T) pourra ensuite remplacer l'estimation.

| Grandeur | Calcul | Granularité |
|---|---|---|
| **Énergie** (kWh) | Σ `puissance_w` × facteur d'état (`on` = 1, `pwm` = `valeur`/100, `off` = 0) × durée de l'état | actionneur, zone, jour |
| **Eau** (L) | Σ `debit_l_h` × durée `on` des pompes ; recoupé avec la variation de `niveau_cuve` | pompe, cuve, jour |
| **Lumière** (DLI, mol/m²/j) | lumière artificielle : `ppfd_max` × `valeur`/100 × durée ; lumière naturelle : lux × 0,0185 (facteur indicatif lumière du jour, à remplacer par un capteur PAR) | zone, jour |
| **Intrants** (mL) | `debit_ml_min` × durée `on` de `pompe_ph_down`, `pompe_nutri_a`, `pompe_nutri_b` (= volume par impulsion × nombre d'impulsions) | pompe, zone (cuve), jour |
| **Coût** (€) | kWh × tarif déclaré dans la serre (option heures pleines / creuses) | serre, mois |

Implémentation (`backend/consumption.py`, table `consommation_jour` par actionneur et `lumiere_jour` par zone, jours **locaux** du fuseau de la serre) :
- un état est supposé tenir jusqu'au suivant (topic `etat/` en retain) ; avant le premier état reçu, rien n'est compté ; la journée en cours est comptée jusqu'à l'instant du calcul ;
- `puissance_w`, `debit_l_h`, `ppfd_max` viennent de `serre.yaml` (actionneurs) et `tarif_kwh` de la serre ;
- le lux mesuré **inclut** déjà les LED : `dli_total` = intégrale de `lux × lux_vers_ppfd` (trapèzes, trous > 15 min ignorés, champ `couverture` = part de la journée couverte), `dli_led` = estimation à partir des états LED, `dli_naturel` = différence ;
- intrants (mL) : `debit_ml_min` des pompes doseuses (pompe péristaltique, à mesurer une fois au verre doseur), colonne `ml` ; ils ne comptent pas dans les `litres` d'eau.

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

Hypertables (ts dans la clé primaire, pas de clé étrangère : l'ingestion ne rejette jamais un message
parce que la configuration est en retard) :
  mesure(ts, capteur_id, zone, type, noeud, emplacement, valeur, unite, qualite)
  vision_resultat(ts, image_id, idx, zone, camera, emplacement_id, modele, espece, espece_conf,
                  sante, sante_conf, classe, classe_conf, bbox, score_anomalie, surface_verte_px)
  etat_actionneur(ts, zone, actionneur, actionneur_id, action, valeur)
  commande(ts, zone, actionneur, action, valeur, duree_s, source, raison, decision_id, camera)
  alerte(ts, id, zone, niveau, message, source, acquittee)
  noeud_status(ts, noeud, status)              (ts = heure de réception : le payload n'en a pas)

Tables classiques :
  decision(id, ts, zone, …, preuves, actions, ordres, statut, expire)   upsert par id (doc 10 §2)
  action(id, decision_id, zone, type, cible, label, commande, resultat, ts_debut, ts_fin)
                                                        dérivée des décisions et commandes (doc 10 §3)
  consommation_jour(jour, actionneur_id, zone, type, duree_on_s, kwh, litres, ml, dli, cout)
  lumiere_jour(jour, zone, dli_total, dli_led, dli_naturel, couverture)
  config_export(version, ts, sha256, contenu)          versions exportées vers le Pi (§8)
```

Code : `backend/db/models.py` (SQLAlchemy 2, types portables : les tests tournent sur SQLite), `backend/db/timescale.sql` (hypertables, appliqué par `init_db` sur PostgreSQL seulement), `backend/db/seed.py` (`python -m backend.db.seed` : charge `serre.yaml` et les recettes, idempotent ; un déplacement de plante clôt l'affectation). Les champs du contrôleur sans colonne dédiée sont stockés en JSON (`serre.parametres` : hystérésis, sécurité, risque, lumière, prévision ; `actionneur.parametres` : `duree_s`, `impulsion_s`, `melange_s`, `delai_min_s`, `marche_min_s` ; `zone.presence_autorisee`), si bien que l'export (§8) reconstruit `serre.yaml` à partir de la base seule. Pas encore d'Alembic : `init_db` crée les tables manquantes mais **ne modifie pas une table existante**. Après une évolution du schéma, une base de développement se recrée : `docker compose -f backend/docker-compose.yml --profile broker down -v && make stack-up db-init`. Les migrations arriveront avec G2.

Les capteurs déclarés dans `serre.yaml` (§4) sont créés par le seed. Un canal inconnu (capteur non déclaré) est créé par l'ingestion au premier message (`<noeud>-<type>[-<emplacement>]`, sans `materiel`) et relié à son emplacement (sondes de sol) ; il n'apparaît pas dans l'export tant qu'il n'est pas déclaré.

L'ingestion (`backend/ingestion/`, `python -m backend.ingestion`) s'abonne aux `SUBSCRIPTIONS` de `common/mqtt/topics.py`, valide avec `decode` et écrit dans ces tables par lots ; les messages invalides sont comptés et journalisés, les doublons (redélivrance QoS 1, retain rejoué) ignorés. `Command.raison` donne `commande.decision_id` (doc 10 §3) ; après chaque lot, `backend/traceability.py` dérive les `action`, les confirme par `etat_actionneur` et applique les changements d'`etat_sante` décidés (doc 10 §3–4). Les résultats vision sont rattachés à un emplacement par les `camera_region` (centre de la bbox, ou seul emplacement visible en phase 1).

La consommation n'est **pas** un agrégat continu TimescaleDB : la durée d'un état demande une fonction fenêtre, interdite dans un continuous aggregate. Elle est recalculée toutes les heures par l'ingestion (jour courant et veille) ou à la demande (`python -m backend.consumption --jour …`).

Dashboard : `backend/docker-compose.yml` (TimescaleDB, Grafana, mosquitto de développement) et `backend/grafana/` (source de données et dashboard « Serre » provisionnés : climat, sol, solution, états des actionneurs, nœuds, alertes, décisions, consommation). `make stack-up && make db-init && make sim-demo` remplit la base avec 24 h simulées.

## 8. Configuration exportée vers le contrôleur

Le Pi doit rester autonome ([01 §1](01-architecture.md#principes)) : il ne lit pas la base du serveur en continu. L'interface **publie une configuration versionnée** de la serre :

```
UI ──► API ──► serre_config_v<N>.yaml ──► Pi : edge/config/serre.yaml (copie locale)
                                           └─ controller recharge à chaud, journalise la version
```

Contenu : zones, emplacements et plantes actives (espèce, stade, recette), capteurs et actionneurs (avec `duree_max_s`, `puissance_w`), régions caméra, recettes.
Chaque décision enregistre la `config_version` utilisée, ce qui rend les décisions rejouables.
Transport : topic retain `serre/config` (proposition, hors contrat actuel) ou simple copie `rsync` dans un premier temps.

Implémentation (`backend/config/export.py`, `make config-export [INSTALL=…] [PI_CONFIG=…]`) :

```
python -m backend.config.export                      # data/serre_config/serre_config_v<N>.yaml
python -m backend.config.export --install edge/controller/serre.yaml
python -m backend.config.export --rsync pi@serre.local:SerreIA/edge/controller/serre.yaml
```

- `build_config` reconstruit un `serre.yaml` **autonome** depuis la base (recettes en ligne : `recettes:` accepte un chemin ou un dictionnaire) ; il est validé comme le contrôleur le chargera (`SerreCfg`, recette et stade de chaque plante), avec les avertissements de cohérence. Une configuration invalide est refusée et aucune version n'est créée.
- La **version suit le contenu** : `sha256` du contenu hors version ; si rien n'a changé depuis le dernier export, le numéro est conservé, sinon N + 1, enregistré dans `config_export` (contenu complet, pour rejouer une décision) et dans `serre.config_version`.
- `--install` écrit le fichier de manière atomique (fichier temporaire + `os.replace`) : le `ConfigWatcher` du contrôleur recharge le fichier quand sa date change et ne lit jamais un fichier tronqué. `--rsync` copie la version vers le Pi.
- Tant que l'UI n'existe pas (G2), le cycle est : éditer `serre.yaml` → `make db-init` → `make config-export PI_CONFIG=pi@serre.local:SerreIA/edge/controller/serre.yaml` (ou `INSTALL=<chemin>` pour un contrôleur local). Sur le PC, ne pas installer par-dessus l'exemple versionné `edge/controller/serre.yaml`, qui reste la source du seed.
