# 11 — Agent de décision conversationnel

L'utilisateur doit pouvoir **dialoguer** avec la serre : demander pourquoi une action a eu lieu, ce qu'il faut faire pour une plante, ou demander une intervention.
Choix retenu : **le contrôleur déterministe décide, un LLM explique et propose**.

> Statut : **implémenté** (G4, `backend/agent/`, §7) ; onglet Agent de l'UI fait avec G2 ([12 §2.7](12-interface-utilisateur.md#27-agent)). Dépend de [09](09-modele-gestion-serre.md) (modèle de serre) et [10](10-decisions-tracabilite.md) (journal de décisions).

## 1. Répartition des rôles

| Brique | Où | Décide ? | Rôle |
|---|---|---|---|
| `safety.py` (niveau 0) | Pi | **veto** | limites dures, appliquées à toute décision quelle que soit son origine |
| `rules.py`, `forecast.py` (niveaux 1–3) | Pi | **oui** | routines et actions exceptionnelles automatiques, avec preuves |
| **Agent LLM** | serveur (`backend/agent/`) | **non** | explique les décisions, répond aux questions, **propose** des actions ou des changements de consigne |
| Utilisateur | UI | oui | valide / rejette les propositions, agit manuellement |

Conséquences :
- le LLM n'est **jamais sur le chemin critique** : s'il est indisponible (API, réseau, quota), la serre fonctionne exactement pareil ; seul l'onglet « Agent » de l'UI est dégradé ;
- les décisions restent **reproductibles** (règles versionnées), le LLM n'ajoute qu'une couche de langage naturel ;
- l'agent ne voit que ce que les outils lui donnent (pas d'accès direct à la base ni à MQTT).

## 2. Architecture

```
  UI (onglet Agent) ──POST /api/agent/chat (SSE)──► backend/agent/
                                                  ├─ boucle tool use (Claude API)
                                                  ├─ outils lecture  ──► DB (serre, mesures, vision, décisions)
                                                  ├─ outils proposition ──► table decision (statut « proposee »)
                                                  └─ journal conversation + appels d'outils
  UI : carte « Proposition » [Valider] [Rejeter]
           │ valider
           ▼
  backend ──► serre/<zone>/decision (statut « validee », ordres) ──► controller (Pi) ──► safety.py ──► serre/<zone>/cmd/<actionneur> ──► ESP32
```

- Modèle : **Claude** via l'API Anthropic, `claude-sonnet-5-5` par défaut (bon compromis coût / qualité pour du tool use), `claude-opus-5-5` en option pour les analyses longues ; identifiant du modèle dans la configuration du backend.
- Le prompt système contient : description de la serre (résumé de la config [09 §8](09-modele-gestion-serre.md#8-configuration-exportée-vers-le-contrôleur)), liste des règles actives avec leur identifiant, rappel des garde-fous (§4), langue : français.
- Mise en cache du prompt système (description de la serre, règles) pour limiter le coût des conversations.

## 3. Outils exposés au LLM

### Lecture
| Outil | Paramètres | Retour |
|---|---|---|
| `get_serre` | — | zones, emplacements, plantes actives, équipements |
| `get_plante` | `emplacement` ou `plante_id` | fiche plante, recette, historique santé, dernières classifications |
| `get_mesures` | `zone`, `types[]`, `debut`, `fin`, `agregat` (`brut`, `moy_15min`, `moy_1h`) | séries (sous-échantillonnées, max ~500 points) |
| `get_vision` | `emplacement`, `debut`, `fin` | `VisionResult` résolus par emplacement, URI images et Grad-CAM |
| `get_decisions` | `zone`, `debut`, `fin`, `type`, `statut` | décisions avec preuves (doc 10 §2) |
| `get_arbre_actions` | `zone`, `debut`, `fin` | arbre doc 10 §6 |
| `get_consommation` | `zone`, `periode` | kWh, litres, DLI, intrants |
| `get_regle` | `regle_id` | description, seuils, version |

### Proposition (écriture différée)
| Outil | Paramètres | Effet |
|---|---|---|
| `proposer_action` | `zone`, `actionneur`, `action`, `valeur?`, `duree_s`, `justification`, `preuves_refs[]` | crée une `Decision` `niveau: agent`, `statut: proposee` |
| `proposer_consigne` | `recette_id`, `stade`, `grandeur`, `plage`, `duree_h?`, `justification` | crée une proposition de modification de recette (temporaire ou permanente) |
| `proposer_etat_plante` | `plante_id`, `etat_sante`, `justification` | ex. marquer « à surveiller » |
| `demander_capture` | `camera`, `justification` | capture immédiate ; **seule action exécutée sans validation** (sans effet sur les plantes) |

Les outils de proposition vérifient **avant** de créer la proposition : actionneur existant dans la zone, `duree_s` ≤ `duree_max_s` de l'actionneur, plage de consigne dans les limites de sécurité. Un refus est renvoyé au LLM comme résultat d'outil explicite, pour qu'il reformule.

## 4. Garde-fous

1. **Pas d'accès direct à `serre/+/cmd/+`** : seul le backend publie, et seulement après validation humaine.
2. **Liste blanche** d'actionneurs et de durées ; jamais de commande de pompe sans `duree_s` (déjà imposé par `Command.validate_for`).
3. **Double contrôle** : validation dans l'outil + `safety.py` sur le Pi au moment de l'exécution.
4. **Preuves obligatoires** : `proposer_*` exige une `justification` et au moins une référence (`decision_id`, `image_id`, série de mesures) ; l'UI les affiche sur la carte de proposition.
5. **Expiration** des propositions non validées (2 h par défaut) : une proposition périmée ne s'exécute pas.
6. **Journal complet** : messages, appels d'outils, arguments, résultats, modèle utilisé, tokens → table `agent_journal` ; consultable dans l'UI.
7. **Données** : seules des données de la serre sont envoyées à l'API (pas d'identifiants, pas de secrets) ; les images ne sont transmises que si l'utilisateur le demande explicitement (« regarde la photo de A1 »).
8. **Budget** : limite de tokens par conversation et par jour, configurable.

## 5. Exemples de dialogues

**Expliquer une décision**
> **Utilisateur** : Pourquoi la ventilation a tourné à 2 h 30 cette nuit ?
> *(agent → `get_decisions(zone="z1", debut="…T02:00", fin="…T03:00")`)*
> **Agent** : C'est la règle `maladie.mildiou.ventilation` (décision `dec-…-007`). Deux éléments l'ont déclenchée : la caméra `cam-z1-a` a classé la tomate en **A1** comme `tomate/maladie/mildiou` sur 3 images consécutives (confiance 0,81 sur la dernière, image `z1-a-20261012T020000`), et l'humidité était au-dessus de 90 % depuis 11 h avec 17,8 °C de moyenne, des conditions favorables au mildiou. Le ventilateur a tourné 15 min et une alerte a été émise. Une proposition d'isolement de la plante attend votre validation.

**Conseil sur une plante**
> **Utilisateur** : Que faire pour la tomate en A1 ?
> *(agent → `get_plante("z1-A1")`, `get_vision("z1-A1", …)`, `get_mesures("z1", ["humidite","temperature"], …)`)*
> **Agent** : Les trois dernières classifications confirment un mildiou probable, et la zone reste humide la nuit. Je propose : (1) abaisser la consigne d'humidité de z1 à 60 % max pendant 72 h ; (2) marquer la plante « malade ». Retirer les feuilles touchées est une intervention manuelle que je ne peux pas faire.
> *(agent → `proposer_consigne(...)`, `proposer_etat_plante(...)` → deux cartes « Valider / Rejeter » dans l'UI)*

**Demande d'action**
> **Utilisateur** : Allume les LED à fond pendant 2 h, il fait sombre.
> *(agent → `get_consommation`, `get_mesures(["lux"])`)*
> **Agent** : Le DLI du jour est à 11 mol/m² pour une cible de 20 : un complément est justifié. Proposition : LED z1 en PWM 100 % pendant 2 h (≈ 0,48 kWh).
> *(agent → `proposer_action(zone="z1", actionneur="led", action="pwm", valeur=100, duree_s=7200, …)`)*

## 6. Évaluation de l'agent

- Jeu de questions de référence (≈ 30) rejouées sur un historique figé issu du simulateur : l'agent doit citer la **bonne décision et les bonnes preuves** (vérifiable automatiquement via les appels d'outils et les identifiants cités).
- Tests de garde-fous : demandes hors limites (« pompe 10 min », « chauffage à 40 °C ») → l'outil refuse, aucune proposition créée.
- Suivi en production : taux de propositions validées / rejetées, motif de rejet saisi dans l'UI.

## 7. Implémentation et test sur PC

| Fichier | Rôle |
|---|---|
| `backend/agent/config.py` | `AgentConfig` : modèle (`SERREIA_AGENT_MODEL`, défaut `claude-sonnet-5-5`), effort (`medium`), budgets de tokens par conversation et sur 24 h, expiration des propositions (2 h), durée max par défaut des actionneurs sans `duree_max_s` (4 h) |
| `backend/agent/llm.py` | `ClaudeLLM` : streaming, cache du prompt système et de la conversation, repli serveur (`fallbacks: "default"`) si un classifieur refuse, toute panne de l'API → `AgentIndisponible` ; `ScriptedLLM` : LLM factice scripté pour la CI |
| `backend/agent/prompts.py` | prompt système en français, stable (cache) : rôle, garde-fous, résumé de la serre, catalogue des règles |
| `backend/agent/regles.yaml` | catalogue des règles (id, version, niveau, description, paramètres) ; un test vérifie que tout id de `edge/controller/` y figure |
| `backend/agent/tools.py` | les 12 outils du §3, arguments validés (pydantic), une transaction par appel, refus explicites ; propositions = `Decision` `niveau: agent`, `type: manuelle`, règles `agent.action` / `agent.consigne` / `agent.plante` / `agent.capture` |
| `backend/agent/consignes.py` | `proposer_consigne` validé : recette modifiée en base (ancienne valeur gardée), nouvelle `config_version` exportée ; consigne temporaire restaurée à l'échéance (ingestion, agent) |
| `backend/agent/loop.py` | `Agent.chat()` : boucle d'outils, événements `conversation` / `texte` / `outil` / `proposition` / `fin` / `erreur`, journal `agent_journal`, budgets |
| `backend/api/agent.py` | `POST /agent/chat` (SSE), `GET /agent/conversations`, `GET /agent/conversations/{id}` (messages, journal, propositions et leur statut) ; 503 sans agent |
| `backend/agent/fixtures.py`, `questions.yaml`, `eval.py` | historique de référence (mildiou z1-A1, nuits humides, journée sombre), 12 questions de référence, score automatique ; `make agent-eval` avec Claude réel |
| `backend/db/models.py` | tables `agent_conversation`, `agent_journal`, `agent_proposition` |

Choix d'implémentation :
- les propositions ne sont **pas publiées** à leur création (garde-fou 1) : elles sont écrites en base avec leurs actions `proposee` ; la validation passe par `POST /api/decisions/{id}/valider`, comme les propositions du contrôleur ;
- `demander_capture` crée une décision née `validee` (ordre `camera:<id>`) publiée sur `serre/<zone>/decision` : jamais de message sur `cmd/` depuis le serveur ;
- les références de preuves sont vérifiées (décision en base, `image_id` dans `vision_resultat`, série `mesure:<zone>/<type>/<debut>/<fin>` non vide) et converties en `PreuveVision` / `PreuveCapteur` ;
- `proposer_consigne` : le contrat MQTT n'a pas d'ordre de consigne, le serveur modifie la recette et exporte la configuration ; son installation sur le Pi reste `make config-export PI_CONFIG=…` ;
- aucune image n'est envoyée à l'API Claude : le serveur archive les JPEG reçus du service caméra (`POST /api/images`, doc 12) mais l'agent ne voit que les `image_id` et les résultats du classifieur ;
- les heures sont données à l'agent et rendues en heure locale de la serre ; l'heure courante précède chaque message utilisateur (le prompt système reste identique d'un message à l'autre).

Lancer : `make api` (agent actif si le paquet `anthropic` et des identifiants sont présents ; `python -m backend.api --agent none` sinon), puis l'onglet Agent de l'UI ([12](12-interface-utilisateur.md)) ou
`curl -N -X POST localhost:8000/api/agent/chat -H 'Content-Type: application/json' -d '{"message": "Pourquoi la ventilation a tourné cette nuit ?"}'`.

Tests : `tests/test_agent.py` (LLM scripté, aucun appel réseau) — outils de lecture sur l'historique, garde-fous (pompe 10 min, chauffage 40 °C, actionneur absent, pompe sans durée, référence inventée → refus, rien de créé), propositions, expiration, validation par l'API, consigne appliquée puis restaurée, boucle (journal, reprise de conversation, budget, LLM indisponible), SSE.

Reste à faire : onglet Agent et cartes « Proposition » (doc 12) ; motif de rejet et taux de validation dans l'UI ; images transmises sur demande explicite quand le serveur les stockera (garde-fou 7) ; questions de référence portées à ~30 sur l'historique figé du scénario 2 (doc 16 : `make agent-eval HISTORIQUE=data/scenarios/mildiou`, déjà joué avec le client factice) ; mesure du coût réel par conversation.
