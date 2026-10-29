# 21 — Configurateur des pièces imprimées

**But** : un écran de l'interface web (`/impression`) qui guide la préparation des pièces de
la [doc 20](20-impression-3d-structures.md). L'utilisateur indique la taille de sa serre, les
familles de pièces voulues, son environnement et les cotes qu'il a mesurées ; l'écran en
déduit la liste des pièces à imprimer avec leur matériau et leurs réglages, les mesures et
éprouvettes à faire d'abord, les alertes de sécurité, et exporte un `params.scad`.

> Statut : **spécifié**, non implémenté. Tout est calculé dans le navigateur : pas d'API ni de
> base, l'état est gardé dans le `localStorage` du navigateur. Les règles reprennent la doc 20
> sans la remplacer : en cas d'écart, la doc 20 fait foi.

## 1. Entrées

### 1.1 Contraintes

| Contrainte | Valeurs | Effet |
|---|---|---|
| Échelle de la serre | petite intérieure · tunnel jardin · grande ([20 §3](20-impression-3d-structures.md#3-échelles-de-serre)) | pertinence de chaque pièce (oui / partiel / non) |
| Familles | A Hydroponie · B Structure et bâche · C Éclairage · D Électronique · E Culture | filtre du catalogue |
| Priorité maximale | P0 · P1 · P2 · Évolution ([20 §6](20-impression-3d-structures.md#6-priorités)) | garde les pièces de priorité inférieure ou égale |
| Serre en extérieur | oui / non | alerte vent sur la structure ([20 §7](20-impression-3d-structures.md#7-sécurité)) |
| Pièces à moins de 5 cm d'un driver LED | oui / non | matériaux de la famille C limités à ASA / ASA-CF / ABS |
| Filaments disponibles | PETG, ASA, ABS, PETG-CF, ASA-CF, TPU | choix du matériau parmi les candidats, sinon alerte « filament manquant » |
| Multicouleur CANVAS | oui / non | étiquettes bicolores ou en relief simple |

Le PLA n'est pas proposé ([20 §2.2](20-impression-3d-structures.md#22-matériaux)).

### 1.2 Cotes mesurées

Les cotes de [20 §5.2](20-impression-3d-structures.md#52-cotes-à-mesurer-avant-dimprimer). Chaque
cote a une unité, une valeur typique (affichée en indication, jamais utilisée comme mesure),
une plage plausible et la liste des pièces qui en dépendent. Une cote vide est « à mesurer ».

| Cote | Variable SCAD | Unité | Typique | Plage | Pièces |
|---|---|---|---|---|---|
| Ø extérieur du tube de structure | `tube_structure_d` | mm | 20 | 10–50 | B1, B2, B3, B4, C2, D4, D8 |
| Épaisseur du film | `film_ep` | µm | 200 | 100–300 | B2 |
| Jeu d'ajustement de la CC2 | `jeu` | mm | 0,3 | 0,1–0,5 | toutes |
| Ø du canal NFT | `canal_nft_d` | mm | 100 | 75–110 | A2 |
| Pente des canaux NFT | `pente_nft` | % | 2 | 1–4 | A2, E6 |
| Ø des net-pots | `netpot_d` | mm | 50 | 25–80 | A1, A2, A3 |
| Ø du seau ou du bac DWC | `seau_d` | mm | 300 | 150–600 | A3 |
| Ø des sondes pH / EC | `sonde_phec_d` | mm | 12 | 8–16 | A4 |
| Ø de la sonde DS18B20 | `ds18b20_d` | mm | 6 | 4–8 | A4 |
| Distance JSN-SR04T → niveau haut de l'eau | `jsn_distance` | mm | 300 | 250–1000 | A4 |
| Côté du montant de lampe (tube ou profilé) | `montant_section` | mm | 20 | 15–40 | C1 |
| Largeur × hauteur de la rampe LED | `rampe_l`, `rampe_h` | mm | 30 × 10 | 5–300 | C1 |
| Course de réglage de la lampe | `hauteur_max` | mm | 600 | 100–1500 | C1, C3 |
| Masse de la lampe | `lampe_masse` | kg | 1,5 | 0,1–10 | C1, C2 |
| Ø du tuteur | `tuteur_d` | mm | 10 | 6–16 | E1 |
| Ø du tube goutte-à-goutte | `goutte_d` | mm | 4,6 | 4–16 | E3 |

## 2. Règles

### 2.1 Sélection des pièces

Le catalogue contient les fiches A1–A4, B1–B4, C1–C3, D1–D8 et E1–E6 de
[20 §4](20-impression-3d-structures.md#4-catalogue-par-besoin). Une pièce est retenue si sa
famille est cochée, si sa priorité est ≤ la priorité maximale et si sa pertinence à l'échelle
choisie n'est pas « non ». La pertinence « partiel » est affichée avec sa raison (ex. B1 en
grande serre : « la structure est achetée, seulement clips et accessoires »).

### 2.2 Matériau

Chaque pièce a une liste ordonnée de matériaux candidats tirée de la doc 20 (ex. B1 :
ASA-CF, ASA ; A4 : PETG, ASA). Le matériau retenu est :

1. le premier candidat **disponible** ;
2. si « pièces à < 5 cm d'un driver » est coché et que la pièce est de la famille C, seuls
   ASA, ASA-CF et ABS restent candidats ;
3. si aucun candidat n'est disponible, le premier candidat est affiché avec l'alerte
   « filament manquant ».

Sont ajoutés : « opaque » pour toute pièce au contact de l'eau ou de la solution, « + joint TPU »
pour les pièces qui en demandent un. Les réglages (parois, remplissage, remarque) viennent du
type d'usage de la pièce ([20 §2.3](20-impression-3d-structures.md#23-réglages-type)).

### 2.3 Cotes dérivées et contrôles

Calculées seulement quand les cotes sources sont saisies :

| Cote dérivée | Formule | Pièce |
|---|---|---|
| `raccord_d_int` | `tube_structure_d + jeu` | B1, B3, D4, D8 |
| `emmanchement` | `ceil(1,5 × tube_structure_d)` | B1 |
| `clip_bache_d_int` | `tube_structure_d + 2 × film_ep / 1000 + jeu` | B2 |
| `netpot_trou_d` | `netpot_d + jeu` | A1, A2, A3 |
| `presse_etoupe_phec_d` | `sonde_phec_d + jeu` | A4 |
| `presse_etoupe_ds18b20_d` | `ds18b20_d + jeu` | A4 |
| `coulisseau_int` | `montant_section + jeu` | C1 |

Contrôles affichés à côté des cotes :

- valeur hors de la plage plausible → avertissement (erreur de saisie ou d'unité probable) ;
- `pente_nft` hors 1–4 % → avertissement ;
- `jsn_distance` < 250 mm → **erreur** : zone aveugle du capteur ([20 A4](20-impression-3d-structures.md#a4--couvercle-de-cuve-et-supports-de-sondes)) ;
- `seau_d` > 256 mm → le couvercle (A3) dépasse le plateau de la CC2 : à découper en secteurs ;
- `hauteur_max` > 256 mm → les montants imprimés (C1) sont à découper, ou à remplacer par un
  tube / une tige filetée.

### 2.4 Mesures et éprouvettes

- **Mesures** : chaque cote vide requise par au moins une pièce retenue, avec l'outil de mesure
  et les pièces bloquées.
- **Éprouvettes** : une par pièce à ajustement serré (clip sur tube, filetage, baïonnette,
  presse-étoupe), à imprimer avant la pièce : anneau ou tronçon de 5 mm au Ø calculé
  ([20 §1](20-impression-3d-structures.md#1-principes)), plus une fois l'anneau de jeu
  0,1–0,5 mm si `jeu` n'est pas mesuré.

### 2.5 Alertes de sécurité

Tirées de [20 §7](20-impression-3d-structures.md#7-sécurité), affichées seulement si la sélection
les concerne :

| Condition | Alerte |
|---|---|
| une pièce de la famille C | câble de sécurité métallique indépendant de la pièce ; acheter la suspension à cliquet (C2) |
| C3 retenue | fins de course haut et bas, durée max gérée par le firmware |
| D2 ou D7 retenue | jamais un boîtier imprimé comme seule enveloppe d'un circuit 230 V |
| un matériau ASA ou ABS retenu | styrène : imprimer caisson fermé, pièce ventilée |
| une pièce de la famille A | contact alimentaire : PETG / ASA, parois épaisses, époxy alimentaire si besoin, rincer |
| serre en extérieur et famille B | la tenue au vent vient des piquets, tubes et sangles ; surdimensionner angles et faîtage |
| pièces près d'un driver | pas de PETG à moins de 5 cm d'un driver, d'un dissipateur ou du chauffage |
| un filament manquant | liste des pièces concernées |
| toujours | modèles tiers : vérifier la licence (souvent CC BY-NC) et les cotes avant d'imprimer |

## 3. Sorties

- **Liste des pièces** : id, pièce, priorité, pertinence, matériau, parois / remplissage,
  cotes utiles (mesurées ou dérivées), modèles (liens), ce qu'on n'imprime pas, renvoi logiciel.
- **`params.scad`** : une ligne par cote (`nom = valeur; // unité — libellé`), les cotes vides
  en commentaire `// nom = ?; // À MESURER (typique …)`, puis les cotes dérivées. C'est le
  fichier unique importé par nos pièces `.scad` ([20 §5.3](20-impression-3d-structures.md#53-où-ranger-les-sources-proposition)).
- **Markdown** : le plan complet (contraintes, pièces, mesures, éprouvettes, alertes), à coller
  dans `hardware/README.md` ou à archiver.
- **JSON** : `{version, date, contraintes, cotes, derivees, pieces, mesures, eprouvettes, alertes}`.

## 4. Écran

```
┌ Impression 3D ─────────────────────────────────────────────────────────────────────────┐
│ ┌ Contraintes ─────────────────┐ ┌ [Pièces 14] [Mesures 5] [Sécurité 4] [Export] ─────┐ │
│ │ Échelle ( ) petite (•) tunnel │ │ Id  Pièce                 Prio Matériau     Parois  │ │
│ │ Familles [x]A [x]B [x]C [x]D  │ │ D1  Abri ventilé SHT41    P0   ASA (blanc)  4–6     │ │
│ │ Priorité max  P1 ▾            │ │ A4  Couvercle de cuve     P0   PETG opaque  4+      │ │
│ │ [ ] extérieur [x] driver<5cm  │ │     + joint TPU · presse-étoupes Ø 12,3 / Ø 6,3     │ │
│ │ Filaments [x]PETG [x]ASA …    │ │ B2  Clips de bâche        P1   ASA          4–6     │ │
│ ├ Cotes mesurées ──────────────┤ │     Ø int 20,7 mm · ⚠ éprouvette d'abord            │ │
│ │ Ø tube structure [20.0] mm    │ │ …                                                   │ │
│ │ Film            [    ] µm ⚑   │ │                                                     │ │
│ │ Jeu CC2         [0.3 ] mm     │ │                                                     │ │
│ └───────────────────────────────┘ └─────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

⚑ cote à mesurer. L'onglet Export montre l'aperçu de `params.scad` et trois boutons de
téléchargement (`.scad`, `.md`, `.json`). « Réinitialiser » revient aux contraintes par défaut
(tunnel, toutes familles, P1, PETG + ASA + TPU) et vide les cotes.

## 5. Code et tests

| Fichier | Rôle |
|---|---|
| `frontend/src/impression/catalogue.ts` | données de la doc 20 : matériaux, réglages, cotes, pièces |
| `frontend/src/impression/plan.ts` | fonctions pures : sélection, matériau, cotes dérivées, mesures, alertes, exports |
| `frontend/src/impression/plan.test.ts` | tests Vitest des règles et des exports |
| `frontend/src/pages/Impression.tsx` | écran `/impression` |

Tests : sélection par échelle et priorité, jamais de PLA, matériau près d'un driver, opacité
au contact de l'eau, filament manquant, cotes dérivées du clip de bâche, contrôle JSN-SR04T,
cotes manquantes dans les mesures, alerte câble de sécurité, `params.scad` sans `undefined` ni
`NaN`.

## 6. Évolutions

- Pré-remplir familles et échelle depuis la serre déclarée (zones `hydro_*` → famille A,
  nombre de caméras → D4, surface → échelle) via l'API de [12](12-interface-utilisateur.md).
- Quand `hardware/` existera, générer aussi son `README.md` (pièce → modèle, licence,
  matériau, réglages, quantité) et vérifier en CI que `params.scad` contient toutes les cotes.
- Quantités (nombre de clips d'après la longueur d'arceaux et l'espacement de 50–60 cm, nombre
  de raccords d'après le cadre).
