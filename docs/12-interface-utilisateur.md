# 12 — Interface utilisateur et API

Interface web pour **constituer sa serre** (zones, emplacements, plantes, pots, mode de culture, capteurs, actionneurs), **suivre** mesures, images et consommations, **comprendre** les décisions (preuves vision + capteurs, arbre des actions) et **dialoguer** avec l'agent.

> Statut : **implémenté** (G2, §7) : API REST complète sous `/api`, relais `WS /ws/live`, SPA React des sept écrans, authentification optionnelle ; vue jeu `/jeu` ([13](13-interface-jeu-pixel-art.md)) ; Alembic à venir. Modèle de données : [09](09-modele-gestion-serre.md) ; décisions et arbre : [10](10-decisions-tracabilite.md) ; agent : [11](11-agent-decision.md) ; vue « jeu » en pixel art (construction de la serre, jardinier animé, stats en bulles) : [13](13-interface-jeu-pixel-art.md).

## 1. Architecture

```
 Navigateur ── React + Vite (SPA) ──┬── REST  /api/…        ──┐
                                    ├── WS    /ws/live       ──┤
                                    └── SSE   /api/agent/chat──┤
                                                               ▼
                         backend/ (FastAPI, uvicorn) ── PostgreSQL + TimescaleDB
                           ├─ api/        routes REST, validation pydantic
                           ├─ db/         modèles, migrations (Alembic)
                           ├─ ingestion/  abonné MQTT → tables (common.mqtt.decode)
                           ├─ live/       pont MQTT → WebSocket
                           ├─ agent/      boucle Claude + outils (doc 11)
                           └─ config/     export serre.yaml vers le Pi (doc 09 §8)
                                    │ MQTT
                                    ▼
                           mosquitto (Pi) ── controller, camera_service, ESP32
```

- Hébergé sur le **serveur / PC** (pas sur le Pi) : si le serveur tombe, la serre continue ([01 §1](01-architecture.md#principes)).
- En production, FastAPI sert le build statique du front (`frontend/dist`) : un seul processus, un seul port.
- Accès local (LAN) ; authentification simple par mot de passe + jeton de session dès qu'une action peut être déclenchée depuis l'UI : si `SERREIA_UI_PASSWORD` est défini, toute requête autre qu'une lecture (GET) demande `Authorization: Bearer <jeton>` (`POST /api/auth/login`) ; seuls la connexion et le dépôt d'images du `camera_service` (`POST /api/images`) restent ouverts. Jetons en mémoire, 7 jours.

### Stack front
| Besoin | Bibliothèque |
|---|---|
| Base | React 18, TypeScript, Vite |
| Données serveur, cache, invalidation | TanStack Query |
| Navigation | React Router |
| Plan de serre (glisser-déposer) | grille CSS + glisser-déposer HTML5 natif |
| Arbre des actions | React Flow (`@xyflow/react`) + dagre (mise en page), chargé à la demande |
| Courbes temps réel / consommation | Recharts 3 |
| Formulaires | React Hook Form + Zod (schémas écrits à côté des formulaires, à partir des types générés) |
| Composants | composants façon shadcn/ui (Radix Dialog / Tabs / Collapsible) copiés dans `src/components/ui/` + Tailwind 4 |
| Vue jeu pixel art ([13](13-interface-jeu-pixel-art.md)) | Phaser 3, easystarjs, mitt (chargés à la demande) |
| Types API | `openapi-typescript` à partir de `/openapi.json` (`make openapi`) : corps des requêtes ; les réponses (dicts) sont typées dans `src/api/types.ts` |

## 2. Écrans

### 2.1 Constructeur de serre
Plan en grille par zone ; on ajoute des zones, des emplacements, puis on dépose des plantes.

```
┌ Serre « Maison » ─────────────────────────────────────────────┐ ┌ Emplacement z1-A1 ──────────────┐
│ [+ Zone]  z1 (terre) │ z2 (hydro NFT)                          │ │ Plante   tomate · Cœur de bœuf  │
│ ┌────────────────────────────────────────┐                     │ │ Stade    floraison ▾            │
│ │  A1 🍅●  A2 🍓●  A3 ·    A4 ·            │  ● sain             │ │ Recette  tomate-standard ▾      │
│ │  B1 ·    B2 🍅▲  B3 ·    B4 ·            │  ▲ à surveiller     │ │ Contenant pot 11 L plastique    │
│ │                         📷 cam-z1-a      │  ✖ malade           │ │ Culture  terre ▾                │
│ └────────────────────────────────────────┘                     │ │ Capteurs SHT41, BMP280, GY-302  │
│ Palette : [Tomate] [Fraisier] [Poivron] [+ autre espèce]        │ │ Caméra   cam-z1-a (région ✓)    │
└────────────────────────────────────────────────────────────────┘ │ [Historique] [Décisions] [Photos]│
                                                                   └──────────────────────────────────┘
```

Fonctions :
- créer / renommer / supprimer zones et emplacements (grille rangées × colonnes ou étagères) ;
- fiche emplacement : plante (espèce issue de la taxonomie ou libre, variété, dates, stade, recette), contenant (type, volume, matériau), **mode de culture** ;
- déplacer une plante (clôture l'affectation, [09 §1](09-modele-gestion-serre.md#1-hiérarchie)) ;
- **éditeur de régions caméra** : sur la dernière image de la caméra, dessiner le rectangle de chaque emplacement ;
- contrôles de cohérence affichés en bandeau (emplacement hydro sans capteur pH/EC, recettes incompatibles dans une zone, espèce hors taxonomie) ;
- bouton **« Publier la configuration »** → nouvelle `config_version` envoyée au Pi, avec un diff par rapport à la précédente. Le backend existe déjà (`backend/config/export.py`, [09 §8](09-modele-gestion-serre.md#8-configuration-exportée-vers-le-contrôleur)) : validation, versionnement selon le contenu, table `config_export`, installation atomique ou rsync. L'API n'aura qu'à l'appeler ; le diff se calcule entre deux lignes de `config_export`. Les contrôles de cohérence du bandeau sont ceux de `edge/controller/coherence.py`.

### 2.2 Équipements
Tableaux capteurs / actionneurs / caméras / nœuds ESP32 :
- capteur : modèle, mesures, nœud, zone, emplacements couverts, plage physique, **date du dernier étalonnage** (rappel en orange au-delà de l'échéance) ;
- actionneur : type (`Actuator`), puissance W, débit L/h, PPFD max, durée max, état courant (`etat/<actionneur>`) ;
- nœud : `online` / `offline` (topic `status`), dernière mesure reçue ;
- bouton de commande manuelle (crée une décision `manuel`, passe par `safety.py`).

### 2.3 Tableau de bord
Par zone : tuiles mesures courantes vs plage de consigne (vert / orange / rouge), mini-courbes 24 h, états des actionneurs, dernière image avec la classification de chaque emplacement superposée, alertes actives, décisions en attente de validation.

### 2.4 Consommation
Énergie (kWh, €), eau (L), lumière (DLI obtenu vs cible), intrants (mL) — par jour / semaine / mois, empilés par actionneur ou par zone ([09 §5](09-modele-gestion-serre.md#5-consommations)). Mention « estimé » tant qu'aucun wattmètre n'est déclaré.

### 2.5 Journal des décisions et fiche décision
Liste filtrable (zone, emplacement, type routine / exceptionnelle / sécurité / manuelle / agent, niveau, statut, règle, période).

```
┌ dec-20261012-0231-z1-007 · niveau 1 · règle maladie.mildiou.ventilation v3 · exécutée ─────────────┐
│ HR > 90 % depuis 11,2 h à 17,8 °C et mildiou détecté sur z1-A1 (conf. 0,81, 3 images) → ventilation │
├ Vision ─────────────────────────────┬ Capteurs ──────────────────────────────────────────────────────┤
│ [image 02:00] [Grad-CAM]            │ Humidité   ▁▂▄▆██████████  seuil 90 % ── durée au-dessus 11,2 h │
│ espèce  tomate      0,97            │ T° air     ▅▄▄▃▃▃▃▃▃▃▃▃▃▃  moyenne 12 h 17,8 °C                  │
│ santé   anormal     0,88            │ Prévision  HR +6 h = 93 % (gru-v1)                              │
│ classe  mildiou     0,81  ×3 conf.  │ Consigne   floraison : HR 55–70 %                              │
├ Actions ────────────────────────────┴────────────────────────────────────────────────────────────────┤
│ ✔ ventilo on 900 s (confirmé 02:31:04)   ✔ alerte warning   ⏳ isoler plante A1  [Valider] [Rejeter]  │
│ config v12 · [Demander à l'agent]                                                                    │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

Les courbes capteurs sont centrées sur l'instant de la décision (± 12 h) et surlignent la fenêtre réellement utilisée par la règle. « Demander à l'agent » ouvre le chat pré-rempli avec l'id de décision.

### 2.6 Arbre des actions
Vue React Flow de l'arbre [10 §6](10-decisions-tracabilite.md#6-arbre-des-actions) : Serre → Zones → `Routines` / `Exceptionnelles` / `Sécurité` / `Manuelles` → décisions → actions.
- code couleur par statut (exécutée, proposée, rejetée, bloquée) et icône par type d'actionneur ;
- branches routinières repliées par défaut (agrégées « ×14 cycles ») ; exceptionnelles dépliées ;
- curseur temporel (24 h, 7 j) ; clic sur une décision → fiche décision ; sur une action → commande MQTT et état confirmé.

### 2.7 Agent
Chat en streaming ([11](11-agent-decision.md)) :
- les appels d'outils sont affichés de façon repliable (« a consulté : décisions z1 02:00–03:00 ») ;
- les propositions apparaissent comme des **cartes** (actionneur, durée, justification, preuves cliquables, estimation de consommation) avec **Valider / Rejeter** (motif de rejet optionnel) ;
- références cliquables (`dec-…`, `z1-A1`, `image_id`) vers les écrans correspondants ;
- bandeau « agent indisponible » si l'API ne répond pas, le reste de l'UI restant utilisable.

## 3. API REST (FastAPI)

Préfixe `/api`. Schémas pydantic partagés avec `common/` quand ils existent (`SensorReading`, `VisionResult`, `Command`…).

| Ressource | Routes |
|---|---|
| Authentification | `GET /auth` (`{requise, utilisateur}`), `POST /auth/login`, `POST /auth/logout` |
| Serre et structure | `GET/POST /serres`, `GET/PATCH/DELETE /serres/{id}` ; idem `/zones`, `/emplacements`, `/cuves` ; `GET /zones/{id}/plan` (grille du constructeur : plante active, contenant, capteurs, caméras, dernière classification) |
| Plantes | `GET/POST /plantes` (`?actives=1&zone=`, POST avec `emplacement` pour planter directement), `GET/PATCH /plantes/{id}`, `POST /plantes/{id}/deplacer` (`emplacement: null` : retirer), `GET /plantes/{id}/historique` |
| Contenants, recettes | `/contenants`, `/recettes` (CRUD ; une recette est validée comme par le contrôleur) |
| Équipements | `/capteurs` (canaux ; échéance d'étalonnage calculée), `/actionneurs` (+ état courant), `/cameras` (CRUD), `PUT /cameras/{id}/regions`, `GET /cameras/{id}/derniere-image`, `GET /noeuds` |
| Configuration | `GET /config/coherence`, `GET /config/versions`, `GET /config/diff?de=&a=` (défaut : dernière version publiée → brouillon), `POST /config/publier` → `config_version` (`backend.config.export`) |
| Mesures | `GET /mesures?zone=&type=&emplacement=&debut=&fin=&agregat=`, `GET /zones/{id}/tableau` (tuiles vs consigne, actionneurs, dernière image, alertes, propositions) |
| Vision | `GET /vision?emplacement=&zone=&debut=&fin=`, `GET /images/{image_id}` (+ `?gradcam=1`), `POST /images` (dépôt du `camera_service`, `edge/archive.py`) |
| Décisions | `GET /decisions?…`, `GET /decisions/{id}`, `POST /decisions/{id}/valider`, `POST /decisions/{id}/rejeter` |
| Actions | `GET /actions/arbre?zone=&debut=&fin=`, `POST /actions/manuelle` |
| Consommation | `GET /consommation?zone=&periode=jour\|semaine\|mois&jour=` (totaux, par actionneur, par jour, DLI vs cible, `estime`) |
| Alertes | `GET /alertes?actives=1`, `POST /alertes/{id}/acquitter` |
| Agent | `GET /agent/statut`, `POST /agent/chat` (SSE), `GET /agent/conversations`, `GET /agent/conversations/{id}` |
| Temps réel | `WS /ws/live` (hors `/api`) : messages `{kind, zone, subject, payload}` relayés depuis MQTT (capteur, vision, etat, status, alerte, decision, cmd) |

`POST /api/decisions/{id}/valider` et `POST /api/actions/manuelle` sont les **seuls** points d'entrée qui agissent sur la serre depuis le serveur. Ils ne publient pas de `Command` : ils publient la `Decision` (statut `validee`, `ordres` structurés) sur `serre/<zone>/decision`, et le contrôleur l'exécute via `safety.py` puis émet les commandes ([10 §4](10-decisions-tracabilite.md#4-cycle-de-vie)).

Une modification de structure (zones, plantes, équipements, régions) ne touche que la base : le contrôleur la voit à la publication (`POST /api/config/publier`), qui installe le nouveau `serre.yaml` (`python -m backend.api --install <chemin>` et/ou `--rsync <destination>`).

## 4. Organisation du dépôt

```
backend/
├── api/                 # app.py (create_app, montage du front), auth.py, deps.py, crud.py
│   │                    # serres.py, plantes.py, equipements.py, config.py, mesures.py,
│   │                    # consommation.py, alertes.py, decisions.py, actions.py, agent.py, live.py
│   ├── sim.py           # serre simulée derrière l'API (--mqtt sim)
│   └── __main__.py      # python -m backend.api
├── live/bridge.py       # LiveHub : pont MQTT → WebSocket
├── db/                  # models.py (SQLAlchemy), session.py, seed.py, timescale.sql
├── ingestion/           # mqtt_ingest.py
├── agent/               # loop.py, tools.py, prompts.py…
└── config/              # export.py (serre.yaml versionné)
frontend/
├── package.json  vite.config.ts  index.html  playwright.config.ts  e2e/
└── src/
    ├── api/             # client.ts, hooks.ts (TanStack Query), sse.ts, types.ts, schema.d.ts (généré)
    ├── pages/           # Constructeur, Equipements, Dashboard, Consommation, Decisions, FicheDecisionPage, Arbre, Agent
    ├── components/      # PlanSerre, FicheEmplacement, EditeurRegions, ConfigPublication, FicheDecision,
    │                    # CarteProposition, CommandeManuelle, Charts, ImageAnnotee, ui/…
    └── live/            # LiveProvider (WebSocket, invalidation des requêtes)
```

La vue jeu est dans `src/game/` ([13 §11](13-interface-jeu-pixel-art.md#11-implémentation)). Pas d'Alembic : `init_db` crée les tables manquantes ([09 §7](09-modele-gestion-serre.md#7-persistance)).

## 5. Développement sans matériel

Tout l'écran est développable avec le **simulateur** ([06 §5](06-capteurs-controle.md#5-simulateur--sim)), de deux façons :

- **Sans broker** : `make api-sim` (`python -m backend.api --mqtt sim`) fait tourner simulateur et contrôleur dans le processus de l'API, sur un bus en mémoire, avec l'ingestion et le relais temps réel branchés. Les 24 dernières heures sont rattrapées au démarrage (`--prefill-h`), puis la simulation avance en temps réel (`--accel`) ; l'horloge de l'API est celle de la simulation. `--panne` reprend les pannes de `sim/faults.py`, par exemple `--panne valeur:z1/humidite=92@0 --panne maladie:z1-A1/tomate/maladie/mildiou@15` pour une proposition d'isolement à valider. Base SQLite `data/serre_sim.db`.
- **Scénario scripté** ([16](16-test-systeme-simule.md)) : `make api-sim SCENARIO=journee` joue le scénario depuis son début (`--scenario`, `ACCEL=60` par défaut), base `data/serre_sim_<nom>.db` recréée à chaque lancement. `make api-historique NOM=mildiou` (`--historique`) sert l'historique figé d'un scénario en lecture seule, horloge arrêtée à sa fin.
- **Avec la stack** : `docker compose up` (mosquitto, TimescaleDB), `make ingest`, `make sim-live` (simulateur + contrôleur sur le broker), `make api`.

Puis `make front-dev` (Vite, proxy `/api` et `/ws` vers `:8000`) ou `make front-build` : FastAPI sert alors `frontend/dist` sur le même port. Le simulateur ne produit pas de JPEG : les images s'affichent comme « non reçues » tant qu'un vrai `camera_service` n'envoie rien.

## 6. Tests

| Niveau | Contenu |
|---|---|
| Backend | pytest sur SQLite (`seeded_db`) avec le bus en mémoire et l'ingestion : CRUD et refus (`tests/test_api_serre.py`), cohérence (hydro sans pH/EC), diff et publication versionnée, équipements, tableau de bord vs consignes, images (traversée de chemin refusée), consommation, alertes (`tests/test_api_suivi.py`), authentification, relais `WS /ws/live`, service du front (`tests/test_api_auth_live.py`), décisions et agent (`tests/test_api.py`, `tests/test_agent.py`) |
| Contrat | les décisions publiées par l'API passent `common.mqtt.decode` ; le relais ne transmet que des messages valides |
| Front | Vitest + Testing Library (`make front-test`) : plan et glisser-déposer, carte de proposition, fenêtre de règle et domaine des courbes, arbre (routines repliées), flux SSE, conversation stockée ; Playwright (`make e2e`, navigateur : `npx playwright install chromium`) : créer une zone → un emplacement → déposer une plante → publier la configuration → valider une proposition du simulateur, contre `python -m backend.api --mqtt sim` |
| Agent | jeu de questions de référence et tests de garde-fous ([11 §6](11-agent-decision.md#6-évaluation-de-lagent)), avec un client LLM factice en CI |

## 7. Implémentation et test sur PC

```bash
source .venv/bin/activate         # le Makefile appelle `python`
make setup front-install          # Python (extra backend) et dépendances npm
make api-sim                      # API + serre simulée sur :8000 (SQLite, sans Docker)
make api-sim SCENARIO=journee     # … ou un scénario scripté (doc 16), ×60 (ACCEL=…)
make api-historique NOM=mildiou   # … ou l'historique figé d'un scénario (make scenario-figer)
make front-dev                    # http://localhost:5173 (ou make front-build puis :8000)
make test front-test e2e          # pytest, Vitest, Playwright
SERREIA_UI_PASSWORD=… make api    # vraie serre (stack + psycopg), écritures authentifiées
make openapi                      # après un changement de route : types TypeScript régénérés
```

Dépannage : `make api` vise PostgreSQL (`$SERREIA_DB`) et demande `psycopg` (extra `backend`)
et la stack Docker ; sans elle, `make api-sim`. `address already in use` sur `:8000` : une
API tourne déjà (`ss -ltnp | grep :8000`, puis `kill <pid>`) ; Vite proxifie toujours vers
`:8000`, une seconde API sur `--http-port 8001` n'est donc pas vue par `make front-dev`.

Écarts assumés par rapport à la conception : plan de serre en grille CSS + glisser-déposer natif (React Flow seulement pour l'arbre) ; schémas Zod écrits à la main ; pas de `sse-starlette` (la réponse en flux de FastAPI suffit) ; le dépôt d'images `POST /api/images` s'ajoute aux routes prévues pour recevoir l'`Uploader` du service caméra.

Reste à faire : Alembic ; édition de `regles.yaml` depuis l'UI ; liste des capteurs couverts éditable dans la fiche capteur ; Grad-CAM produit côté service caméra ; dépôt d'images authentifié par un jeton propre au Pi.
