# 17 — Analyse du système logiciel (état au 17/10/2026)

**But** : faire l'état des lieux de tout le logiciel avant la mise en serre réelle. On regarde le
contrat MQTT, le contrôleur, le simulateur, le firmware, la base, l'API, l'agent, les modèles de
vision, les données, l'interface et l'outillage. Ce document ne contient que des **constats** :
ce qui existe, ce qui tient et ce qui ne tient pas, avec les références dans le code. Les
améliorations proposées, toutes faisables sans matériel, sont dans
[18](18-ameliorations-logicielles.md).

> **Périmètre** : `main` au commit `c56412e` (code identique à `bc0ed4f`, PR #2). Analyse statique : lecture du code
> et des docs 01 à 16, sans lancer de tests, de notebooks ni d'entraînements. Les chiffres
> mesurés viennent de [14](14-resultats-phase1.md) et [16](16-test-systeme-simule.md). Les
> numéros de ligne valent pour ce commit.

## 1. Résumé

Le système est **complet de bout en bout en simulation**. Les capteurs simulés et les pannes
passent par MQTT et alimentent le contrôleur, qui produit des décisions tracées. Celles-ci sont
ingérées en base, puis exposées par l'API au tableau de bord, à l'agent Claude et à la vue jeu.
Le code est propre : docstrings qui renvoient aux docs, aucun `TODO` ni `FIXME`, contrat
Pydantic strict, environ 6 600 lignes de tests Python.

Les faiblesses portent sur l'exploitation plus que sur les fonctions :

| # | Constat | Domaine | Gravité |
|---|---|---|---|
| 1 | Le chauffage n'a pas de durée maximale et reste allumé si la sonde de T° se tait | contrôle | **critique** |
| 2 | Le bus MQTT n'a ni authentification ni TLS : une `Decision validee` forgée est exécutée | sécurité | **critique** |
| 3 | Le contrôleur ne garde aucun état : au redémarrage, propositions, verrous, historique et DLI sont perdus | contrôle | haute |
| 4 | Une exception dans `tick()` arrête le contrôleur, et les nœuds ne s'en aperçoivent pas | contrôle | haute |
| 5 | Les 42 % de faux positifs vision sur images saines ne sont pas traités (docs 14 et 15 non engagées) | vision | haute |
| 6 | Pas de migrations (Alembic), pas de rétention Timescale, tests sur SQLite seulement | base | haute |
| 7 | Dédoublonnage des alertes cassé, caches de l'ingestion jamais rechargés | ingestion | moyenne |
| 8 | API : lectures, WS et upload ouverts, réponses non typées, course à la validation | API | moyenne |
| 9 | Constats 1 à 5 de la doc 16 ouverts (boucle mildiou, chauffage avec ventilation, cycles courts, eau) | contrôle | moyenne |
| 10 | Pas de CI ; `deploy.sh` ne redémarre pas le contrôleur et n'a pas de retour arrière | outillage | moyenne |

## 2. Vue d'ensemble

### 2.1 Taille du code

| Module | Lignes | Plus gros fichiers | Tests |
|---|---|---|---|
| `common/mqtt` | 593 | `schemas.py` 308, `topics.py` 161 | `test_mqtt_contract.py` (331), `test_firmware_contract.py` |
| `edge/controller` | ≈3 100 | `forecast.py` 520, `config.py` 445, `service.py` 417, `rules.py` 410, `vision_rules.py` 390 | une douzaine de fichiers (`test_rules`, `test_safety`, `test_decision_lifecycle`…) |
| `edge` (vision, caméra, publication) | ≈2 150 | `camera_service.py` 253, `publisher.py` 172 | `test_edge_vision.py`, `test_camera_service.py` |
| `sim` | ≈1 890 | `scenario.py` 349, `attendus.py` 268, `nodes.py` 262 | `test_sim.py`, `test_scenarios.py` (413) |
| `firmware` | ≈1 340 | `actionneurs/main.cpp` 195, `serre_node.cpp` 168 | 7 tests Unity natifs (logique pure) |
| `backend` | ≈7 200 | `agent/tools.py` 1 015, `traceability.py` 601, `api/serres.py` 534 | ≈100 tests dans 17 fichiers (≈3 000 lignes) |
| `vision` | ≈4 630 | `train/train_classifier.py` 321, `eval/two_stage.py` 282 | `test_index`, `test_taxonomy`, `test_near_duplicates`… |
| `tools` | ≈1 000 | `notebooks/build.py` 634 | — |
| `frontend/src` | ≈9 400 écrites + ≈10 700 générées | `SerreJeu.tsx` 547, `Constructeur.tsx` 412, `scenes/Serre.ts` 365 | 16 fichiers Vitest (≈34 cas), 2 parcours Playwright |

### 2.2 Flux

```
 ESP32 (4 nœuds)  ──┐                              ┌── camera_service (ONNX / Hailo)
 ou sim/ (nœuds,    │      MQTT JSON (mosquitto)   │
 météo, pannes,  ───┼──────────────────────────────┤
 scénarios)         │                              └── edge/controller
                    │                                   safety → risk → GRU → rules → vision_rules
                    ▼                                   → arbitrage → safety.check → cmd / decision
          backend/ingestion ── base (SQLite ou TimescaleDB)
                                    │
               backend/api (FastAPI, threadpool) ── WS /ws/live (LiveHub)
                    │                    └── POST /agent/chat (SSE) ── backend/agent (Claude)
                    ▼
          frontend (React Query, Vite)  +  /jeu (Phaser)
```

Il y a trois façons de faire tourner l'ensemble sans matériel : `make api-sim` (simulateur dans le
processus de l'API, [12 §5](12-interface-utilisateur.md)), `make scenario` (rejoué au plus vite et
vérifié) et `make api-historique` (historique figé, en lecture seule, [16](16-test-systeme-simule.md)).

## 3. Forces à préserver

- **Un contrat MQTT unique et strict** : modèles Pydantic `extra="forbid"` et figés, topic → schéma
  vérifié par `decode()` (`common/mqtt/schemas.py`, `topics.py`). Les tables du firmware sont
  vérifiées contre ce contrat par un test (`tests/test_firmware_contract.py`).
- **Une sécurité en couches** : `safety.watch` d'abord, puis l'arbitrage où un « off » de sécurité
  l'emporte toujours, puis `safety.check` sur chaque ordre retenu (`edge/controller/service.py:138-170`,
  `safety.py:46-95`). Dans le firmware s'ajoutent les durées maximales des pompes, le flotteur
  local et le mode dégradé.
- **Une traçabilité réelle** : `Decision` avec preuves, `ordres`, `config_version`, cycle
  proposée / validée / rejetée / expirée, `Action` confirmée par `etat/`, et un arbre des actions
  ([10](10-decisions-tracabilite.md)).
- **Des scénarios vérifiables** : forçages, pannes injectables, vision factice et attendus YAML,
  avec la mention `connu` pour les écarts admis (`sim/scenario.py`, `sim/attendus.py`).
- **Un agent cantonné** : il ne fait que proposer. Les garde-fous sont dans le code (durée
  bornée, limites de sécurité, preuves existantes), tout est journalisé (`agent_journal`), avec
  budgets et cache de prompt stable ([11](11-agent-decision.md)).
- **Un ML reproductible** : graines fixées, SHA-256 de `index.parquet`, version de taxonomie et
  commit dans MLflow, splits groupés par pHash et dHash, notebooks générés.

## 4. Contrôle et sécurité (`edge/controller`, firmware)

### 4.1 Ce qui existe
`Controller.tick` tourne toutes les 10 s. Par zone, on obtient l'ordre suivant :
1. propositions de sécurité, risque mildiou, prévision GRU si le modèle ONNX existe, règles,
   puis règles vision ;
2. un ordre par actionneur, choisi par l'arbitrage ;
3. un filtre qui écarte l'état déjà atteint et les commandes en attente depuis moins de 120 s ;
4. `safety.check` sur chaque ordre retenu.

Seule la règle qui a allumé un actionneur peut l'éteindre (`owner`, `marche_min_s`). La
configuration est rechargée à chaud, et un fichier cassé laisse la version précédente en place
(`config.py:420-445`).

### 4.2 Limites constatées
- **Le chauffage peut rester allumé indéfiniment.**
  - Quand la T° n'est plus lue, `temperature()` rend `[]` (`rules.py:101-104`) et
    `safety.watch_zone` n'agit que si `t is not None` (`safety.py:109`). La sonde muette ne
    produit qu'une alerte *warning* sans ordre (`safety.py:246-261`).
  - L'actionneur `chauffage-z1` n'a pas de `duree_max_s` (`serre.yaml:45`), et le firmware n'a pas
    d'échéance pour le chauffage.
  - Un nœud air hors ligne avec le chauffage allumé laisse donc 1 500 W allumés sans contrôle.
- **Vérifications qui laissent passer quand la valeur manque** : la règle de présence teste
  `(ctx.value(PRESENCE) or 0) > 0`, si bien qu'une présence inconnue compte comme absence. De même,
  `t_max` et `t_min` ne s'appliquent que si `t is not None` (`safety.py:84-89`).
- **Capteur jamais vu** : la surveillance ne parcourt que les mesures reçues
  (`safety.py:246`). Un capteur déclaré dans `serre.yaml` qui n'a jamais publié n'est donc
  jamais signalé.
- **Pas de garde contre les exceptions** : `ctl.tick()` est appelé sans `try` dans `main`
  (`service.py:407-408`). Une exception arrête le service. systemd le relance
  (`Restart=always`, `WatchdogSec`), mais l'état est perdu (point suivant).
- **Aucun état persistant** : `GreenhouseState` est reconstruit uniquement depuis le flux MQTT
  (`state.py`). Les alertes, verrous, propositions, validations et DLI ne vivent qu'en mémoire
  (`service.py:73-80`). Après un redémarrage :
  - les propositions en attente sont perdues ;
  - les alertes sont republiées ;
  - les moyennes sur 12 h et la prévision n'ont plus d'historique ;
  - la DLI repart de 0, ce qui fait surcompenser les LED.
- **Les nœuds ne surveillent pas le contrôleur** : ils ne surveillent que leur propre connexion
  au broker. Un contrôleur arrêté avec le broker en marche laisse le chauffage, le ventilateur
  et les LED dans leur dernier état.
- **Mode dégradé** (`firmware/src/actionneurs/main.cpp:146-176`) : arrosage et ventilation
  programmés, mais **pas de chauffage hors gel**, et tout reste éteint sans heure NTP. Le
  niveau de cuve reçu par MQTT n'est jamais invalidé quand il vieillit (`main.cpp:116-121`).
- **Firmware incomplet pour z2** : le nœud actionneurs ne gère que z1 (`node_config.h`), alors
  que `serre.yaml` déclare des pompes pour z2 (NFT, pH-, nutri A/B) et un nœud `esp32-05`
  absent de `platformio.ini`. Un nœud est limité à 4 abonnements (`serre_node.h:51`).
- **Constats de la doc 16 encore ouverts** ([16 §6](16-test-systeme-simule.md#6-journal-de-test)) :
  1. décisions mildiou republiées en boucle, faute d'hystérésis sur les règles vision (80 fois) ;
  2. la ventilation d'humidité masque la cause mildiou (propriétaire de l'actionneur) ;
  3. chauffage et ventilation en même temps : l'arrêt à 20 °C ne suit pas le minimum de la
     recette, 21 °C (`rules.py:136-148`) ;
  4. cycles courts : il y a `marche_min_s`, mais pas de temps d'arrêt minimal ;
  5. l'eau compte la recirculation NFT (`backend/consumption.py`).
- **Seuils vision en trois endroits** : `risk.py` (`VISION_SEUIL`, `CONFIRMATIONS`),
  `regles.yaml` et `VisionAlertConfig`, avec en plus HR 85 % codé en dur dans `vision_rules.py`.

## 5. Contrat MQTT et bus

- **Pas de version de schéma** dans les messages : seuls `Decision.config_version` et
  `RegleRef.version` portent une version. Un nœud plus ancien que le contrat est rejeté sans
  qu'on sache pourquoi.
- **Pas de sécurité** :
  - `backend/mosquitto.conf` a `listener 1883` et `allow_anonymous true` ;
  - `MqttPublisher` n'a ni TLS ni identifiants ;
  - côté firmware, les identifiants sont facultatifs et le transport est `WiFiClient` en clair.
  N'importe quel appareil du réseau peut publier sur `cmd/` ou publier une `Decision`
  `statut: validee`, que le contrôleur exécute (`service.py:105-108`).
- **QoS** : PubSubClient ne publie qu'en QoS 0. Les `etat/` retenus et les mesures des nœuds
  partent donc en QoS 0, alors que le contrat demande QoS 1 pour `etat`.
- **Horodatage** : le firmware ignore le `ts` des commandes (une commande vieille n'est pas
  rejetée). L'âge des données mélange l'horloge du Pi et celle du nœud. Le serveur NTP par défaut
  est `pool.ntp.org`, ce qui suppose un accès Internet.
- **Logique en double** : plages physiques (`ranges.py` et `ranges.h`), liste des actionneurs
  et validation des commandes (Pydantic et `command.h`). La synchronisation est vérifiée par un
  test plutôt que générée. La durée maximale des pompes est aussi en double (`MAX_PUMP_S` 1 800
  dans le firmware, `duree_max_s` dans `serre.yaml`) sans test. La docstring de `ranges.py:4`
  cite encore `firmware/lib/serre_core/`, au lieu de `serre_logic`.

## 6. Simulateur (`sim/`)

- **Modèle physique** (`sim/model.py`) :
  - T° du premier ordre (τ = 1 800 s), avec soleil, chauffage et ventilation ;
  - HR relaxée linéairement, **sans psychrométrie** : pas de VPD, et la brumisation ne
    refroidit pas ;
  - CO₂, pH et EC linéaires ;
  - **la cuve n'est jamais remplie** ;
  - pas de retard des actionneurs.
- **Nœuds** (`sim/nodes.py`) : payloads, plages et refus des pompes émulés, mais **pas le mode
  dégradé de l'ESP32**. La perte du broker n'est donc pas testée de bout en bout.
- **Scénarios** : deux seulement (`journee`, `mildiou`). Les scénarios panne réseau, broker
  redémarré et rechargement à chaud sont listés en [16 §7](16-test-systeme-simule.md#7-reste-à-faire).
  Il n'y a ni saison froide, ni canicule, ni redémarrage du contrôleur.

## 7. Base de données et ingestion (`backend/db`, `backend/ingestion`)

### 7.1 Schéma
- Tables de configuration (serre, cuve, zone, contenant, emplacement, recette, plante,
  affectation, capteur, actionneur, camera, camera_region, config_export).
- Séries sans clé étrangère, par choix (mesure, vision_resultat, etat_actionneur, commande,
  alerte, noeud_status).
- Tables mutables (decision, action, consommation_jour, agent_*).

### 7.2 Limites constatées
- **Pas de migrations** : `init_db` fait `create_all`, puis `add_missing_columns`
  (`session.py:47`), qui n'ajoute que des colonnes nullables : pas d'index, de type ni de
  contrainte. Alembic est annoncé « à venir » depuis G1.
- **Timescale minimal** : 6 hypertables (`timescale.sql`), mais **ni rétention, ni compression,
  ni agrégat continu**. À une mesure toutes les 30 s par capteur, `mesure` grossit sans limite.
- **Agrégation en Python** : `series()` et `_resample` (`api/mesures.py`, `agent/tools.py`)
  chargent toutes les lignes brutes de la fenêtre au lieu de `time_bucket` ou de `GROUP BY`.
  Le même code est dupliqué entre l'API et l'agent, et l'API importe des fonctions privées
  (`_resample`, `_vision`, `_grid`).
- **Index manquants sur les chemins chauds** :
  - `vision_resultat.emplacement_id` (plan de zone) ;
  - `alerte.id` seul (acquittement ; la clé primaire est `(ts, id)`) ;
  - `decision.statut` et `action.resultat` (parcourus par `reconcile` à chaque écriture) ;
  - `etat_actionneur (zone, actionneur, ts desc)`.
- **Tests sur SQLite seulement** : `timescale.sql`, JSONB et les hypertables ne sont pas testés
  (`SERREIA_TEST_PG` existe mais n'est pas lancé).
- **Ingestion** (`mqtt_ingest.py`) :
  - les alertes reçoivent `id=uuid.uuid4().hex` (`:163`), si bien qu'une redélivrance QoS 1 ou
    un message rejoué crée un doublon, à l'inverse de ce que dit la docstring ;
  - `reload()` n'est appelé qu'à la construction (`:60`), donc une caméra, une région ou un
    actionneur modifié dans l'UI n'est pas vu par une ingestion en cours ;
  - l'écriture en base se fait sur le thread de rappel MQTT, sous verrou, avec `reconcile` sans
    borne de temps, si bien qu'une base lente bloque le client MQTT ;
  - au-delà de `MAX_PENDING` (200 000 lignes), tout le tampon est abandonné avec un simple log
    (`:222-224`).

## 8. API (`backend/api`)

- **Couverture** : environ 80 routes sous `/api` (structure, équipements, configuration
  cohérence / diff / publication, mesures, tableau de bord, vision, images, consommation,
  alertes, décisions, actions, agent), `WS /ws/live` et le front compilé.
- **Réponses non typées** : les routes rendent `dict`. L'OpenAPI ne décrit donc que les corps de
  requête. Le front recopie les types à la main (`frontend/src/api/types.ts`, 400 lignes) et
  les schémas zod, sans contrôle de dérive.
- **Authentification** (`api/auth.py`) :
  - le mot de passe `SERREIA_UI_PASSWORD` est facultatif, et sans lui tout est ouvert ;
  - avec lui, seules les écritures sont protégées : **tous les GET**, dont les conversations de
    l'agent, ainsi que `WS /ws/live` restent publics ;
  - `POST /api/images` est ouvert (`OPEN`, `:22`), donc n'importe qui peut écrire des JPEG de
    15 Mo sur le disque ;
  - les jetons sont gardés en mémoire (perdus au redémarrage, purgés seulement à la lecture) ;
  - pas de limite de débit sur le login ;
  - le nom d'utilisateur est déclaratif.
- **Course à la validation** : `validate()` publie la décision **avant** le commit de la requête
  (`decisions.py:82-91`). Si l'ingestion enregistre le `executee` du contrôleur avant ce commit,
  le commit le remet à `validee`. Sans verrou de ligne, deux validations simultanées publient
  deux fois. Le numéro de version de `config/export.py` est un `max+1` sans verrou.
- **Performances** : N+1 sur le tableau de bord (une requête par courbe et par actionneur) et
  sur le plan (vision par emplacement, sans index). Toutes les routes sont des `def` synchrones
  dans le threadpool, et le chat SSE occupe un thread pendant tout un tour de l'agent.
- **Configuration et observabilité** :
  - variables d'environnement lues un peu partout, sans objet de réglages unique ;
  - identifiants par défaut dans le code (`session.py:17`) ;
  - un logger dont le niveau est changé globalement dans une requête (`config.py:35`) ;
  - ni `/health`, ni métriques (les compteurs `recus`, `rejets` et `ecrits` existent mais ne
    sont pas exposés), ni identifiant de requête ;
  - en mode `--mqtt sim`, un `SimRunner` qui plante ne fait qu'un log (`api/sim.py:107`), et
    l'API continue sur une horloge figée.

## 9. Agent (`backend/agent`)

- **Bon état général** :
  - boucle de 12 tours d'outils au plus par message ;
  - budgets de tokens par conversation (400 k) et par jour (3 M) ;
  - `pause_turn`, `refusal` et `max_tokens` gérés ;
  - cache de prompt stable (JSON trié, sans horodatage) ;
  - entrées d'outil revalidées par Pydantic.
- **Limites** :
  - `Tools.run` n'attrape que `ValidationError` et `ToolError` (`tools.py:278-291`). Une
    `SQLAlchemyError` ou une `KeyError` remonte dans le générateur SSE et coupe le flux sans
    événement `erreur`.
  - Le nouvel essai sur une entrée d'outil illisible (`llm.py:92`) relance tout le tour après que
    du texte a déjà été envoyé : ce texte peut apparaître deux fois dans l'UI.
  - L'historique est rejoué en entier à chaque tour, sans compaction, et seul le plafond de 400 k
    tokens l'arrête.
  - Le budget compte les lectures du cache au prix plein et n'est pas exprimé en euros.
  - **Injection par les données** : notes de plantes, noms, messages d'alerte et classes vision
    arrivent tels quels dans les résultats d'outils. La validation humaine borne l'impact, sauf
    pour `demander_capture`, qui s'exécute tout de suite (limité seulement par les 12 tours).
  - Pas encore joué avec Claude réel : `make agent-eval` existe, et `questions.yaml` compte
    12 questions sur les ~30 visées ([16 §7](16-test-systeme-simule.md#7-reste-à-faire)).

## 10. Modèles de vision (`vision/`)

### 10.1 Résultats mesurés ([14](14-resultats-phase1.md))

| | valeur |
|---|---|
| classifieur `1e8dfc9c`, test en domaine, F1 `sante` | 0,979 (CCMT), 0,999 (PV) |
| même modèle sur PlantDoc (hors domaine) : rappel anormal / précision / spécificité | 0,986 / 0,679 / **0,50** |
| PlantDoc : F1 `classe`, espèce, ECE `sante` / `classe` | 0,264 ; 0,46 ; 0,13 / 0,30 |
| ablations A–E, F1 `sante` PlantDoc | 0,705 à 0,735 (écart entre runs ≈ 0,02) |
| YOLOv8n `a604f044`, mAP@0,5 val / test | 0,888 / 0,956 (test flatté par PV) |
| deux étages sur PlantDoc TEST : faux positifs sur images saines | **42,2 %** |

### 10.2 Limites constatées
- **Aucun des points P0 à P2** de [14 §7](14-resultats-phase1.md) et de
  [15](15-ameliorations-detection.md) n'est réalisé :
  - pas de seuil `sante` réglé, ni de calibration par température ;
  - pas de plusieurs graines ni de bootstrap ;
  - pas de val hors domaine pour choisir le checkpoint ;
  - pas de mAP PlantDoc seul, ni d'évaluation sur boîtes oracle ;
  - pas de règle de décision commune ;
  - pas d'agrégation des feuilles.
- **La config principale ne peut pas tourner** telle quelle : `clf_effnet_b0.yaml` active
  `background.enabled: true` sur `data/backgrounds`, qui n'existe pas, et `BackgroundPaster`
  lève une erreur. L'ablation C n'a pas réellement testé le fond (forcé à `false`,
  [14 §4.2](14-resultats-phase1.md)).
- **Mesure faussée** : les deux étages ont été évalués avec l'ablation E au lieu du run
  retenu, parce que le notebook 05 prend par défaut le `best.pt` le plus récent
  (`tools/notebooks/build.py:500`, `:574-578`).
- **Règle de décision en double** : hors ligne, la règle est `max p_anormal ≥ 0,5` sur une image
  (`eval/two_stage.py:110-122`). Sur l'edge, elle est 0,6 sur 3 captures. On ne mesure donc pas
  ce qui sera déployé.
- **Gel du backbone incomplet** : seul `requires_grad` est coupé (`models/multihead.py:40`),
  et les statistiques de BatchNorm continuent d'évoluer.
- **Prétraitement** : la balance des blancs sur carte grise n'est appliquée qu'à l'inférence
  (`edge/camera_service.py:139`). Les constantes ImageNet sont recopiées
  (`edge/vision/backends.py:17-19`). `torch.backends.cudnn.benchmark=True` est actif, mais
  `deterministic` ne l'est pas.

## 11. Données

- **Écart de domaine** : aucune image de serre, 29 classes sur 56 présentes dans PlantDoc, déséquilibre
  ×36, sampler en 1/√effectif sans équilibrage par source, `data/backgrounds/` absent.
- **Versionnage** : archives tar sur Drive avec rclone ([data-drive](data-drive.md)), et
  traçabilité par le seul hash de l'index. Les résultats MLflow sont sur Colab : `runs/` est vide
  et `mlruns/` absent en local, si bien que les chiffres ne survivent que dans la doc 14.
- **Notebooks** : committés avec leurs sorties alors que le générateur les écrit sans, donc
  `make notebooks` en mode `--check` est probablement rouge. Les métadonnées disent `T4` alors
  que les runs ont tourné sur A100.

## 12. Interface (`frontend/`)

- **Pile** : React 18, Vite 6, TypeScript 5.7, Tailwind 4, Radix, TanStack Query 5,
  react-router 6, react-hook-form avec zod, recharts, @xyflow/react, Phaser 3.90.
  Architecture saine : l'état serveur est dans React Query, le temps réel invalide les requêtes
  (`live/LiveProvider.tsx`), et les pages lourdes (`Arbre`, `SerreJeu`) sont chargées à la demande.
- **Limites** :
  - **contrat en double** : `types.ts` et zod écrits à la main, à cause des réponses non typées
    (§8) ;
  - **bundle** : le chunk principal fait 895 Ko (recharts et Radix chargés d'emblée), `SerreJeu`
    1,58 Mo, et l'avertissement de taille est relevé à 1 700 Ko pour ne plus s'afficher
    (`vite.config.ts:19`) ;
  - **robustesse du temps réel** : `JSON.parse` sans `try` (`LiveProvider.tsx:67`,
    `api/sse.ts:29`), reconnexion toutes les 3 s sans backoff, WS sans jeton ;
  - **mobile** : un seul point de rupture (tiroir `md:`), et le glisser-déposer HTML5 du
    constructeur ne marche pas au toucher ;
  - **qualité** : ni ESLint ni Prettier, aucun test des pages (Dashboard, Constructeur,
    Équipements, Consommation, Décisions), des hooks ou de `LiveProvider`, pas de couverture,
    pas de test d'accessibilité automatisé ;
  - **absent** : PWA, i18n ;
  - **gros composants** : `SerreJeu.tsx` 547 lignes, `Constructeur.tsx` 412,
    `useConstruction.ts` 318.

## 13. Outillage et déploiement

- **Pas de CI** (aucun `.github/`), alors que le dépôt est sur GitHub. Ruff, pytest, Vitest,
  typecheck, les tests natifs PlatformIO et `make scenario` ne sont lancés qu'à la main.
- **`edge/deploy.sh`** :
  - ne redémarre que `serreia-camera` et `serreia-vision-alerts`, **pas `serreia-controller`**
    (`:24-25`), si bien que le code du contrôleur mis à jour n'est pas chargé ;
  - la porte anti-régression du modèle n'existe qu'en commentaire (`:7-8`) ;
  - le `git pull` se fait sur l'appareil, sans retour arrière ni contrôle de santé.
- **Firmware** : OTA (ArduinoOTA) protégée par un mot de passe par défaut `changeme`, images non
  signées. L'environnement `env:air` est fixé sur z1.
- **Pas de pre-commit**. Le Makefile suppose un venv actif (`PY ?= python`).

## 14. Synthèse des risques

| Risque | Probabilité | Impact | Renvoi aux améliorations |
|---|---|---|---|
| Chauffage bloqué allumé (sonde ou nœud muet) | moyenne | dégâts aux plantes, 1,5 kW, incendie | [18 C1](18-ameliorations-logicielles.md#c1--chauffage-borné-et-coupé-sur-sonde-muette-p0) |
| Commande forgée sur le bus | faible (réseau domestique) | actionneurs pilotés de l'extérieur | [18 M2](18-ameliorations-logicielles.md#m2--authentification-et-acl-mosquitto-p1) |
| Redémarrage du contrôleur (mise à jour, exception) | haute | propositions perdues, LED surcompensées | [18 C2, C3](18-ameliorations-logicielles.md#2-contrôle-et-sécurité-c) |
| Alertes vision trop nombreuses | haute | perte de confiance, agent noyé | [18 V](18-ameliorations-logicielles.md#8-modèles-et-données-vision-v) |
| Évolution du schéma sans migration | haute | base à recréer, perte d'historique | [18 D1](18-ameliorations-logicielles.md#d1--alembic-p1) |
| Base qui grossit sans limite | certaine (à terme) | carte SD ou disque plein, API lente | [18 D2](18-ameliorations-logicielles.md#d2--rétention-compression-agrégats-continus-p1) |
| Statut de décision écrasé | faible | traçabilité fausse | [18 A3](18-ameliorations-logicielles.md#a3--validation-atomique-p0) |
| Déploiement qui laisse l'ancien contrôleur | haute | correctif non appliqué sans qu'on le voie | [18 O2](18-ameliorations-logicielles.md#o2--deploysh-fiable-p0) |
| Régression non vue (pas de CI) | haute | une garantie de sécurité perdue | [18 O1](18-ameliorations-logicielles.md#o1--intégration-continue-p0) |
| Dérive des types entre front et API | moyenne | écrans cassés après un changement d'API | [18 A1](18-ameliorations-logicielles.md#a1--réponses-typées-p1) |
