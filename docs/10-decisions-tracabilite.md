# 10 — Décisions, traçabilité et arbre des actions

Objectif : pour **chaque action** exécutée dans la serre, pouvoir répondre à « pourquoi ? » — quelle **classification photo** (image, classe, confiance), quelles **mesures capteurs** et quelle **règle ou modèle** l'ont produite — et visualiser l'ensemble sous forme d'**arbre** séparant routines et actions exceptionnelles.

> Statut : **conception**. S'appuie sur le modèle de [09](09-modele-gestion-serre.md) et sur les niveaux de contrôle de [06 §4](06-capteurs-controle.md#4-stratégie-de-contrôle--edgecontroller).

## 1. Principe

```
 entrées                         contrôleur (Pi)                          sorties
 ───────                         ───────────────                          ───────
 serre/z1/capteur/humidite ─┐
 serre/z1/capteur/temperature├─► évaluation des règles ──► Decision ──┬─► Command  serre/z1/cmd/ventilo
 serre/z1/vision/cam-z1-a ──┤    (niveaux 0 → 3)          (+ preuves) ├─► Alert    serre/z1/alerte
 prévision GRU (niveau 2) ──┤                                         └─► serre/z1/decision  (journal)
 recette + config serre ────┘
```

Règle d'or : **aucune `Command` automatique sans `Decision`**. Le contrôleur crée d'abord la décision (avec ses preuves), puis émet la ou les commandes en y faisant référence. Les commandes manuelles (UI) et les propositions de l'agent ([11](11-agent-decision.md)) suivent le même chemin.

## 2. Enregistrement `Decision`

```json
{
  "id": "dec-20261012-0231-z1-007",
  "ts": "2026-10-12T02:31:00Z",
  "zone": "z1",
  "emplacements": ["z1-A1"],
  "niveau": 1,
  "origine": "controller",
  "regle": {"id": "maladie.mildiou.ventilation", "version": 3},
  "config_version": 12,
  "preuves": {
    "vision": [
      {
        "image_id": "z1-a-20261012T020000",
        "camera": "cam-z1-a",
        "modele": "clf-effb0-v3",
        "emplacement": "z1-A1",
        "espece": "tomate", "espece_conf": 0.97,
        "sante": "anormal", "sante_conf": 0.88,
        "classe": "tomate/maladie/mildiou", "classe_conf": 0.81,
        "bbox": null,
        "score_anomalie": 0.42,
        "gradcam_uri": "images/z1-a-20261012T020000_A1_gradcam.jpg",
        "confirmations": 3
      }
    ],
    "capteurs": [
      {"topic": "serre/z1/capteur/humidite", "agregat": "duree_au_dessus", "seuil": 90, "valeur": 11.2, "unite": "h", "qualite": "ok"},
      {"topic": "serre/z1/capteur/temperature", "agregat": "moyenne_12h", "valeur": 17.8, "unite": "°C", "qualite": "ok"}
    ],
    "prevision": [
      {"grandeur": "humidite", "horizon": "+6h", "valeur": 93, "modele": "gru-v1"}
    ],
    "consignes": {"recette": "tomate-standard", "stade": "floraison", "humidite": [55, 70]}
  },
  "explication": "HR > 90 % depuis 11,2 h à 17,8 °C et mildiou détecté sur z1-A1 (conf. 0,81, 3 images consécutives) → ventilation 15 min + alerte.",
  "actions": ["act-…-01", "act-…-02"],
  "statut": "executee"
}
```

| Champ | Description |
|---|---|
| `niveau` | `0` sécurité, `1` règle/régulateur, `2` prévision, `3` optimisation, `agent` proposition LLM, `manuel` utilisateur |
| `origine` | `controller`, `safety`, `agent`, `ui:<utilisateur>` |
| `regle` | identifiant stable et versionné de la règle (`edge/controller/rules.py`) ou du modèle |
| `preuves.vision` | copie des champs du `VisionResult` / `Detection` utilisés + emplacement résolu (régions caméra, [09 §4](09-modele-gestion-serre.md#caméra)) + lien Grad-CAM + nombre de **confirmations** temporelles |
| `preuves.capteurs` | mesures brutes **ou agrégats** réellement utilisés par la règle (avec la fenêtre), jamais tout l'historique |
| `preuves.prevision` | sorties du modèle de niveau 2 utilisées |
| `consignes` | plage de la recette à laquelle la mesure a été comparée |
| `explication` | texte **généré de façon déterministe** par la règle (gabarit), pas par le LLM : il doit exister même hors ligne |
| `statut` | voir cycle de vie §4 |

On ne stocke que **ce qui a fait basculer la décision** : c'est ce que l'UI affiche dans la fiche décision ([12](12-interface-utilisateur.md)).

## 3. Enregistrement `Action`

| Champ | Exemple | Remarque |
|---|---|---|
| `id` | `act-20261012-0231-z1-007-01` | |
| `decision_id` | `dec-20261012-0231-z1-007` | une action routinière a aussi une décision (la règle de planning) |
| `type` | `routine \| exceptionnelle \| securite \| manuelle` | voir §5 |
| `cible` | `actionneur:ventilo` (z1) / `alerte` / `camera:cam-z1-a` / `plante:<id>` | une action peut ne pas être une commande MQTT (ex. « marquer la plante isolée ») |
| `commande` | `{"action": "on", "duree_s": 900, "source": "controller", "raison": "dec-20261012-0231-z1-007"}` | `Command` existante ; le champ `raison` porte l'**id de décision** suivi du texte court |
| `resultat` | `confirmee \| non_confirmee \| bloquee \| echec` | confirmée quand `serre/z1/etat/ventilo` reflète la commande dans les 10 s |
| `ts_debut`, `ts_fin` | | `ts_fin` = échéance `duree_s` ou commande `off` |

Le lien `Command.raison` ↔ `Decision.id` permet aussi à l'ingestion serveur de reconstituer la traçabilité à partir du seul flux MQTT, même si le message `decision` a été perdu.

## 4. Cycle de vie

```
             ┌──────────── (agent / UI) ────────────┐
             ▼                                      │
        proposee ──valider──► validee ──┐           │
             │                          │           │
          rejeter                       ▼           │
             ▼              (controller) creee ──► safety.py ──ok──► executee ──► terminee
          rejetee                                     │
                                                      └─refus──► bloquee_securite (+ alerte)
```

- Les décisions du contrôleur naissent directement à l'état `creee` (pas de validation humaine, comme aujourd'hui).
- Les décisions de l'agent et certaines décisions exceptionnelles configurées « avec validation » (ex. isoler une plante, traitement) naissent `proposee` et attendent l'utilisateur ; elles **expirent** après un délai (défaut 2 h).
- **Toute** décision passe par `safety.py` (niveau 0) avant exécution ; un refus est lui-même tracé (`bloquee_securite`) avec la limite en cause.

## 5. Routines et actions exceptionnelles

| Type | Déclencheur | Exemples |
|---|---|---|
| **routine** | horloge ou régulation continue sur consigne | photopériode LED, cycles d'arrosage, hystérésis T/HR → ventilo / chauffage / brumisateur, dosage pH/EC par impulsions, capture caméra toutes les 10 min |
| **exceptionnelle** | **décision d'un modèle** (vision, prévision, indice de risque) ou événement anormal | ventilation préventive mildiou, recapture à la demande pour confirmer une détection, alerte nuisible, plante marquée « à surveiller » / « isolée », baisse d'HR ciblée, demande d'inspection manuelle |
| **securite** | limite dure de [06 §4 niveau 0](06-capteurs-controle.md#niveau-0--sécurité-safetypy) | coupure pompe cuve vide, coupure chauffage T° max, alerte « capteur muet » |
| **manuelle** | utilisateur (UI) ou proposition agent validée | forcer LED à 100 % 1 h, arrosage ponctuel |

Les routines sont nombreuses et répétitives : elles sont **agrégées** (une décision par cycle de régulation et par actionneur, pas par mesure) pour que le journal reste lisible.

### Règles « classification → action » (premier jeu)

Une classification ne déclenche d'action que si elle est **confirmée** : même classe sur ≥ 3 images consécutives de l'emplacement, `classe_conf` ≥ seuil calibré (doc [03](03-classifieur.md)), espèce prédite = espèce déclarée de la plante (sinon → alerte « incohérence espèce » seulement).

| Classe vision (taxonomie) | Condition capteurs | Décision / actions | Validation |
|---|---|---|---|
| `tomate/maladie/mildiou`, `pomme_de_terre/maladie/mildiou` | HR > 85 % ou humectation estimée > 10 h, 10–25 °C | ventilation 15 min toutes les heures la nuit, consigne HR max abaissée de 10 pts pendant 72 h, alerte `warning`, plante → `malade` | auto (ventilation), proposée (isolement) |
| `*/maladie/oidium` (courge, cerisier) | HR 40–70 %, T° 20–27 °C | alerte, recapture rapprochée (1 h) pour suivre l'extension, plante → `a_surveiller` | auto |
| `tomate/maladie/septoriose`, `alternariose`, `tache_bacterienne` | arrosage par aspersion actif | basculer l'emplacement en arrosage au pied si possible, alerte, inspection manuelle | proposée |
| `*/nuisible/*` (ex. `tomate/nuisible/tetranyque`) | HR < 50 % favorise l'acarien | brumisation légère (si recette compatible), alerte inspection, recapture | proposée |
| `*/virus/*` | — | alerte `critique` « isoler la plante » (pas de remède : risque de propagation) | proposée |
| `sante: sain` mais `score_anomalie` > seuil | — | alerte `info` + recapture ; aucune action actionneur | auto |
| `surface_verte_px` en baisse > 15 % / 48 h | stress hydrique possible (substrat sec, EC haute) | arrosage ponctuel ou vérification EC, alerte | proposée |

Ces règles sont dans `edge/controller/rules.py` avec un identifiant stable (`maladie.mildiou.ventilation`) ; leurs seuils sont dans la recette ou un fichier `regles.yaml` éditable depuis l'UI.

## 6. Arbre des actions

L'arbre est une **vue** construite à partir des tables `decision` et `action` sur une période (24 h par défaut).

```
Serre « Maison »                                         [12/10 00:00 → 24:00]
├── z1 (terre)
│   ├── Routines
│   │   ├── Lumière       led       photopériode 16 h          ✔ 06:00 on 80 %  ✔ 22:00 off
│   │   ├── Climat        ventilo   hystérésis T° 26/24 °C     ✔ ×14 cycles (3 h 20 au total)
│   │   │                 chauffage hystérésis T° 16/18 °C     ✔ ×3 cycles
│   │   ├── Arrosage      pompe_nutri 3 × 45 s                 ✔ 07:00 ✔ 13:00 ✔ 19:00
│   │   └── Vision        cam-z1-a  capture 10 min             ✔ 144 images
│   ├── Exceptionnelles
│   │   └── dec-…-007  mildiou z1-A1 (conf 0,81 ×3) + HR>90 % 11 h      [niveau 1]
│   │       ├── ventilo on 900 s                               ✔ confirmée
│   │       ├── alerte warning « mildiou probable z1-A1 »      ✔
│   │       └── isoler plante z1-A1                            ⏳ proposée (attend validation)
│   └── Sécurité
│       └── dec-…-011  T° 36 °C > max 35 °C → chauffage off      ✔
└── z2 (hydro NFT)
    ├── Routines
    │   └── pH            pompe_ph_down 4 impulsions × 2 s       ✔ pH 6,6 → 6,2
    └── Exceptionnelles
        └── dec-…-015  prévision EC +6 h = 3,9 > 3,5 (gru-v1)    [niveau 2]
            └── ajout eau claire 20 s                            ✖ bloquée : cuve pleine
```

Structure de données renvoyée par l'API (`GET /actions/arbre?zone=&debut=&fin=`) :

```json
{
  "id": "serre", "label": "Serre « Maison »", "children": [
    {"id": "z1", "label": "z1 (terre)", "children": [
      {"id": "z1/routine", "type": "groupe", "label": "Routines", "children": [ … ]},
      {"id": "z1/exceptionnelle", "type": "groupe", "children": [
        {"id": "dec-…-007", "type": "decision", "niveau": 1, "statut": "executee",
         "resume": "mildiou z1-A1 + HR>90 % 11 h",
         "children": [{"id": "act-…-01", "type": "action", "resultat": "confirmee", "label": "ventilo on 900 s"}]}
      ]}
    ]}
  ]
}
```

Chaque nœud `decision` ouvre la fiche de décision (preuves image + capteurs, cf. [12](12-interface-utilisateur.md)).

## 7. Évolution du contrat MQTT

> Version minimale **implémentée** ([06 §6](06-capteurs-controle.md#6-implémentation-et-test-sur-pc)) : topic `decision`, schéma `Decision` (sans `Action` séparée : `actions` est une liste de libellés `cmd:ventilo on 900 s`, `alerte`, `bloquee:…`), convention `raison`, publication par `edge/controller/service.py` avant chaque commande. Côté serveur (G1, [09 §7](09-modele-gestion-serre.md#7-persistance)) : l'ingestion écrit la table `decision` (forme minimale, upsert par id) et relie chaque `commande` à sa décision via `raison` (`commande.decision_id`). Restent pour G3 : table `action`, confirmation par `etat/`, cycle de vie complet, arbre.

| Topic | Émetteur | QoS | Retain | Schéma |
|---|---|---|---|---|
| `serre/<zone>/decision` | controller, backend (agent/UI) | 1 | non | `Decision` (§2) |

- À ajouter dans `common/mqtt/topics.py` (`TopicKind.DECISION`, `decision_topic`, `SUBSCRIPTIONS`) et `common/mqtt/schemas.py` (modèle pydantic `Decision`, sous-modèles `PreuveVision`, `PreuveCapteur`), avec tests dans `tests/test_mqtt_contract.py`.
- Convention sur `Command.raison` : `"<decision_id> | <texte court>"` — compatible avec le schéma actuel (champ texte libre).
- Les preuves image référencent `image_id` (l'image elle-même transite par l'upload serveur, jamais par MQTT).
