# 13 — Vue « jeu » en pixel art

Une vue de l'interface inspirée d'Animal Crossing / Stardew Valley : on **construit** sa serre case par case, puis, une fois en fonctionnement, un **petit jardinier** la parcourt et **rejoue les actions réelles** du contrôleur (ventiler, arroser, inspecter une plante malade). Approcher ou cliquer une plante ou une station de culture affiche ses **stats** dans une bulle de dialogue.

> Statut : **implémenté (J1–J5)**, avec les sprites de `planche_01` à `planche_04` (jardinier et ses actions, 16 espèces) : vue `/jeu` (Phaser 3), pipeline sprites → atlas piloté par le manifeste (§2), champ `disposition` en base (§3), construction, serre vivante, inspection, rejeu, démo hors ligne `/jeu?demo=1` ; détail en §11. Interface classique et API : [12](12-interface-utilisateur.md) ; modèle de données : [09](09-modele-gestion-serre.md) ; décisions : [10](10-decisions-tracabilite.md) ; agent : [11](11-agent-decision.md).

## 1. Principe

- La vue jeu est une **autre façon d'afficher** la même serre : elle lit et écrit exactement les mêmes ressources que l'interface classique (`/api/zones`, `/emplacements`, `/plantes`, `/capteurs`, `/actionneurs`, `/decisions`, `WS /ws/live`, [12 §3](12-interface-utilisateur.md#3-api-rest-fastapi)). Elle n'ajoute **aucune logique métier** et ne déclenche aucune commande que l'interface classique ne pourrait pas déclencher.
- Le jardinier est un **avatar des événements réels**, pas une simulation : il ne bouge que pour illustrer ce que le contrôleur, la vision ou l'utilisateur ont réellement fait. Au repos, il fait une ronde.
- Les écrans détaillés (fiche décision, arbre des actions, consommation, agent) restent ceux de [12 §2](12-interface-utilisateur.md#2-écrans). On les ouvre depuis un menu en surimpression, le **SerrePhone** (clin d'œil au NookPhone).
- Si le moteur de jeu plante ou si le navigateur est trop lent, l'interface classique reste pleinement utilisable. Elle sert aussi d'alternative accessible (§8).

```
┌ Serre « Maison » ── 14:32 ☀ 23,4 °C  HR 68 %  ⚡ 1,2 kWh  💧 4,1 L ─────────────── [📱 SerrePhone] ┐
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │
│  ▓  z1 · terre                          ✺ventilo  ▓  z2 · hydro NFT                         ▓ │
│  ▓   🍅    🍓    ·     ·                          ▓   ═🌿═🌿═🌿═🌿═🌿═🌿═  canal G1–G6         ▓ │
│  ▓   A1    A2    A3    A4        ☺ ← jardinier    ▓   ═🌿═🌿═🌿═🌿═🌿═🌿═  canal G7–G12        ▓ │
│  ▓   🍅?   ·     ·     ·                          ▓                       [cuve] pH 5,9      ▓ │
│  ▓   B1    B2    B3    B4    📷cam-z1-a           ▓   ▤ SHT41  ▤ LD2450     EC 1,8         ▓ │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ │
│ [🔨 Construire]  [▶ Serre vivante]  [⏪ Rejouer 24 h]                       ⚠ 1 décision à valider │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## 2. Direction artistique

| Élément | Choix |
|---|---|
| Perspective | vue de dessus **3/4** (comme Stardew Valley ou Animal Crossing en 2D) : grille orthogonale, objets vus légèrement de face. C'est plus simple à dessiner et à rendre cliquable que l'isométrique. |
| Tuiles | **16 × 16 px**, affichées en zoom entier ×3 ou ×4 (`pixelArt: true` dans Phaser, `image-rendering: pixelated`), jamais de zoom fractionnaire |
| Personnage | 16 × 24 px, 4 directions |
| Palette | limitée (~32 couleurs, ex. *Resurrect 64* réduite), commune à tous les sprites |
| Outil | **Aseprite** (calques, tags d'animation), export *spritesheet* + JSON lu directement par Phaser |
| Police | police pixel libre (ex. *Press Start 2P*, *m5x7*) pour les bulles et la barre d'état |
| Démarrage | packs libres pour prototyper (*Sprout Lands*, *LPC*, *Kenney*), **licence vérifiée et notée** dans `frontend/public/sprites/LICENCES.md`, puis remplacement progressif par des sprites maison |

### Inventaire des sprites

| Famille | Variantes | Animations |
|---|---|---|
| Sol et structure | terre, dalle, gravier, allée ; murs, vitres, porte, étagère | — |
| Contenants | un sprite par `type` de [09 §3](09-modele-gestion-serre.md#3-contenant-et-mode-de-culture) : `pot`, `jardiniere`, `sac_de_culture`, `godet`, `canal_NFT`, `bac_DWC`, `pleine_terre` | eau qui coule dans `canal_NFT` quand `pompe_nutri` est en marche |
| Plantes | **espèce × stade** (`semis`, `croissance`, `floraison`, `fructification`, `recolte`) ; espèce hors taxonomie → plante générique | léger balancement ; balancement plus fort quand le ventilateur tourne |
| Santé | `sain` → normal ; `a_surveiller` → feuilles jaunies ; `malade` → taches et feuilles tombantes ; `isolee` → cloche ou ruban ; `retiree` → pot vide | particules (spores) si `malade` |
| Actionneurs (`Actuator`) | `ventilo`, `led`, `brumisateur`, `chauffage`, `pompe_nutri`, `pompe_ph_down` | `off` / `on` ; `pwm` → vitesse ou intensité proportionnelle à `valeur` |
| Capteurs | petit boîtier par famille (air, sol, eau, lumière) ; cuve avec niveau visible | LED verte si en ligne, grise si `offline` |
| Caméra | caméra sur pied ou au plafond | petit flash à chaque capture |
| Jardinier | marcher, attendre, arroser, inspecter (loupe), ventiler (allumer un interrupteur), doser (pipette), noter (carnet), dormir (la nuit) | 4 directions × 4 à 6 images |
| Bulles | `!` (alerte), `?` (anomalie vision), `…` (agent qui réfléchit), cœur (récolte prête) | apparition en rebond |

### Sources des sprites : `sprites-src/`

```
sprites-src/
├── brut/planche_0N.png      # planches générées (ChatGPT), fond transparent : 01 à 04
├── decoupe/planche_0N/      # sprite_001.png … + apercu.png (numéros des cadres)
├── sprites.json             # manifeste : chaque asset → taille cible, états, numéros des sprites sources
└── README.md                # procédure de découpe et de nettoyage
```

- **Découpe** : `tools/decouper_sprites.py --auto` détecte les sprites d'après le canal alpha (pixels quasi opaques, fragments proches recollés : tige et motte d'une jeune pousse, gouttes, objet tenu dont le cadre chevauche celui du personnage) et numérote les cadres ligne par ligne. Un mode interactif (sélection à la souris, OpenCV avec interface graphique) sert aux corrections.
- **Manifeste** `sprites.json` : pour chaque asset, la taille **cible** en pixels de jeu, les états ou images d'animation, le chemin final sous `frontend/public/sprites/`, et `source.sprites`, les numéros des fichiers découpés. Les plantes sont décrites par une matrice santé × stade. Chaque actionneur porte le nom `Actuator` correspondant (`ventilo`, `led`…).
- **État des planches** (manifeste v1.3 ; avancement et prompts dans [`PROMPTS.md`](../sprites-src/PROMPTS.md#état-davancement)) :

| Planche | Sprites | Contenu | Écarts |
|---|---|---|---|
| `planche_01` | 150 | jardinier : marche bas, droite, haut, attente, arrosage à droite ; tomate, fraisier, basilic ; poivron (sauf floraison) ; contenants, sols, vitres, actionneurs (6 images chacun), capteurs, bulles | bordure de briques droite, états `isolee` / `retiree` manquants (`suggested_additions.missing_from_planche_01`) |
| `planche_02` | 44 | actions du jardinier : marche à gauche dessinée, arrosage bas et haut, inspection à droite et de face, interrupteur, pipette, carnet, tapoter un boîtier, sommeil sur le banc, enveloppe, portrait 32×32 | « Zz » perdu à la découpe ; directions absentes jouées en miroir (inspection à gauche) ou de face (inspection vers le haut) |
| `planche_03` | 78 | piment, aubergine, concombre, courgette, melon (5 stades × 3 santés) ; floraison du poivron | — |
| `planche_04` | 109 | laitue, laitue rouge, épinard, roquette, mâche (4 stades), blette, kale ; taille `[16, 24]` | bande NFT avec ses godets dessinée mais pas branchée (`suggested_additions.drawn_not_wired`) |

- **Limites des images générées** : sprites environ 3 à 5 fois trop grands et hors grille ; actionneurs, capteurs et cuves posés sur un voile blanc semi-transparent.

### Atlas du jeu : `make sprites`

`tools/construire_atlas.py` lit `sprites.json` et produit tout ce que le jeu affiche :

1. **nettoyage** de chaque sprite découpé : halo flou et voile blanc effacés, alpha binaire ;
2. **réduction** à `size × export.facteur` (facteur **2** : une tuile = 32 px d'atlas = 16 px de jeu), chaque pixel prenant la couleur dominante de son bloc, sans mélange ; une **échelle commune** aux images d'un asset tirées d'une **même planche** (un semis reste plus petit que la plante adulte ; le jardinier, dessiné 2× plus grand sur `planche_02`, garde la même taille à l'écran), reprise d'un autre asset avec `echelle_de`. Une animation dessinée à part a son échelle (`echelle_propre`) ou sa taille (`size`, le portrait) ; une case de matrice peut venir d'une autre planche (`{"sheet", "n"}`, floraison du poivron) ;
3. **atlas** `frontend/public/sprites/atlas.png` + `atlas.json` (Phaser, JSON Hash), PNG séparés pour les éléments 9-slice, aperçu ×3 `sprites-src/atlas_apercu.png` ;
4. **catalogue** `frontend/src/game/catalogue.gen.json` dans les termes du modèle : espèce × stade × santé → frame (`especes`, `stades_modele` du manifeste, `modele.sante`), contenants par `type`, actionneurs par `actuator`, capteurs par `famille`, animations du jardinier.

Le jeu ne lit que ce catalogue : une nouvelle planche se découpe, se décrit dans le manifeste, puis `make sprites` suffit. Tout ce qui manque a un repli (plante générique, stade le plus proche, `idle` du jardinier, cloche et spores dessinées par le jeu). Les prompts des planches suivantes sont dans [`sprites-src/PROMPTS.md`](../sprites-src/PROMPTS.md).

## 3. Correspondance données → monde

| Donnée ([09](09-modele-gestion-serre.md)) | Dans le monde |
|---|---|
| Serre | la carte entière ; le nom et l'heure locale sont affichés dans la barre d'état |
| Zone `z1` | une pièce ou une parcelle délimitée par des murs bas, avec une étiquette (`z1 · terre`). Couleur de sol selon le `mode_culture` dominant. |
| Emplacement `z1-A1` | une case de la grille (`rangée`, `colonne`) ou un niveau d'étagère, avec le sprite du contenant |
| Plante | sprite espèce × stade × `etat_sante` posé sur l'emplacement |
| Capteur | boîtier posé dans la zone ; les `emplacements_couverts` sont mis en surbrillance au survol |
| Actionneur | objet animé selon `serre/<zone>/etat/<actionneur>` (retain, reçu via `WS /ws/live`) |
| Caméra | objet orienté ; ses `emplacements_visibles` sont mis en surbrillance au survol |
| Cuve | réservoir dont le niveau visible suit `niveau_cuve` |
| Mesures d'ambiance | effets légers : HR > consigne → buée sur les vitres ; nuit → assombrissement ; LED allumées → halo rose-violet ; T° hors plage → teinte chaude ou froide discrète |
| Consommations ([09 §5](09-modele-gestion-serre.md#5-consommations)) | compteurs ⚡ kWh et 💧 L du jour dans la barre d'état, suivis de « (estimé) » tant qu'aucun wattmètre n'est déclaré |
| Alertes, décisions à valider | bulle `!` au-dessus de l'objet concerné et compteur dans la barre d'état |

### Ajout au modèle : `disposition`
La grille (`rangée`, `colonne`) ne suffit pas pour placer les murs, les équipements et les zones les unes par rapport aux autres. On ajoute un champ optionnel `disposition` sur **zone**, **emplacement**, **capteur**, **actionneur**, **caméra** et **cuve** :

```json
{"x": 12, "y": 4, "largeur": 8, "hauteur": 5, "orientation": "sud", "sprite": "pot_terre_cuite"}
```

- les coordonnées sont en tuiles, dans le repère de la serre ;
- `largeur` et `hauteur` concernent les zones uniquement ;
- `sprite` est optionnel et sert à surcharger le sprite par défaut déduit du type.

Le champ est **purement visuel** : le contrôleur l'ignore et il n'est pas exporté dans `serre.yaml` ([09 §8](09-modele-gestion-serre.md#8-configuration-exportée-vers-le-contrôleur)). Sans `disposition`, la vue jeu en calcule une par défaut : zones côte à côte, emplacements selon leur grille, équipements le long des murs.

## 4. Mode Construction

L'équivalent du constructeur de [12 §2.1](12-interface-utilisateur.md#21-constructeur-de-serre), en version « déco » :

```
┌ 🔨 Construction ──────────────────────────────────────────────────────┐ ┌ Inventaire ────────────────┐
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓                                             │ │ Structure  ▦ zone  ▥ étag. │
│  ▓ z1  🍅  🍓  ░░  ░░    ▓      ░░ = case libre (grille aimantée)     │ │ Contenants 🪴 pot  ═ NFT   │
│  ▓     ░░  🍅  ░░  ░░    ▓                                             │ │ Plantes    🍅 🍓 🌶 🌿 …   │
│  ▓          ▤!           ▓   ← « ! » : capteur sans emplacement        │ │ Capteurs   ▤ air ▤ sol ▤ pH│
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓       couvert (contrôle de cohérence)      │ │ Actionn.   ✺ 💡 🌫 🔥 ⛲  │
│                                                                       │ │ Caméras    📷              │
│ [↻ Pivoter] [✋ Déplacer] [🧽 Gomme] [↶ Annuler]   [📤 Publier la config]│ └────────────────────────────┘
└───────────────────────────────────────────────────────────────────────┘
```

- **Inventaire** à gauche ou à droite, par familles. Les capteurs et actionneurs proposés sont filtrés selon le `mode_culture` de la zone ([09 §3](09-modele-gestion-serre.md#mode-de-culture)).
- **Poser un objet** = glisser depuis l'inventaire sur une case libre. Un aperçu fantôme est affiché en rouge si l'emplacement est interdit (case occupée, hors zone).
- Chaque action correspond à **un appel CRUD existant**, sans endpoint nouveau :

| Geste | Appel |
|---|---|
| tracer une zone | `POST /zones` (+ `disposition`) |
| poser un contenant | `POST /emplacements` (+ contenant, `mode_culture`) |
| poser une plante sur un contenant | `POST /plantes` ; une fenêtre pixel demande la variété et le stade |
| déplacer une plante vers un autre contenant | `POST /plantes/{id}/deplacer` (clôture l'affectation, [09 §1](09-modele-gestion-serre.md#1-hiérarchie)) |
| poser un capteur ou un actionneur | `POST /capteurs`, `POST /actionneurs` ; une fenêtre demande le modèle, le nœud et la puissance |
| déplacer un objet sans changer sa fonction | `PATCH …/{id}` avec la nouvelle `disposition` |
| gomme | `DELETE …/{id}`, après confirmation si une plante active est concernée |

- Les **contrôles de cohérence** de [12 §2.1](12-interface-utilisateur.md#21-constructeur-de-serre) apparaissent comme une bulle `!` sur l'objet fautif, avec l'explication au survol.
- Les **régions caméra** restent éditées dans l'interface classique, sur l'image réelle. Depuis le jeu, un clic sur la caméra ouvre cet éditeur.
- **« Publier la configuration »** est le même bouton qu'en [12 §2.1](12-interface-utilisateur.md#21-constructeur-de-serre) : diff, puis nouvelle `config_version`. Petite animation : le jardinier apporte une enveloppe au Pi.
- Annuler et rétablir sont gérés localement. Tant que l'on n'a pas publié, rien n'est envoyé au Pi, mais les objets sont bien enregistrés en base.

## 5. Mode Serre vivante

### File de tâches du jardinier
Les messages `WS /ws/live` (`{kind, zone, subject, payload}`) alimentent une **file de tâches** classée par priorité. Le jardinier exécute une tâche à la fois et se rend à pied sur place, avec un pathfinding A* sur la grille des tuiles.

| Événement | Priorité | Tâche jouée |
|---|---|---|
| `alerte` niveau sécurité ([10](10-decisions-tracabilite.md)) | 1 | court vers l'objet, bulle `!`, la barre d'état clignote |
| `decision` exceptionnelle | 2 | va à l'actionneur concerné et joue l'animation (interrupteur pour `ventilo`, pipette pour `pompe_ph_down`…) ; bulle avec la règle (`maladie.mildiou.ventilation`) |
| `vision` avec `etat_sante` qui passe à `a_surveiller` ou `malade` | 2 | va à la plante, animation loupe, bulle `?` qui reste affichée jusqu'à acquittement |
| `decision` en attente de validation | 3 | se tient devant l'objet avec un carnet ; un clic ouvre la carte de proposition ([12 §2.7](12-interface-utilisateur.md#27-agent)) |
| `etat` d'un actionneur (routine) | 4 | animation de l'objet seulement ; le jardinier y passe s'il est libre (arrosoir pour `pompe_nutri`) |
| `status` nœud `offline` | 3 | va au boîtier, animation « tapote », boîtier grisé |
| rien | 5 | ronde entre emplacements, s'arrête devant une plante ou deux ; la nuit, va s'asseoir sur un banc |

Règles :
- l'**objet** (actionneur, plante) change d'état **immédiatement** à la réception du message. Le jardinier n'arrive qu'ensuite : l'animation illustre l'événement, elle ne le retarde jamais ;
- les routines fréquentes sont regroupées : si une même tâche est déjà dans la file, on incrémente un compteur (« ×3 ») ;
- une tâche périmée (> 2 min sans être jouée) est abandonnée, sauf les alertes et les décisions à valider.

### Rejouer une période
**⏪ Rejouer** reprend le curseur temporel de l'arbre des actions ([12 §2.6](12-interface-utilisateur.md#26-arbre-des-actions)) : 24 h ou 7 j. Les décisions et états sont relus via `GET /api/actions/arbre` et `GET /api/mesures` et injectés dans la même file de tâches, en accéléré (×60, ×600). Le jour et la nuit défilent, on voit le jardinier ventiler à 02:31 et la buée disparaître.

## 6. Inspection : stats d'une plante ou d'une station

Clic sur une plante ou une station (ou touche d'action quand le jardinier est à côté, si on le dirige au clavier) : une **bulle de dialogue pixel** s'ouvre, avec un texte qui défile comme dans un jeu.

```
╔══════════════════════════════════════════════════════════════════╗
║  🍅  Tomate « Cœur de bœuf » · z1-A1                    ❤❤❤♡♡  ║
║  Floraison · plantée il y a 47 jours · recette tomate-standard   ║
║ ──────────────────────────────────────────────────────────────── ║
║  T° air   ███████░░░  22,8 °C   (20–26)        ✔                 ║
║  HR       █████████░  91 %      (55–70)        ⚠ depuis 11 h     ║
║  Sol      ██████░░░░  38 %                     ✔                 ║
║  Lumière  ████░░░░░░  DLI 9,2 / 14                               ║
║ ──────────────────────────────────────────────────────────────── ║
║  👁 Vision 02:00 : mildiou 0,81 (×3)                              ║
║  ⚙ Dernière action : ventilo 900 s (02:31) — règle mildiou v3    ║
║                                                                  ║
║  ▶ [Fiche]  [Photos]  [Décisions]  [Demander à l'agent]  [Fermer] ║
╚══════════════════════════════════════════════════════════════════╝
```

- **Cœurs** : score de santé synthétique sur 5 (classe santé + `score_anomalie` + écarts à la recette). C'est **décoratif** : le détail chiffré est juste en dessous.
- **Jauges** : valeur courante comparée à la plage de la recette pour le stade en cours ([09 §6](09-modele-gestion-serre.md#6-recettes-de-culture)), avec le même code couleur que le tableau de bord ([12 §2.3](12-interface-utilisateur.md#23-tableau-de-bord)). Une icône (✔ ⚠ ✖) double la couleur pour rester lisible sans elle.
- **Station hydro** (cuve, canal NFT) : pH, EC, `temp_eau`, `niveau_cuve`, dernier dosage, volume consommé du jour.
- **Actionneur** : état, durée depuis le dernier changement, énergie du jour, et un bouton de commande manuelle (même chemin que [12 §2.2](12-interface-utilisateur.md#22-équipements) : décision `manuel`, puis `safety.py`).
- **Capteur** : dernière mesure, nœud, date d'étalonnage (bulle orange si elle est dépassée).
- Les boutons ouvrent les écrans classiques par-dessus le jeu. « Demander à l'agent » pré-remplit le chat avec l'emplacement.

### Parler au jardinier
Option : un clic sur le jardinier ouvre le **chat de l'agent** ([11](11-agent-decision.md)) dans une boîte de dialogue avec son portrait pixel. Les propositions de l'agent s'affichent comme des **cartes** Valider / Rejeter, identiques à [12 §2.7](12-interface-utilisateur.md#27-agent). Le jardinier est l'incarnation de l'agent, mais **ne décide rien de plus** que lui : mêmes outils, mêmes garde-fous ([11 §4](11-agent-decision.md#4-garde-fous)).

## 7. Architecture front

```
React (pages, SerrePhone, bulles, formulaires) ──── TanStack Query ── /api, /ws/live
        │  props + bus d'événements (mitt)
        ▼
<SerreJeu/> ── monte une instance Phaser 3
                 ├─ scenes/Chargement.ts    sprites, atlas Aseprite
                 ├─ scenes/Serre.ts         tilemap, entités, caméra (zoom/pan), jour/nuit
                 ├─ scenes/Construction.ts  inventaire, aperçu fantôme, grille aimantée
                 └─ scenes/Hud.ts           barre d'état (ou HUD en React par-dessus le canvas)
```

| Besoin | Choix |
|---|---|
| Moteur 2D | **Phaser 3** : tilemaps, sprites animés lus depuis le JSON Aseprite, caméra, entrées souris/clavier/tactile, rendu `pixelArt` |
| Pathfinding | `easystarjs` (A* sur grille) |
| Bus React ↔ Phaser | `mitt` : Phaser émet `objet:clic`, `objet:deplace` ; React émet `donnees:maj`, `live:evenement` |
| Interface par-dessus | composants React stylés pixel (bordures en 9-slice, police pixel), réutilisant la logique des composants de [12](12-interface-utilisateur.md) (`FicheEmplacement`, `CarteProposition`…) |

Règles :
- **Phaser ne fait aucun appel réseau.** Les données viennent de TanStack Query (React) et lui sont poussées. Les gestes de construction remontent à React, qui appelle l'API puis invalide le cache.
- Le monde est **reconstruit depuis les données** à chaque mise à jour. Aucun état métier ne vit seulement dans Phaser.
- Le jeu est chargé en **lazy import** : un utilisateur qui reste sur la vue classique ne télécharge pas Phaser ni les sprites.

### Organisation
```
frontend/
├── public/sprites/          # atlas Aseprite (.png + .json), tilesets, LICENCES.md
└── src/game/
    ├── SerreJeu.tsx         # montage Phaser, pont avec React
    ├── bus.ts
    ├── scenes/              # Chargement, Serre, Construction, Hud
    ├── entities/            # Jardinier, Plante, Actionneur, Capteur, Camera, Cuve
    ├── tasks/fileTaches.ts  # événement live → tâche, priorités, regroupement
    ├── mapping.ts           # donnée → sprite / animation / effet (pur, testable)
    └── ui/                  # BulleDialogue, Inventaire, SerrePhone
sprites-src/                 # planches brutes, sprites découpés, manifeste sprites.json (§2)
```

### Performance et accessibilité
- objectif 60 fps avec quelques centaines de plantes : atlas uniques, culling hors caméra, animations d'ambiance coupées quand l'onglet est caché ;
- option « réduire les animations » qui suit `prefers-reduced-motion` : le jardinier se téléporte et les particules sont supprimées ;
- la vue classique reste le chemin accessible (lecteur d'écran, navigation clavier complète) ; un bouton les relie dans les deux sens ;
- les états ne sont **jamais codés par la seule couleur** : sprite différent, icône ou bulle en plus.

## 8. Développement sans matériel

Avec le simulateur ([06 §5](06-capteurs-controle.md#5-simulateur--sim)) et le faux `camera_service` ([12 §5](12-interface-utilisateur.md#5-développement-sans-matériel)), la serre vit déjà : les actionneurs s'animent et le jardinier fait ses tâches.

On ajoute un **scénario démo** (`sim --scenario mildiou`) qui fait monter l'HR, publie une classification `mildiou` sur `z1-A1` et laisse le contrôleur décider. On voit alors toute la chaîne : bulle `?`, jardinier qui inspecte, ventilation, fiche décision.

Un mode **« hors ligne »** charge une serre et une journée d'événements depuis un fichier JSON de démonstration. Il sert pour travailler les sprites sans backend.

## 9. Tests

| Niveau | Contenu |
|---|---|
| Unitaires (Vitest) | `mapping.ts` : chaque combinaison espèce × stade × santé a un sprite, sinon le sprite générique ; `fileTaches.ts` : priorités, regroupement « ×n », abandon des tâches périmées |
| Composants | bulle d'inspection : valeurs et icônes d'état correctes pour une plante simulée |
| Parcours (Playwright) | en mode Construction, tracer une zone et poser un pot puis une tomate → `GET /plantes` la contient ; un événement WS `decision` simulé → l'actionneur passe à `on` et le jardinier atteint sa case ; « Demander à l'agent » ouvre le chat pré-rempli |
| Visuels | captures de référence de la scène (canvas) sur le scénario démo, comparées à tolérance près |

## 10. Étapes

| Étape | Contenu | Critère |
|---|---|---|
| **J1 — Serre statique** | sprites de prototype, rendu de la serre depuis l'API avec `disposition` par défaut, zoom et déplacement de la caméra | la serre saisie dans l'interface classique s'affiche correctement |
| **J2 — Inspection** | bulles plante, station, actionneur et capteur ; liens vers les écrans classiques | toutes les stats de [12 §2.3](12-interface-utilisateur.md#23-tableau-de-bord) consultables depuis le jeu |
| **J3 — Serre vivante** | `WS /ws/live` → animations des objets, jardinier avec sa file de tâches, jour/nuit | scénario démo mildiou joué de bout en bout |
| **J4 — Construction** | inventaire, pose et déplacement, gomme, cohérence, publication | serre complète construite uniquement depuis le jeu et chargée par le controller |
| **J5 — Finitions** | rejouer 24 h / 7 j, ambiance (buée, LED), parler au jardinier, sprites maison | — |

Ces étapes se placent **après G2** ([07](07-roadmap.md)) : elles réutilisent l'API et les composants de l'interface classique.

## 11. Implémentation

| Élément | Fichiers |
|---|---|
| Atlas et catalogue | `tools/construire_atlas.py` (`make sprites`), `sprites-src/sprites.json` v1.3, `tests/test_construire_atlas.py`, `tests/test_decouper_sprites.py` |
| `disposition` | colonne JSON sur `zone`, `emplacement`, `capteur`, `actionneur`, `camera`, `cuve` ; `init_db` ajoute les colonnes manquantes d'une base existante (`add_missing_columns`, en attendant Alembic) ; modèle `Disposition` (`backend/api/crud.py`) dans les `*In` / `*Patch` ; jamais exporté dans `serre.yaml` |
| Page | `frontend/src/game/SerreJeu.tsx` (route `/jeu`, chargée à la demande), `PhaserVue.tsx`, `donnees.ts` (API ou démo) |
| Pur et testé | `monde.ts` (données → tuiles, entités, cases bloquées, disposition par défaut), `mapping.ts`, `tasks/fileTaches.ts`, `rejeu.ts` |
| Phaser | `scenes/Chargement.ts`, `scenes/Serre.ts` (sol, murs, objets réconciliés, ambiance, caméra, clics), `scenes/Construction.ts` (grille, fantôme, glisser, rectangle de zone), `entities/Jardinier.ts` (A* easystarjs), `entities/Objet.ts` |
| React | `ui/BarreEtat`, `ui/BulleDialogue`, `ui/SerrePhone`, `ui/Inventaire`, `ui/FormulaireEquipement`, `useConstruction.ts` (gestes → CRUD, annuler / rétablir), `useRejeu.ts`, `components/ChatAgent.tsx` (partagé avec la page Agent) |

Écarts et choix par rapport aux sections précédentes :
- **Zoom** : par pas entiers de *pixels de jeu* (caméra 0,5 ; 1 ; 1,5… puisque l'atlas est en ×2), jamais de pixel fractionnaire, et la serre entière tient à l'écran au départ.
- **Murs** : murs bas dessinés par le jeu, vitres de façade et porte de `planche_01` ; dès que `brick_border_straight` existe dans le catalogue, les murs passent en briques.
- **HUD** en React par-dessus le canvas (pas de scène `Hud`) ; l'inventaire est une colonne à côté du canvas.
- **Live** : `LiveProvider` expose `subscribe` (chaque événement). L'état d'un actionneur et le statut d'un nœud changent dès le message ; la tâche est ajoutée ensuite à la file.
- **Rejeu** : décisions exceptionnelles, de sécurité et manuelles une par une, avec leurs actions (actionneur en marche de `ts_debut` à `ts_fin`) ; les routines restent agrégées dans l'arbre, donc absentes du rejeu. L'HR et la T° viennent de `/mesures` (buée, teinte).
- **Construction** : un contenant posé reçoit le code de grille de sa case (`codeCase`), cohérent avec le plan classique. La gomme retire la plante (`deplacer` vers aucun emplacement) ou supprime l'objet, et l'annulation le recrée ; une caméra recréée perd ses régions. La cuve et les zones ne se suppriment pas depuis le jeu.
- **Tests** : Vitest (`mapping`, `monde`, `fileTaches`, `rejeu`, `BulleDialogue`, sur la serre de démo `public/demo/serre-demo.json`) et Playwright `e2e/jeu.spec.ts` (pot puis tomate posés depuis l'inventaire, annuler, décision manuelle jouée par le jardinier, « Demander à l'agent »). Pour viser une case du canvas, les tests passent par `window.__serreJeu`, exposé seulement sous automatisation (`navigator.webdriver`). Pas encore de captures de référence (§9, visuels).

Reste à faire : sprites des planches suivantes (aromatiques, racines et légumineuses, ravageurs, briques, mobilier) et leur branchement quand un nouveau type d'élément apparaît (overlays de symptômes par classe vision, canal NFT continu et salades en godet de `planche_04`, banc, boîtier Pi, enveloppe portée par le jardinier) ; captures visuelles de référence.
