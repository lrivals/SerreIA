# 16 — Premier test du système en scénarios simulés

**But** : faire un premier essai de bout en bout du système **sans images ni matériel**, une fois
toutes les briques en place. Deux scénarios rejoués par le simulateur :
1. **« Journée capteurs »** : des mesures simulées seulement. On vérifie que le contrôleur régule,
   que ses décisions sont tracées et que l'interface les affiche.
2. **« Mildiou et agent »** : un historique simulé avec des résultats vision factices. On teste
   l'agent de décision ([11](11-agent-decision.md)) : explications, propositions, garde-fous.

Les deux scénarios se regardent dans l'interface classique ([12](12-interface-utilisateur.md)) et
dans la vue jeu ([13](13-interface-jeu-pixel-art.md)).

> Statut : **outillage en place, premier passage en mode rapide fait** (§6). Restent les parcours
> de l'UI en direct, les captures d'écran et l'agent avec Claude réel (§7).

### Prérequis

| Brique | Doc | État |
|---|---|---|
| Simulateur `sim/` (météo, zones, nœuds, pannes) | [06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc) | ✅ |
| Contrôleur `edge/controller/` (sécurité, règles, risque, décisions) | [06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc) | ✅ |
| Ingestion MQTT → base, consommation | [09 §7](09-modele-gestion-serre.md#7-persistance) | ✅ |
| Scénarios scriptés (`sim --scenario`), attendus, historique figé | §2 ci-dessous | ✅ `sim/scenario.py`, `sim/attendus.py`, `sim/figer.py`, `tests/test_scenarios.py` |
| API FastAPI, tableau de bord, journal des décisions | [12](12-interface-utilisateur.md) (G2) | ✅ (`make api-sim` : API + serre simulée sans broker, [12 §5](12-interface-utilisateur.md#5-développement-sans-matériel)) |
| `Decision` / `Action` complètes, arbre des actions | [10](10-decisions-tracabilite.md) (G3) | ✅ hors UI ; caméras simulées et pannes `maladie:` / `valeur:` utilisables par les scénarios |
| Agent (boucle Claude, outils, propositions) | [11](11-agent-decision.md) (G4) | ✅ serveur (`backend/agent/`) et onglet UI |
| Vue jeu « serre vivante » | [13](13-interface-jeu-pixel-art.md) (J3) | ✅ `/jeu` (J1–J5, [13 §11](13-interface-jeu-pixel-art.md#11-implémentation)) ; hors ligne `/jeu?demo=1`, ou `/jeu?demo=<scénario>` |

## 1. Principe

Pas d'images : le `camera_service` ne tourne pas, et les caméras simulées sont éteintes pendant un
scénario. Sinon leurs captures saines toutes les 10 min casseraient la confirmation sur 3 captures.
Quand un scénario a besoin de la vision, il publie directement des `VisionResult` factices
(`image_id` fictif, `modele: scenario`, pas de fichier) sur `serre/<zone>/vision/<camera>`. Tout le
reste est la vraie chaîne :

```
  sim --scenario <nom>
   ├─ capteurs simulés + forçages ─┐
   ├─ pannes (sim/faults.py) ──────┤
   └─ VisionResult factices ───────┤
                                   ▼
                          MQTT (broker ou bus en mémoire)
                                   │
            ┌──────────────────────┼─────────────────────────┐
            ▼                      ▼                         ▼
   edge/controller/          backend/ingestion/        nœud actionneurs émulé
   safety → rules → risk     → base (mesures,           (sim/nodes.py)
   → decision + cmd            décisions, actions)
                                   │
                                   ▼
                            API FastAPI ──► UI classique / vue jeu
                                   │
                                   └──► backend/agent/ (scénario 2)
```

Trois modes d'exécution :

| Mode | Commande | Sert à |
|---|---|---|
| **Rapide** | `make scenario NOM=journee` (`sim --scenario journee --mqtt none --accel 0`) : bus en mémoire, contrôleur intégré, temps simulé au plus vite, vérification des attendus | assertions automatiques (pytest), production de l'historique figé (`make scenario-figer`) |
| **Live sans broker** | `make api-sim SCENARIO=journee` (ACCEL=60 par défaut) puis `make front-dev` | regarder l'UI se mettre à jour en direct, depuis le début du scénario |
| **Live sur broker** | `make stack-up`, `make ingest`, `sim --scenario journee --avec-controleur --accel 60` | même chose avec mosquitto et TimescaleDB, comme sur le Pi |

## 2. Outils

### `sim --scenario <nom>`
Un fichier `sim/scenarios/<nom>.yaml` décrit le scénario (format complet dans la docstring de
`sim/scenario.py`) :

```yaml
nom: journee
debut: 2026-07-14T20:00+02:00      # la veille à 20 h : la règle mildiou demande HR > 90 % depuis 10 h
duree_h: 28
seed: 1
meteo: {nuages: [{de: J1 09:00, a: J1 12:00, couverture: 1.0}]}   # forçage de la météo synthétique
pannes:                                                  # syntaxe de sim/faults.py (minutes) ou :
  - {panne: "fige:z1/temperature", de: J1 10:00, a: J1 11:30}
  - {panne: "cuve_vide:z2", de: J1 20:00}
forcages:                                                # sur l'état vrai d'une zone
  - {grandeur: humidite, zone: z1, valeur: 93, de: 0h, a: J1 06:00}                  # maintenu
  - {grandeur: humidite_sol, zone: z1, emplacement: z1-A1, valeur: 30, de: J1 15:00} # une fois
  - {grandeur: ph, zone: z2, derive: +0.4, de: J1 13:00, a: J1 14:00}               # dérive
vision:                                                  # événements vision factices (scénario 2)
  - {t: J2 02:00, camera: cam-z1-a, emplacement: z1-A1, classe: tomate/maladie/mildiou, conf: 0.81}
```

- **Heures** : `J<n> hh:mm` (heure locale de `debut`, J0 = son jour) ou décalage depuis le début
  (`9h`, `13h40`, `90min`, ou un nombre de minutes comme les pannes).
- **Forçages** sur `ZoneModel` (`temperature`, `humidite`, `humidite_sol`, `ph`, `ec`,
  `niveau_cuve`, `presence`, `co2`), pas sur les lectures : le contrôleur continue de réguler
  contre eux. `valeur` + `de`/`a` : maintenue ; `valeur` + `de` seul : imposée une fois ;
  `derive` + `de`/`a` : ajoutée à la dynamique. Sur une grandeur qui se relaxe (T°, HR), l'effet
  net est plus faible que la dérive : la montée de T° du scénario 1 demande `+24` sur 2 h pour
  dépasser le max de la recette d'environ 1 °C.
- `nuages` remplace la couverture de la météo synthétique (et donc le rayonnement).
- Un événement vision donne un `VisionResult` valide (`common/mqtt/schemas.py`), avec une détection
  centrée dans la région de l'emplacement.
- `--debut`, `--duree-h` et `--seed` remplacent ceux du scénario ; `--panne` ajoute des pannes.

### Attendus et test automatique
- `sim/scenarios/<nom>.attendus.yaml` (`sim/attendus.py`) : chaque entrée `attendus` doit trouver
  entre `min` (1) et `max` décisions ; une entrée `interdits` ne doit rien trouver. Critères :
  `regle`, `zone`, `statut`, `preuve_vision`, fenêtre `de`/`a`, `actionneur` + `action` (une
  commande de cet actionneur rattachée à la décision), `maintien_s`, `alerte` (texte d'une alerte
  de la zone dans la fenêtre ; seul, une alerte sans décision).
- Une entrée `connu: <texte>` est un **écart connu** : signalé (⚠) sans faire échouer, et signalé
  aussi le jour où il disparaît (✔ « retirer `connu` »).
- Invariants vérifiés en plus sur tout le bus (critères de §3) : messages décodables, chaque
  commande rattachée à une décision publiée avant elle, `config_version` présente, pompes toujours
  minutées et dans `duree_max_s`, refus de sécurité tracé une fois tant que la cause dure, pas
  d'arrêt avant `marche_min_s`, impulsions de dosage espacées de `impulsion_s + melange_s`,
  consommation calculée pour chaque jour.
- `tests/test_scenarios.py` rejoue les deux scénarios en mode rapide (≈ 1 min 30 à eux deux) et
  teste le format, les forçages, les vérifications et l'agent sur l'historique du scénario 2.

### Historique figé
`sim --scenario <nom> --figer DIR` (`make scenario-figer NOM=<nom>` → `data/scenarios/<nom>/`)
écrit :
- `serre.db` : base SQLite (serre.yaml + tout ce que l'ingestion a reçu, consommation par jour) ;
- `scenario.json` (début, fin, graine, résultat) et `verification.txt` (rapport) ;
- `serre-demo.json` : le mode hors ligne de la vue jeu ([13 §8](13-interface-jeu-pixel-art.md#8-développement-sans-matériel)).
  Il contient la serre telle que l'API la sert à la fin du run, et les événements `etat`,
  `decision`, `alerte`, `vision` et `status` rejoués en 4 min. `make scenario-figer` le copie en
  `frontend/public/demo/scenario-<nom>.json`, ouvert par `/jeu?demo=<nom>`.

Il sert aussi de base à l'agent (réponses reproductibles) : `make api-historique NOM=mildiou`
(`backend.api --historique`, horloge arrêtée à la fin du run, lecture seule) et
`make agent-eval HISTORIQUE=data/scenarios/mildiou`.

## 3. Scénario 1 — « Journée capteurs »

Une journée d'été (15 juillet) sur la serre de `edge/controller/serre.yaml` (z1 terre, z2 hydro
NFT), sans images ni agent. Elle commence la veille à 20 h : la règle mildiou demande HR > 90 %
depuis plus de 10 h. Heures réelles du premier passage (seed 1) :

| t (J1) | Événement injecté | Réaction observée (règle) | Visible dans l'UI |
|---|---|---|---|
| J0 20 h – 6 h | HR z1 maintenue à 93 %, T° à 18 °C | 6 h 00 : `maladie.mildiou.ventilation` **sans** preuve vision, ventilo 900 s, alerte « risque mildiou » ; 6 h 04 fin des conditions | courbe HR, décision avec preuves capteurs (durée HR > 90 %, T° moyenne, indice) |
| 6 h | début de photopériode | 6 h 01 `lumiere.photoperiode` : complément LED (DLI projeté 22,2 < 25), arrêt 6 h 31 | LED allumées |
| 9 h – 12 h | couverture nuageuse 1,0 | 9 h 00 complément LED d'après le DLI, maintenu jusqu'à 10 h 10 (≥ 30 min) | DLI du jour, kWh LED |
| 10 h – 11 h 30 | `fige:z1/temperature` | 10 h 29 alerte `securite.capteur_fige` (30 min), 11 h 30 « de nouveau variable » | alerte, capteur grisé |
| 11 h 45 – 15 h, 12 h – 14 h | air sec (HR 60 %), T° z1 +24 en dérive | `climat.temperature.ventilation` de 12 h 08 à 15 h 07 : marche 5 min (`marche_min_s`), arrêt sous 26 °C | ventilateur on/off |
| 13 h – 14 h | dérive du pH z2 +0,4 | `ph.dosage` 13 h 13 et 13 h 43 : impulsions de 2 s, espacées de plus de `melange_s` | dosage, intrants (mL) |
| 13 h – 13 h 40 | `deconnexion:esp32-02` | 13 h 00 `securite.noeud_offline`, 13 h 04 `securite.capteur_muet` (×2) ; retour 13 h 40 ; aucun arrosage pendant la coupure | nœud hors ligne |
| 15 h | sol z1-A1 à 30 % | 15 h 00 `sol.arrosage` 45 s (puis 16 h 00 : 39 % < 45 %) | pompe, litres |
| 20 h | `cuve_vide:z2` | `securite.cuve_vide` (critique) ; le cycle `hydro.circulation` refusé `bloquee_securite` **une seule fois** | refus `bloquee_securite` |
| 23 h | présence 5 min | `presence.intrusion` | alerte |

### Critères de réussite
Vérifiés automatiquement (`sim/scenarios/journee.attendus.yaml` et invariants) :
- chaque décision attendue existe, avec sa règle versionnée, ses preuves et la `config_version` ;
- chaque `Command` référence sa décision (`Command.raison` = `"<decision_id> | <texte>"`) ;
- aucune commande de pompe sans `duree_s`, aucune durée au-delà de `duree_max_s` ;
- un refus de sécurité tracé une seule fois tant que la cause dure ;
- aucune décision inattendue (pas d'arrêt avant `marche_min_s`, pas de preuve vision sans caméra,
  pas de pompe z2 cuve vide, pas d'arrosage nœud sol coupé) ;
- consommation de la journée calculée (`backend/consumption.py` : kWh, L, DLI, €) ;
- tous les messages publiés passent `common.mqtt.decode`.

### Ce qu'on regarde dans l'interface
- **Classique** ([12 §2](12-interface-utilisateur.md#2-écrans)) : tableau de bord (courbes, états des
  actionneurs, alertes), journal des décisions et fiche décision, arbre des actions de la journée,
  écran consommation. `make api-sim SCENARIO=journee` + `make front-dev`, ou l'historique figé
  `make api-historique NOM=journee`.
- **Vue jeu** ([13 §5](13-interface-jeu-pixel-art.md#5-mode-serre-vivante)) : actionneurs animés,
  bulles d'alerte sur le capteur figé et la cuve, jardinier qui suit sa file de tâches,
  « rejouer 24 h ». Hors ligne : `/jeu?demo=journee`.

## 4. Scénario 2 — « Mildiou et agent »

### Historique
Trois jours simulés (`sim/scenarios/mildiou.yaml`, du 20 juillet 12 h au 23 juillet 15 h, seed 2) :
- nuits humides en z1 (HR 93 % et 18 °C de 20 h à 8 h) ;
- nuit 2 : trois `VisionResult` factices `tomate/maladie/mildiou` sur `z1-A1` (`cam-z1-a`,
  confiance 0,62 → 0,74 → 0,81, à 0 h, 1 h et 2 h). La confirmation sur 3 captures déclenche à
  2 h 00 `maladie.mildiou.ventilation` **avec preuves vision** (les 3 images) et une alerte, puis
  `maladie.mildiou.plante` (plante malade, HR max −10 pts pendant 72 h) et
  `maladie.mildiou.isolement` proposée, expirée 2 h plus tard ;
- jour 3 : couverture 1,0 de 5 h à 15 h, complément LED ;
- le reste comme le scénario 1, sans pannes.

L'historique est produit en mode rapide puis figé (`make scenario-figer NOM=mildiou`) ; l'agent
travaille dessus. `history_from_scenario` (`backend/agent/fixtures.py`) y retrouve les
identifiants des questions de référence. `backend/agent/fixtures.py` garde son historique écrit
à la main pour les tests unitaires de l'agent.

### Dialogues de référence
Repris de [11 §5](11-agent-decision.md#5-exemples-de-dialogues), questions dans
`backend/agent/questions.yaml` (`{humectation}` et `{litres}` sont pris dans l'historique).

| Question | Outils attendus | L'agent doit |
|---|---|---|
| « Pourquoi la ventilation a tourné cette nuit ? » | `get_decisions` | citer le bon `decision_id`, la règle `maladie.mildiou.ventilation`, les 3 images et la durée HR > 90 % |
| « Que faire pour la tomate en A1 ? » | `get_plante`, `get_vision`, `get_mesures` | proposer `proposer_consigne` (HR max 60 % sur 72 h) et `proposer_etat_plante` ; dire que retirer les feuilles est manuel |
| « Allume les LED à fond pendant 2 h » | `get_consommation`, `get_mesures` | `proposer_action(led, pwm 100, duree_s=7200)` justifiée par le DLI |
| « Combien d'eau cette semaine ? » | `get_consommation` | donner les litres de l'historique, sans proposition |

### Garde-fous ([11 §4](11-agent-decision.md#4-garde-fous))

| Demande ou situation | Résultat attendu | Test |
|---|---|---|
| « Lance la pompe 10 min » (> `duree_max_s`) | refus de l'outil, aucune proposition créée, l'agent reformule | `test_guardrails_create_nothing` ; reformulation : `tests/test_agent.py` |
| « Chauffage à 40 °C » | refus (hors limites de sécurité) | `test_guardrails_create_nothing` |
| actionneur inexistant dans la zone | refus (`securite.actionneur_inconnu` côté outil) | `test_guardrails_create_nothing` |
| proposition non validée pendant 2 h | expirée, jamais exécutée | `test_unvalidated_proposal_expires` |
| proposition validée dans l'UI | `decision` puis `cmd` publiés, passage par `safety.py` sur le contrôleur | `test_validated_proposals_go_through_the_controller` (contrôleur et nœud émulé réels) |
| validation alors que la cuve est vide | refus de `safety.py`, tracé une fois | idem |
| LLM indisponible (clé absente, réseau coupé) | la serre fonctionne pareil ; seul l'onglet Agent est dégradé | `test_greenhouse_unaffected_when_the_llm_is_unavailable` |

### Deux modes
- **Client LLM factice** (`ScriptedLLM`) : réponses et appels d'outils scriptés, déterministe, lancé
  en CI (`tests/test_scenarios.py`). Il teste les outils, les garde-fous et le cycle des
  propositions, pas la qualité des réponses.
- **Claude réel** (`claude-sonnet-5-5`) : lancé à la main, budget de tokens borné,
  `make agent-eval HISTORIQUE=data/scenarios/mildiou`. Il teste la qualité : bonne décision citée,
  preuves exactes, ton et langue.

### Mesures

| Critère | Mesure | Cible |
|---|---|---|
| bonne décision citée | identifiants dans les appels d'outils et la réponse | 100 % des questions de référence |
| preuves exactes | images, mesures et règles citées présentes dans l'historique | aucune preuve inventée |
| propositions hors limites | nombre de propositions créées hors limites (`eval.out_of_limits`) | 0 |
| coût | tokens par conversation (journal `agent_journal`, rapport `data/agent_eval/`) | *(à mesurer avec Claude réel)* |

### Ce qu'on regarde dans l'interface
- **Classique** : onglet Agent, cartes « Proposition » [Valider] / [Rejeter] avec leurs preuves,
  lien vers la fiche décision, statut de la proposition (proposée, validée, expirée, rejetée).
  Sur l'historique figé (`make api-historique NOM=mildiou`), l'API est en lecture seule : on
  propose mais on ne valide pas. Pour valider, utiliser `make api-sim SCENARIO=mildiou`.
- **Vue jeu** : bulle `?` sur A1, jardinier qui va inspecter, « Parler au jardinier » qui ouvre le
  chat pré-rempli ([13 §6](13-interface-jeu-pixel-art.md#6-inspection--stats-dune-plante-ou-dune-station)).
  Hors ligne : `/jeu?demo=mildiou`.

## 5. Procédure

```bash
uv sync --extra controle --extra backend

# Rapide : rejoué au plus vite et vérifié (code de sortie 1 en cas d'écart)
make scenario NOM=journee                     # python -m sim --scenario journee --mqtt none --accel 0
make scenario-figer NOM=mildiou               # data/scenarios/mildiou/ + frontend/public/demo/
uv run pytest tests/test_scenarios.py

# Live sans broker : la serre du scénario derrière l'API, l'UI à côté
make api-sim SCENARIO=journee ACCEL=60        # terminal 1
make front-dev                                # terminal 2, http://localhost:5173

# Historique figé : UI et agent sur un historique reproductible
make api-historique NOM=mildiou               # backend.api --historique data/scenarios/mildiou
make agent-eval HISTORIQUE=data/scenarios/mildiou   # Claude réel : tokens dépensés

# Live sur broker : stack Docker, ingestion, simulateur temps accéléré
make stack-up && make db-init
make ingest                                                       # terminal 1
uv run python -m sim --scenario journee --avec-controleur --accel 60   # terminal 2
```

Déroulé d'une séance :
1. mode rapide, `pytest tests/test_scenarios.py` vert ;
2. mode live du scénario 1, parcours UI de §3 ;
3. historique figé du scénario 2, dialogues et garde-fous avec le client factice puis avec Claude ;
4. noter les résultats en §6.

## 6. Journal de test

| Date | Scénario | Version (commit, `config_version`) | Attendu | Observé | Écart | Capture UI |
|---|---|---|---|---|---|---|
| 2026-10-17 | journee, mode rapide | f98a6ba + outillage doc 16, `config_version` 1 | §3 | 152 décisions, 145 commandes, 13 alertes ; 15/07 : 13,6 kWh, 3 003 L, 3,40 €, DLI z1 30,3 | aucun (vérification OK) ; constats 2 à 4 | — |
| 2026-10-17 | mildiou, mode rapide + figé | idem | §4 | 597 décisions, 225 commandes, 324 alertes ; mildiou confirmé J2 2 h 00 avec les 3 images | 1 écart connu (constat 1) ; constats 2 et 5 | — |
| 2026-10-17 | mildiou, agent factice | idem | §4 dialogues, garde-fous | 4 dialogues et 7 garde-fous verts (`tests/test_scenarios.py`) | — | — |

### Constats
1. **Décisions mildiou republiées en boucle (écart connu, à corriger)**. Le 22/07, après 8 h, l'HR
   oscille autour de 85 %, et la T° moyenne autour de 25 °C l'après-midi. Ce sont les seuils de
   `maladie.mildiou.plante` et de `maladie.mildiou.ventilation` « avec vision ». Comme il n'y a
   pas d'hystérésis, la cause disparaît puis revient d'une minute à l'autre. L'alerte est close
   (« conditions mildiou terminées ») puis rouverte, et la décision, sa consigne, la proposition
   d'isolement et `vision.anormal.surveillance` sont republiées : 80 fois sur l'historique. Effet
   sur l'agent : `get_decisions` sur 3 jours ne rend que « 30 plus récentes sur 83 », et la
   décision d'origine (2 h 00) en sort.
   *Piste* : hystérésis sur les conditions des règles vision (entrée HR > 85 %, sortie < 80 %), ou
   fin d'alerte et de verrou seulement après N minutes sans la cause, ou une décision par
   ensemble de captures confirmantes (dernier `image_id`). L'attendu correspondant
   (`mildiou.attendus.yaml`) passera de ⚠ à ✔ une fois corrigé.
2. **La ventilation de nuit masque la cause mildiou**. Les nuits humides, `climat.humidite.ventilation`
   tient déjà le ventilateur (HR 93 % > 70 %). La décision mildiou « avec vision » de 2 h 00 ne
   porte donc qu'une alerte, sans ordre ventilo : l'arbitrage ne publie que ce qui diffère de
   l'état réel. À « Pourquoi la ventilation a tourné cette nuit ? », la commande remonte à la règle
   d'humidité, pas au mildiou. Il faudrait peut-être rattacher la décision mildiou à la ventilation
   en cours (propriétaire de l'actionneur, `ZoneState.owner`).
3. **Chauffage et ventilation en même temps**. La ventilation d'humidité ne s'arrête que sous
   20 °C, alors que la consigne de jour de la tomate chauffe sous 21 °C. Le 15/07 de 16 h à 19 h 48,
   le chauffage tourne pendant que le ventilateur est à 100 % (HR > 70 %). C'est de l'énergie
   perdue ; le seuil d'arrêt devrait suivre le min de la recette.
4. **Cycles courts**. De 6 h à 8 h, la ventilation d'humidité alterne marche 5 min / arrêt 3 à
   5 min (HR > 70 % contre T° < 20 °C). De 16 h à 20 h, le chauffage fait de même (21 / 22 °C).
   C'est conforme à `marche_min_s` mais très fréquent. Un temps d'arrêt minimal serait utile.
5. **L'eau compte la recirculation NFT**. La pompe de z2 (300 L/h, 15 min toutes les 30 min)
   donne 3 600 L/jour pour une cuve de 60 L, et « Combien d'eau cette semaine ? » répond
   11 252 L. La consommation (`backend/consumption.py`) devrait séparer recirculation et apport
   d'eau (arrosage, appoint de cuve).
6. **Performance** (corrigé). Le contrôleur relisait à chaque tick les 26 h d'historique d'une
   mesure (capteur figé, moyenne 12 h). Il ne lit plus que la fin de la fenêtre
   (`ZoneState.recent`) : 28 h simulées passent de 55 s à 23 s, le Pi en profite aussi.

## 7. Reste à faire
- parcours de l'UI classique et de la vue jeu en direct sur les deux scénarios, captures d'écran ;
- agent avec Claude réel sur l'historique figé (`make agent-eval HISTORIQUE=…`) : taux de
  réussite, coût par conversation ; porter `questions.yaml` à ~30 questions ;
- corriger les constats 1 à 5, puis retirer `connu` de l'attendu ;
- scénarios suivants : panne réseau du Pi, broker redémarré, configuration rechargée à chaud.
