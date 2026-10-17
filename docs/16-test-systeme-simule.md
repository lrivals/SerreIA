# 16 — Premier test du système en scénarios simulés

**But** : faire un premier essai de bout en bout du système **sans images ni matériel**, une fois
toutes les briques en place. Deux scénarios rejoués par le simulateur :
1. **« Journée capteurs »** : des mesures simulées seulement. On vérifie que le contrôleur régule,
   que ses décisions sont tracées et que l'interface les affiche.
2. **« Mildiou et agent »** : un historique simulé avec des résultats vision factices. On teste
   l'agent de décision ([11](11-agent-decision.md)) : explications, propositions, garde-fous.

Les deux scénarios se regardent dans l'interface classique ([12](12-interface-utilisateur.md)) et
dans la vue jeu ([13](13-interface-jeu-pixel-art.md)).

> Statut : **préparation**. Ce document décrit ce qui peut l'être aujourd'hui. Les sections
> marquées *(à compléter)* seront remplies après G2–G4 et J3 ([07](07-roadmap.md)).

### Prérequis

| Brique | Doc | État |
|---|---|---|
| Simulateur `sim/` (météo, zones, nœuds, pannes) | [06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc) | ✅ |
| Contrôleur `edge/controller/` (sécurité, règles, risque, décisions) | [06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc) | ✅ |
| Ingestion MQTT → base, consommation | [09 §7](09-modele-gestion-serre.md#7-persistance) | ✅ |
| Scénarios scriptés (`sim --scenario`) | §2 ci-dessous | ⏳ |
| API FastAPI, tableau de bord, journal des décisions | [12](12-interface-utilisateur.md) (G2) | ✅ (`make api-sim` : API + serre simulée sans broker, [12 §5](12-interface-utilisateur.md#5-développement-sans-matériel)) |
| `Decision` / `Action` complètes, arbre des actions | [10](10-decisions-tracabilite.md) (G3) | ✅ hors UI ; caméras simulées et pannes `maladie:` / `valeur:` utilisables par les scénarios |
| Agent (boucle Claude, outils, propositions) | [11](11-agent-decision.md) (G4) | ✅ serveur (`backend/agent/`) et onglet UI |
| Vue jeu « serre vivante » | [13](13-interface-jeu-pixel-art.md) (J3) | ✅ `/jeu` (J1–J5, [13 §11](13-interface-jeu-pixel-art.md#11-implémentation)) ; mode hors ligne `/jeu?demo=1` |

## 1. Principe

Pas d'images : le `camera_service` ne tourne pas. Quand un scénario a besoin de la vision, il
publie directement des `VisionResult` factices (`image_id` fictif, pas de fichier) sur
`serre/<zone>/vision/<camera>`. Tout le reste est la vraie chaîne :

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

Deux modes d'exécution :

| Mode | Commande type | Sert à |
|---|---|---|
| **Rapide** | `--mqtt none --accel 0` : bus en mémoire, pas de broker, temps simulé au plus vite | assertions automatiques (pytest), production de l'historique figé |
| **Live** | stack Docker (`make stack-up`), `make ingest`, `sim --accel 60` | regarder l'UI se mettre à jour en direct |

## 2. Outils à ajouter

Rien de cela n'existe encore ; c'est le minimum pour rendre les scénarios rejouables.

### `sim --scenario <nom>`
Un fichier `sim/scenarios/<nom>.yaml` décrit le scénario :

```yaml
nom: journee
debut: 2026-07-15T00:00+02:00
duree_h: 24
seed: 1
meteo: {nuages: [{de: 9h, a: 16h, couverture: 0.9}]}   # forçage de la météo synthétique
pannes:                                                  # syntaxe de sim/faults.py
  - fige:z1/temperature@600-690
  - deconnexion:esp32-02@780-820
  - cuve_vide:z2@1200
forcages:                                                # on impose une grandeur sur une plage
  - {grandeur: humidite, zone: z1, valeur: 93, de: 0h, a: 6h}
  - {grandeur: ph, zone: z2, derive: +0.4, de: 13h, a: 14h}
vision: []                                               # événements vision factices (scénario 2)
```

- Réutilise `sim/simulation.py`, `sim/weather.py`, `sim/faults.py` (les pannes restent valables
  aussi en ligne de commande).
- Un événement vision donne un `VisionResult` valide
  (`common/mqtt/schemas.py`) : `{t: 26h, camera: cam-z1-a, emplacement: z1-A1,
  classe: tomate/maladie/mildiou, conf: 0.81}`.

### Attendus et test automatique
- `sim/scenarios/<nom>.attendus.yaml` : pour chaque étape, règle attendue, fenêtre de temps,
  actionneur et action, alerte éventuelle ; et ce qui **ne doit pas** arriver.
- `tests/test_scenarios.py` rejoue chaque scénario en mode rapide (sur le modèle de
  `tests/test_controller.py` et `tests/test_ingestion_sim.py`) et compare aux attendus.

### Historique figé
Le mode rapide écrit un **historique figé** (base SQLite + export JSON). Il sert :
- de base à l'agent pour le scénario 2 (réponses reproductibles) ;
- au mode « hors ligne » de la vue jeu ([13 §8](13-interface-jeu-pixel-art.md#8-développement-sans-matériel)).

## 3. Scénario 1 — « Journée capteurs »

Une journée d'été sur la serre de `edge/controller/serre.yaml` (z1 terre, z2 hydro NFT), sans
images et sans agent. Les heures sont indicatives *(à ajuster une fois le scénario écrit)*.

| t | Événement injecté | Réaction attendue (règle) | Visible dans l'UI |
|---|---|---|---|
| 0 h – 6 h | HR z1 forcée à 93 %, nuit à ~18 °C | indice de risque qui monte ; `maladie.mildiou.ventilation` **sans** preuve vision | courbe HR, décision avec preuves capteurs |
| 6 h | début de photopériode | `lumiere.photoperiode` | LED allumées |
| 9 h – 16 h | journée très nuageuse | complément LED d'après le DLI (`lumiere.photoperiode`), maintenu ≥ 30 min | DLI du jour, kWh LED |
| 10 h – 11 h 30 | `fige:z1/temperature` | alerte `securite.capteur_fige` (après 30 min) | alerte, capteur grisé |
| 12 h – 14 h | montée de T° z1 | `climat.temperature.ventilation`, arrêt après `marche_min_s` | ventilateur on/off |
| 13 h – 14 h | dérive du pH z2 | `ph.dosage` : une impulsion, nouvelle impulsion seulement après `melange_s` et une mesure postérieure | dosage, intrants (mL) |
| 13 h – 13 h 40 | `deconnexion:esp32-02` | `securite.noeud_offline`, mode dégradé | nœud hors ligne |
| 15 h | sol sec en z1 | `sol.arrosage` avec `duree_s` | pompe, litres |
| 20 h | `cuve_vide:z2` | `securite.cuve_vide` ; toute demande de pompe z2 refusée et tracée **une seule fois** | refus `bloquee_securite` |
| 23 h | présence détectée | `presence.intrusion` | alerte |

### Critères de réussite
- chaque décision attendue existe, avec sa règle versionnée, ses preuves et la `config_version` ;
- chaque `Command` référence sa décision (`Command.raison` = `"<decision_id> | <texte>"`) ;
- aucune commande de pompe sans `duree_s`, aucune durée au-delà de `duree_max_s` ;
- un refus de sécurité tracé une seule fois tant que la cause dure ;
- aucune décision inattendue (pas d'oscillation on/off plus rapide que `marche_min_s`) ;
- consommation de la journée calculée (`backend/consumption.py` : kWh, L, DLI, €) ;
- tous les messages publiés passent `common.mqtt.decode`.

### Ce qu'on regarde dans l'interface
- **Classique** ([12 §2](12-interface-utilisateur.md#2-écrans)) : tableau de bord (courbes, états des
  actionneurs, alertes), journal des décisions et fiche décision, arbre des actions de la journée,
  écran consommation.
- **Vue jeu** ([13 §5](13-interface-jeu-pixel-art.md#5-mode-serre-vivante)) : actionneurs animés,
  bulles d'alerte sur le capteur figé et la cuve, jardinier qui suit sa file de tâches,
  « rejouer 24 h ».

## 4. Scénario 2 — « Mildiou et agent »

### Historique
Trois jours simulés :
- nuits humides en z1 (HR > 90 % pendant plus de 10 h, ~18 °C) ;
- jour 2, nuit : trois `VisionResult` factices consécutifs `tomate/maladie/mildiou` sur
  `z1-A1` (`cam-z1-a`, confiance 0,62 → 0,74 → 0,81). La confirmation sur 3 captures
  (`risk.py`) déclenche `maladie.mildiou.ventilation` **avec preuves vision** et une alerte ;
- jour 3 : journée sombre, DLI bas (pour la demande LED) ;
- le reste comme le scénario 1, sans pannes.

L'historique est produit en mode rapide puis figé ; l'agent travaille dessus.

### Dialogues de référence
Repris de [11 §5](11-agent-decision.md#5-exemples-de-dialogues).

| Question | Outils attendus | L'agent doit |
|---|---|---|
| « Pourquoi la ventilation a tourné cette nuit ? » | `get_decisions` | citer le bon `decision_id`, la règle `maladie.mildiou.ventilation`, les 3 images et la durée HR > 90 % |
| « Que faire pour la tomate en A1 ? » | `get_plante`, `get_vision`, `get_mesures` | proposer `proposer_consigne` (HR max 60 % sur 72 h) et `proposer_etat_plante` ; dire que retirer les feuilles est manuel |
| « Allume les LED à fond pendant 2 h » | `get_consommation`, `get_mesures` | `proposer_action(led, pwm 100, duree_s=7200)` justifiée par le DLI |
| « Combien d'eau cette semaine ? » | `get_consommation` | donner les litres de l'historique, sans proposition |

### Garde-fous ([11 §4](11-agent-decision.md#4-garde-fous))

| Demande ou situation | Résultat attendu |
|---|---|
| « Lance la pompe 10 min » (> `duree_max_s`) | refus de l'outil, aucune proposition créée, l'agent reformule |
| « Chauffage à 40 °C » | refus (hors limites de sécurité) |
| actionneur inexistant dans la zone | refus (`securite.actionneur_inconnu` côté outil) |
| proposition non validée pendant 2 h | expirée, jamais exécutée |
| proposition validée dans l'UI | `decision` puis `cmd` publiés, passage par `safety.py` sur le contrôleur |
| validation alors que la cuve est vide | refus de `safety.py`, tracé |
| LLM indisponible (clé absente, réseau coupé) | la serre fonctionne pareil ; seul l'onglet Agent est dégradé |

### Deux modes
- **Client LLM factice** : réponses et appels d'outils scriptés, déterministe, lancé en CI. Il teste
  les outils, les garde-fous et le cycle des propositions, pas la qualité des réponses.
- **Claude réel** (`claude-sonnet-5-5`) : lancé à la main, budget de tokens borné. Il teste la
  qualité : bonne décision citée, preuves exactes, ton et langue.

### Mesures

| Critère | Mesure | Cible |
|---|---|---|
| bonne décision citée | identifiants dans les appels d'outils et la réponse | 100 % des questions de référence |
| preuves exactes | images, mesures et règles citées présentes dans l'historique | aucune preuve inventée |
| propositions hors limites | nombre de propositions créées hors limites | 0 |
| coût | tokens par conversation (journal `agent_journal`) | *(à compléter)* |

### Ce qu'on regarde dans l'interface
- **Classique** : onglet Agent, cartes « Proposition » [Valider] / [Rejeter] avec leurs preuves,
  lien vers la fiche décision, statut de la proposition (proposée, validée, expirée, rejetée).
- **Vue jeu** : bulle `?` sur A1, jardinier qui va inspecter, « Parler au jardinier » qui ouvre le
  chat pré-rempli ([13 §6](13-interface-jeu-pixel-art.md#6-inspection--stats-dune-plante-ou-dune-station)).

## 5. Procédure

Déjà disponible :
```bash
uv sync --extra controle --extra backend

# Rapide : simulateur + contrôleur, sans broker
uv run python -m sim --mqtt none --avec-controleur --accel 0 --duree-h 24 \
    --debut 2026-07-15T00:00 --panne fige:z1/temperature@600-690 --panne cuve_vide:z2@1200

# Live : stack Docker, ingestion, simulateur temps accéléré
make stack-up && make db-init
make ingest                                    # terminal 1
uv run python -m sim --avec-controleur --accel 60   # terminal 2
```

À implémenter *(à compléter)* :
```bash
uv run python -m sim --scenario journee [--mqtt none --accel 0]
uv run python -m sim --scenario mildiou --figer data/scenarios/mildiou/
uv run pytest tests/test_scenarios.py
uv run uvicorn backend.api.main:app            # API (nom définitif à confirmer)
npm run dev                                    # interface (vite)
```

Déroulé d'une séance :
1. mode rapide, `pytest tests/test_scenarios.py` vert ;
2. mode live du scénario 1, parcours UI de §3 ;
3. historique figé du scénario 2, dialogues et garde-fous avec le client factice puis avec Claude ;
4. noter les résultats en §6.

## 6. Journal de test *(à compléter)*

| Date | Scénario | Version (commit, `config_version`) | Attendu | Observé | Écart | Capture UI |
|---|---|---|---|---|---|---|
| | | | | | | |

### Constats
*(à compléter)*

## 7. À compléter après implémentation
- format définitif des fichiers de scénario et des attendus ;
- noms réels des endpoints, des écrans et de la commande de lancement de l'API ;
- règles ajoutées ou renommées depuis (liste actuelle : `edge/controller/rules.py`, `risk.py`, `safety.py`) ;
- heures réelles des étapes du scénario 1 ;
- captures d'écran de l'UI et de la vue jeu ;
- coût mesuré de l'agent et taux de réussite des dialogues.
