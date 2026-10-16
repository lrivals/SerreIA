# 12 — Interface utilisateur et API

Interface web pour **constituer sa serre** (zones, emplacements, plantes, pots, mode de culture, capteurs, actionneurs), **suivre** mesures, images et consommations, **comprendre** les décisions (preuves vision + capteurs, arbre des actions) et **dialoguer** avec l'agent.

> Statut : **conception**. Modèle de données : [09](09-modele-gestion-serre.md) ; décisions et arbre : [10](10-decisions-tracabilite.md) ; agent : [11](11-agent-decision.md) ; vue « jeu » en pixel art (construction de la serre, jardinier animé, stats en bulles) : [13](13-interface-jeu-pixel-art.md).

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
- Accès local (LAN) ; authentification simple par mot de passe + jeton de session dès qu'une action peut être déclenchée depuis l'UI.

### Stack front
| Besoin | Bibliothèque |
|---|---|
| Base | React 18, TypeScript, Vite |
| Données serveur, cache, invalidation | TanStack Query |
| Plan de serre (glisser-déposer) et arbre des actions | React Flow |
| Courbes temps réel / consommation | Recharts |
| Formulaires | React Hook Form + Zod (schémas générés depuis l'OpenAPI de FastAPI) |
| Composants | shadcn/ui (Radix) + Tailwind |
| Vue jeu pixel art ([13](13-interface-jeu-pixel-art.md)) | Phaser 3, easystarjs, mitt (chargés à la demande) |
| Types API | `openapi-typescript` à partir de `/openapi.json` |

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
| Serre et structure | `GET/POST /serres`, `GET/PATCH/DELETE /serres/{id}` ; idem `/zones`, `/emplacements`, `/cuves` |
| Plantes | `GET/POST /plantes`, `PATCH /plantes/{id}`, `POST /plantes/{id}/deplacer`, `GET /plantes/{id}/historique` |
| Contenants, recettes | `/contenants`, `/recettes` (CRUD) |
| Équipements | `/capteurs`, `/actionneurs`, `/cameras` (CRUD), `PUT /cameras/{id}/regions` |
| Configuration | `GET /config/diff`, `POST /config/publier` → `config_version` (`backend.config.export.export`) |
| Mesures | `GET /mesures?zone=&type=&debut=&fin=&agregat=` |
| Vision | `GET /vision?emplacement=&debut=&fin=`, `GET /images/{image_id}` (+ `?gradcam=1`) |
| Décisions | `GET /decisions?…`, `GET /decisions/{id}`, `POST /decisions/{id}/valider`, `POST /decisions/{id}/rejeter` |
| Actions | `GET /actions/arbre?zone=&debut=&fin=`, `POST /actions/manuelle` |
| Consommation | `GET /consommation?zone=&periode=jour\|semaine\|mois` |
| Alertes | `GET /alertes?actives=1`, `POST /alertes/{id}/acquitter` |
| Agent | `POST /agent/chat` (SSE), `GET /agent/conversations`, `GET /agent/conversations/{id}` |
| Temps réel | `WS /ws/live` : messages `{kind, zone, subject, payload}` relayés depuis MQTT (capteur, vision, etat, status, alerte, decision) |

`POST /decisions/{id}/valider` et `POST /actions/manuelle` sont les **seuls** points d'entrée qui publient sur `serre/<zone>/cmd/<actionneur>` depuis le serveur ; ils construisent la `Command` via `common.mqtt` (`cmd_topic`, `encode`, `Command.validate_for`).

## 4. Organisation du dépôt (cible)

```
backend/
├── main.py              # app FastAPI, montage du front statique
├── api/                 # serres.py, plantes.py, equipements.py, decisions.py, actions.py, agent.py, live.py
├── db/                  # models.py (SQLAlchemy), migrations/ (Alembic), timescale.sql
├── ingestion/           # mqtt_ingest.py
├── agent/               # loop.py, tools.py, prompts.py
└── config/              # export.py (serre.yaml versionné)
frontend/
├── package.json  vite.config.ts  index.html
└── src/
    ├── api/             # client généré (openapi-typescript) + hooks TanStack Query
    ├── pages/           # Constructeur, Equipements, Dashboard, Consommation, Decisions, Arbre, Agent
    ├── components/      # PlanSerre, FicheEmplacement, FicheDecision, ArbreActions, CarteProposition…
    ├── live/            # client WebSocket
    └── game/            # vue jeu pixel art (Phaser), voir doc 13
```

Déjà en place (G1) : `backend/db/` (`models.py`, `session.py`, `timescale.sql`, `seed.py` — sans Alembic pour l'instant), `backend/ingestion/` (`mqtt_ingest.py`, `__main__.py`), `backend/consumption.py`, `backend/docker-compose.yml` et `backend/grafana/` ; voir [09 §7](09-modele-gestion-serre.md#7-persistance).

Dépendances Python à ajouter à l'extra `backend` de `pyproject.toml` : `alembic`, `anthropic`, `sse-starlette` (en plus de `sqlalchemy`, `psycopg`, `fastapi`, `uvicorn` déjà présents).

## 5. Développement sans matériel

Tout l'écran est développable avec le **simulateur** ([06 §5](06-capteurs-controle.md#5-simulateur--sim)) et un faux `camera_service` qui rejoue des images de PlantDoc :
1. `docker compose up` : mosquitto, PostgreSQL/TimescaleDB ;
2. `sim` publie capteurs et vision sur les mêmes topics ;
3. le controller tourne sur le PC et produit des décisions ;
4. backend + `vite dev` (proxy `/api` et `/ws` vers FastAPI).

## 6. Tests

| Niveau | Contenu |
|---|---|
| Backend | pytest + base PostgreSQL de test : CRUD, cohérence (mode de culture ↔ capteurs), calcul de consommation, construction de l'arbre, validation/rejet de décision → message MQTT attendu (broker de test) |
| Contrat | les messages émis par le backend passent `common.mqtt.decode` |
| Front | Vitest + Testing Library (composants), Playwright (parcours : créer une serre → ajouter une plante → voir une décision simulée → valider une proposition) |
| Agent | jeu de questions de référence et tests de garde-fous ([11 §6](11-agent-decision.md#6-évaluation-de-lagent)), avec un client LLM factice en CI |
