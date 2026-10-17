# Prompts des planches pixel art

Prompts pour générer les prochaines planches de la vue jeu ([docs/13](../docs/13-interface-jeu-pixel-art.md)) avec un générateur d'images (ChatGPT, comme `planche_01`). Le jeu ne lit que le catalogue produit par `make sprites`. Une planche bien découpée et décrite dans `sprites.json` apparaît donc dans l'interface **sans toucher au code**. Ce qui manque reste affiché avec un sprite de repli : plante générique, `idle` du jardinier, cloche dessinée par le jeu…

## Mode d'emploi

1. **Une planche par conversation.** Joindre `brut/planche_01.png` comme **image de référence**, puis coller le [préambule de style](#préambule-de-style-à-coller-en-tête-de-chaque-prompt) suivi du prompt de la planche.
2. Exiger un PNG **à fond transparent**. Si le résultat arrive sur fond uni ou flou, redemander « transparent background, no backdrop ».
3. Enregistrer l'image sous `sprites-src/brut/planche_NN.png`, puis lancer :
   ```bash
   .venv/bin/python tools/decouper_sprites.py sprites-src/brut/planche_NN.png --auto
   ```
4. Ouvrir `decoupe/planche_NN/apercu.png` pour relever les numéros des sprites.
5. Compléter `sprites.json` :
   - déclarer la planche dans `sources` ;
   - ajouter les assets en suivant le **bloc manifeste** donné sous chaque planche (noms des clés et des animations attendus par le jeu) ;
   - pour une nouvelle plante, renseigner `especes` (noms du modèle, en français) et `stades_modele`.
6. Lancer `make sprites`, regarder `sprites-src/atlas_apercu.png`, puis ouvrir `/jeu?demo=1` (serre de démonstration, sans backend).

**Ce qui a coincé avec la planche 01, à éviter :**
- **Carrés blancs semi-transparents** sous les objets. Le script les efface, mais au prix des bords clairs.
- **Échelle variable** d'un objet à l'autre.
- **Sprites collés entre eux**, que la découpe automatique fusionne.
- **Canal NFT sans extrémités séparées**, donc impossible à répéter en mosaïque.

D'où les consignes « gap », « same scale » et « no backdrop » du préambule.

## Préambule de style (à coller en tête de chaque prompt)

```
Pixel art sprite sheet for a cozy greenhouse management game, same style as the attached
reference sheet (Stardew Valley / Animal Crossing inspired).
- Top-down 3/4 view, light from the top-left, crisp 1-pixel dark brown outline (#49352B).
- Limited palette (max 32 colors) built around: leaf green #5D8C45, dark green #315B35,
  soil brown #805333, wood brown #A66E43, terracotta #C76F4F, cream #F3E5C8,
  water blue #559BC4, flower yellow #E8C957, alert red #D94F45, LED purple #D45BE8.
- No anti-aliasing, no gradients, no blur, no drop shadows outside the sprite.
- FULLY TRANSPARENT BACKGROUND. No backdrop, no white or grey squares behind objects,
  no frames, no labels, no text, no numbers.
- Every sprite is separate: leave a clear transparent gap of at least 24 px between sprites.
- Strict grid: sprites aligned in rows and columns, same scale for every sprite of the sheet,
  one game pixel = one square block of the same size everywhere.
- Plants stand on a small mound of soil, bottom-centered in their cell.
```

## État d'avancement

À mettre à jour à chaque planche ajoutée (dernier point : 17/10/2026, planches 01 à 04 intégrées).

Légende de la colonne « En jeu » :
- **automatique** : le jeu utilise les sprites dès `make sprites`, sans code ;
- **partiel** : une partie est déjà branchée, le reste demandera du code ;
- **code à écrire** : les sprites s'ajoutent à l'atlas mais le jeu ne les utilise pas encore.

| # | Planche | État | En jeu | Pourquoi |
|---|---|---|---|---|
| 01 | Jardinier (marche), tomate, fraisier, poivron, basilic, contenants, sols, actionneurs, capteurs, bulles | ✅ fait | ✅ branché | base actuelle |
| 02 | Jardinier : actions | ✅ fait | ✅ branché | rend lisibles les tâches déjà jouées (inspecter, ventiler, doser, noter, dormir) |
| 03 | Solanacées et cucurbitacées | ✅ fait | ✅ branché | les cultures de serre les plus fréquentes après la tomate |
| 04 | Salades et feuilles | ✅ fait | ✅ branché (variante en godet NFT dessinée : code à écrire) | reine de l'hydroponie (NFT, DWC) |
| 05 | Aromatiques | ⬜ à faire (priorité 1) | automatique | basilic déjà fait ; menthe, persil, ciboulette, coriandre, thym, romarin |
| 07 | Santé et ravageurs | ⬜ à faire (priorité 2) | partiel : `bell_jar` branché, overlays de symptômes et outils à brancher | états `isolee` / `retiree`, symptômes vus par la vision |
| 08 | Structures | ⬜ à faire (priorité 3) | partiel : briques droites branchées, mobilier et canal NFT continu à brancher | murs en briques répétables, mobilier |
| 06 | Racines, légumineuses, divers | ⬜ à faire (priorité 4) | automatique (plante générique en matrice : code à écrire) | radis, carotte, haricot, pois, oignon, micro-pousses, **plante générique** |
| 09 | Interface | ⬜ à faire (priorité 5) | code à écrire | icônes d'inventaire, cœurs, SerrePhone |
| 10 | Ambiance | ⬜ à faire (priorité 6) | code à écrire | buée, halo LED, soleil, pluie |

Manques connus de la planche 01, couverts par les planches à venir :
- ~~jardinier : `walk_left` dessiné, arrosage bas et haut, actions → 02~~ (fait) ;
- ~~floraison du poivron, distincte du fruit vert → 03~~ (fait) ;
- bordure de briques droite → 08 ;
- états `isolee` et `retiree` → 07 (`retiree` est déjà rendu par le contenant vide).

## Espèces retenues

Les cultures les plus citées pour une serre amateur sont la tomate (de loin la première), le poivron ou piment, le concombre, l'aubergine, les salades et feuilles (laitue, épinard, kale), puis les aromatiques (basilic, persil, ciboulette, coriandre, thym, romarin, menthe). Viennent ensuite le fraisier, le melon, la courgette, le radis, la carotte et le pois. En hydroponie, la laitue est la culture la plus facile en NFT comme en DWC. Basilic, menthe, persil, coriandre et fraisier (NFT) y réussissent aussi. Sources : [Rhino Greenhouses](https://www.rhinogreenhouses.co.uk/pages/common-greenhouse-crops), [The Gardening Dad](https://thegardeningdad.com/best-vegetables-to-grow-in-a-greenhouse/), [Gardening Channel – herbes](https://www.gardeningchannel.com/top-herbs-home-greenhouse/), [1000Bulbs – hydroponie](https://blog.1000bulbs.com/home/15-best-hydroponics-foods), [Bright Lane Gardens](https://brightlanegardens.com/?p=3973), [OBI – légumes en serre](https://www.obi.ch/fr/magazine/jardin/serres/cultiver-des-legumes-en-serre), [Truffaut](https://www.truffaut.com/4-idees-pour-cultiver-sous-serre.html), [Agri-Réseau – légumes de serre](https://www.agrireseau.net/era/documents/S'établir%209%20-%20potentiel%20leg%20serre%20(08-02).pdf).

| Espèce (modèle) | Clé sprite | Planche | Stades dessinés | Remarque visuelle |
|---|---|---|---|---|
| tomate, fraisier, poivron, basilic | `tomato`, `strawberry`, `pepper`, `basil` | 01 | ✅ 5 | floraison du poivron prise sur la planche 03 |
| piment | `chili` | 03 | ✅ 5 | petits fruits fins rouges, port compact |
| aubergine | `eggplant` | 03 | ✅ 5 | fleurs violettes, fruits violet foncé brillants |
| concombre | `cucumber` | 03 | ✅ 5 | grimpant sur un tuteur ou une ficelle, fleurs jaunes |
| courgette | `zucchini` | 03 | ✅ 5 | larges feuilles, grande fleur jaune, fruit vert foncé |
| melon | `melon` | 03 | ✅ 5 | rampant, fruit rond brodé |
| laitue | `lettuce` | 04 | ✅ 5 | rosette ; récolte = pomme dense ; la floraison est une montée en graine |
| laitue rouge (feuille de chêne) | `red_lettuce` | 04 | ✅ 5 | feuilles découpées rouge bordeaux |
| épinard | `spinach` | 04 | ✅ 5 | feuilles vert foncé lisses |
| roquette | `arugula` | 04 | ✅ 5 | feuilles découpées, fleurs crème |
| mâche | `lambs_lettuce` | 04 | ✅ 4 | petite rosette ronde |
| blette | `chard` | 04 | ✅ 5 | côtes colorées rouge et jaune |
| chou kale | `kale` | 04 | ✅ 5 | feuilles frisées vert bleuté |
| menthe | `mint` | 05 | 5 | tiges carrées, feuilles dentées vert clair |
| persil | `parsley` | 05 | 5 | feuilles plates ou frisées en touffe |
| ciboulette | `chives` | 05 | 5 | tiges creuses, pompons mauves |
| coriandre | `cilantro` | 05 | 5 | feuilles lobées puis fines, ombelles blanches |
| thym | `thyme` | 05 | 4 | petit buisson ligneux gris-vert |
| romarin | `rosemary` | 05 | 4 | aiguilles, fleurs bleu pâle |
| radis | `radish` | 06 | 4 | collet rouge visible à la récolte |
| carotte | `carrot` | 06 | 4 | fanes plumeuses, collet orange |
| haricot à rames | `bean` | 06 | 5 | sur rame, fleurs blanches, gousses |
| petit pois | `pea` | 06 | 5 | vrilles, gousses vert clair |
| oignon | `onion` | 06 | 4 | tiges tubulaires, bulbe à la récolte |
| micro-pousses | `microgreens` | 06 | 3 | barquette dense |
| plante générique | `generic` | 06 | 5 | pousse neutre sans fruit, remplace le semis de tomate actuel |

`stades_modele` relie les 5 stades du modèle (`semis`, `croissance`, `floraison`, `fructification`, `recolte`) aux colonnes dessinées. Pour une feuille sans fruit, `fructification` et `recolte` peuvent pointer la même colonne « pomme formée ». La floraison d'une laitue est une montée en graine, à garder pour la fin de cycle.

---

## Planche 02 — Jardinier : actions

> ✅ **Fait** (`planche_02`, 44 sprites). Les 12 animations demandées sont toutes là, regroupées par 3 sur chaque rangée de la planche (aperçu : `decoupe/planche_02/apercu.png`). Écarts :
> - le « Zz » du sommeil est perdu à la découpe (fragment 36, inutilisé) : la bulle du jeu le remplace ;
> - l'inspection inclut la jeune plante du dessin ;
> - `carry_envelope` est dessiné plus grand que le reste de la planche : `"echelle_propre": true` ;
> - le portrait a sa propre `size` `[32, 32]` ;
> - le jardinier de cette planche est 2× plus grand que celle de la planche 01 : l'atlas calcule une échelle par planche.

```
[style preamble]

Character animation sheet of the SAME gardener as the reference (straw hat, green apron,
brown boots), 16x24 game pixels per frame, same scale as the reference walking frames.
Rows (left to right = animation frames), 5 frames per row unless stated:
1. walk left (5 frames), drawn, not mirrored
2. watering can, facing down (4 frames, water drops falling)
3. watering can, facing up / seen from behind (4 frames)
4. inspecting a plant with a magnifying glass, crouched, facing right (4 frames)
5. inspecting with magnifying glass, facing down (4 frames)
6. flipping a wall switch, seen from behind (3 frames)
7. dosing with a small pipette over a bottle, facing right (4 frames)
8. writing in a small notebook, facing down (4 frames)
9. tapping a small white sensor box with one finger, facing right (3 frames)
10. sleeping seated on a wooden bench, "Zz" above (3 frames, include the bench)
11. carrying a cream envelope with both hands, walking down (4 frames)
12. one large portrait of the gardener's face and hat, 32x32 game pixels, smiling
```

Bloc manifeste : animations de `assets.characters.gardener.animations`. Le jeu cherche ces noms dans l'ordre et se replie sur `idle` en attendant :

```json
"walk_left":      { "frames": 5, "source": { "sheet": "planche_02", "sprites": [ ... ] } },
"watering_down":  { "frames": 4, "source": ... },
"watering_up":    { "frames": 4, "source": ... },
"inspect_right":  { "frames": 4, "source": ... },
"inspect_down":   { "frames": 4, "source": ... },
"switch":         { "frames": 3, "source": ... },
"dose":           { "frames": 4, "source": ... },
"notebook":       { "frames": 4, "source": ... },
"tap":            { "frames": 3, "source": ... },
"sleep":          { "frames": 3, "fps": 2, "source": ... },
"carry_envelope": { "frames": 4, "source": ... },
"portrait":       { "frames": 1, "source": ... }
```

`walk_left` dessiné remplace le miroir : retirer `flip_x` et `miroir_de`. Les directions absentes (`inspect_left`…) restent jouées en miroir de la droite.

## Planche 03 — Solanacées et cucurbitacées

> ✅ **Fait** (`planche_03`, 78 sprites) : piment, aubergine, concombre, courgette, melon ; floraison du poivron (sprites 76–78), insérée dans `pepper` par des cases `{"sheet": "planche_03", "n": …}`.

```
[style preamble]

Plant growth sheet. Each block = one species: 3 rows (health) x 5 columns (growth stages).
Rows: 1 healthy, 2 yellowing leaves (under-fed / to watch), 3 sick (brown spots,
drooping leaves). Columns: seedling, young plant, flowering, green fruit, ripe fruit.
Plant size: 16x32 game pixels (tall plants) on a small soil mound, same scale as the
tomatoes of the reference.
Blocks, top to bottom:
A. chili pepper: compact bush, thin pointed fruits green then bright red
B. eggplant: purple star flowers, glossy dark purple fruits
C. cucumber: climbing on a thin bamboo stake with string, yellow flowers, long green fruits
D. zucchini: wide lobed leaves, big yellow flower, dark green fruit at the base
E. melon: sprawling vine, round netted fruit green then beige-orange
F. one extra row of 3 bell pepper plants at the FLOWERING stage only (white flowers,
   no fruit): healthy, yellowing, sick
```

Bloc manifeste, une entrée par espèce dans `assets.plants` (modèle : `tomato`) :

```json
"eggplant": {
  "especes": ["aubergine"],
  "stades_modele": { "semis": 0, "croissance": 1, "floraison": 2, "fructification": 3, "recolte": 4 },
  "size": [16, 32],
  "growth_stages": ["seedling", "young", "flowering", "green_fruit", "ripe_fruit"],
  "health_states": ["healthy", "yellowing", "sick"],
  "source": { "sheet": "planche_03", "layout": "rows = health_states, columns = growth_stages",
              "sprites": [[...], [...], [...]] }
}
```

Clés : `chili` (`["piment"]`, retirer « piment » des `especes` de `pepper`), `eggplant`, `cucumber` (`["concombre"]`), `zucchini` (`["courgette"]`), `melon`. Pour la floraison du poivron, insérer une colonne `flowering` dans `pepper` (5 stades) et remettre `stades_modele` à `0…4`.

## Planche 04 — Salades et feuilles

> ✅ **Fait** (`planche_04`, 109 sprites). Taille retenue `[16, 24]` au lieu de 16×16 : sinon, la tige montée écraserait la rosette à environ 11 px. Écarts :
> - blette et kale ont 6 colonnes : la 4e est écartée ;
> - la blette « jaunissante » a des côtes jaunes ;
> - la bande NFT (sprite 109, d'un seul tenant) n'est pas au manifeste : `suggested_additions.drawn_not_wired`.

```
[style preamble]

Leafy greens growth sheet, 16x16 game pixels per plant (low rosettes) on a soil mound.
Same block layout: 3 rows (healthy, yellowing, sick with brown spots / rot) x 5 columns
(seedling, young rosette, growing, full head ready to harvest, bolting with a flower stalk).
Blocks: A. butterhead lettuce (light green)  B. red oak-leaf lettuce  C. spinach
D. arugula (cream flowers when bolting)  E. lamb's lettuce (4 columns, no bolting)
F. Swiss chard with red and yellow stems  G. curly kale (blue-green)
Also draw block A once more as seen in a white NFT channel hole (net cup visible),
5 stages healthy only, so hydroponic lettuces sit in the channel.
```

Clés : `lettuce` (`["laitue", "salade"]`), `red_lettuce` (`["laitue rouge", "feuille de chêne"]`), `spinach` (`["epinard"]`), `arugula` (`["roquette"]`), `lambs_lettuce` (`["mache"]`), `chard` (`["blette", "bette"]`), `kale` (`["chou kale", "kale"]`). Mapping des stades : `{ "semis": 0, "croissance": 1, "floraison": 4, "fructification": 3, "recolte": 3 }`, la colonne 2 servant d'intermédiaire. La variante en godet NFT sera branchée plus tard (sprite par mode de culture).

## Planche 05 — Aromatiques

> ⬜ **À faire** (priorité 1). En jeu : automatique.

```
[style preamble]

Herb growth sheet, 16x16 game pixels per plant on a soil mound, 3 rows (healthy,
yellowing, sick) x 5 columns (seedling, young, bushy, flowering, cut back after harvest).
Blocks: A. mint (square stems, serrated light green leaves, lilac flower spikes)
B. flat-leaf parsley  C. chives (hollow tubes, round mauve pompom flowers)
D. cilantro (lobed leaves then feathery, white umbels)
E. thyme (4 columns: woody grey-green mini shrub, tiny pink flowers)
F. rosemary (4 columns: needle leaves, pale blue flowers)
```

Clés : `mint` (`["menthe"]`), `parsley` (`["persil"]`), `chives` (`["ciboulette"]`), `cilantro` (`["coriandre"]`), `thyme` (`["thym"]`), `rosemary` (`["romarin"]`). Mapping : `{ "semis": 0, "croissance": 1, "floraison": 3, "fructification": 2, "recolte": 4 }`.

## Planche 06 — Racines, légumineuses, divers, plante générique

> ⬜ **À faire** (priorité 4). En jeu : automatique pour les espèces ; la plante générique en matrice demande du code.

```
[style preamble]

Growth sheet, 3 rows (healthy, yellowing, sick) per block:
A. radish, 4 columns, 16x16: sprout, leaves, larger leaves, red root top showing
B. carrot, 4 columns, 16x16: sprout, feathery tops, bushy tops, orange shoulder showing
C. pole bean on a wooden stake, 5 columns, 16x32: sprout, climbing, white flowers,
   young pods, full green pods
D. garden pea with tendrils on a small trellis, 5 columns, 16x32
E. onion, 4 columns, 16x16: green tubes, thicker, bulb forming, bulb out of the soil
F. microgreens: 3 columns only (sowed tray, sprouting, dense green tray), 32x16
G. GENERIC neutral plant (no fruit, no flower color that suggests a species), 5 columns
   16x32: seedling, young, medium, full leafy plant, plant with small white flowers
```

Clés : `radish` (`["radis"]`), `carrot` (`["carotte"]`), `bean` (`["haricot"]`), `pea` (`["petit pois", "pois"]`), `onion` (`["oignon"]`), `microgreens` (`["micro-pousses"]`, `size: [32, 16]`). Pour **G**, remplacer l'entrée `plants.generic` par une matrice complète (5 stades × 3 santés) et retirer `echelle_de`. Le code utilise pour l'instant une frame unique pour la plante générique : le passage à la matrice reste à brancher dans `mapping.ts`.

## Planche 07 — Santé, ravageurs, états de la plante

> ⬜ **À faire** (priorité 2). En jeu : `bell_jar` branché ; les overlays de symptômes et les outils demandent du code.

```
[style preamble]

Plant health overlay sheet, each item 16x16 or 16x32 game pixels, transparent around:
Row 1 (overlays drawn ON TOP of any plant, semi-sparse so the plant stays visible):
  aphids cluster (small green dots), spider mites with fine web, powdery mildew white
  dust patches, downy mildew yellow-brown patches, leaf spots, whitefly cloud,
  sunburn bleached patch, water drops of over-watering
Row 2 (state props): glass bell jar 16x32 (transparent glass, white highlights, drawn
  as an empty jar to put over a plant), red-and-white quarantine ribbon on two small
  posts, a "!" plant label stake, an empty pot with a few soil crumbs (removed plant),
  a wilted dry plant (under-watering), a rotten root ball (root rot) seen above soil
Row 3: harvest basket with produce, seed packet, watering can, pruning shears,
  hand trowel, fertilizer bottle (inventory icons, 16x16)
```

Blocs manifeste :

```json
"ui": {
  "bell_jar":         { "size": [16, 32], "source": { "sheet": "planche_07", "sprites": [..] } },
  "quarantine_ribbon":{ "size": [16, 16], "source": ... },
  "pest_aphids":      { "size": [16, 16], "source": ... },
  "pest_spider_mites":{ ... }, "disease_powdery_mildew": { ... }, "disease_downy_mildew": { ... },
  "leaf_spots": { ... }, "whitefly": { ... }, "sunburn": { ... }, "overwatering": { ... },
  "wilted_plant": { ... }, "root_rot": { ... },
  "tool_watering_can": { ... }, "tool_shears": { ... }, "tool_trowel": { ... },
  "seed_packet": { ... }, "harvest_basket": { ... }, "fertilizer_bottle": { ... }
}
```

`bell_jar` est déjà branché : il remplace la cloche dessinée par le jeu pour `isolee`. Les autres overlays (classe vision → symptôme) restent à brancher dans `mapping.ts`, sur le modèle de `spores`.

## Planche 08 — Structures et mobilier

> ⬜ **À faire** (priorité 3). En jeu : `brick_border_straight` et `brick_border_vertical` branchés ; le mobilier et le canal NFT demandent du code.

```
[style preamble]

Greenhouse structure sheet, tiles of exactly 16x16 game pixels unless stated, tileable
pieces must connect seamlessly when repeated:
Row 1: low red-brick border, straight horizontal tileable segment; straight vertical
  tileable segment (seen from the side); outer corner; inner corner; T-junction;
  end cap; brick segment with an opening (doorway threshold)
Row 2: greenhouse glass wall panels 16x32: front tileable, back tileable, left side,
  right side, corner, panel with condensation drops, panel with an open roof vent
Row 3: wooden bench 32x16, potting table with pots and soil 32x16, 3-level metal shelf
  with trays 16x32, wall light switch 16x16, small Raspberry Pi box with a green LED
  16x16, coiled garden hose 16x16, water pipe straight / elbow / tee (16x16 each)
Row 4: NFT channel pieces, white PVC 16x16 each: left end cap, straight tileable middle
  with one plant hole, straight middle without hole, right end cap; then the same middle
  piece with flowing water in 4 animation frames
Row 5: floor tiles 16x16 tileable: wet soil, mulch, wood plank path (vertical),
  stepping stones on grass, drain grate
```

Clés de `assets.tiles`, celles que le jeu reconnaît déjà :
- `brick_border_straight` : quand elle existe, les murs bas dessinés par le jeu sont remplacés par des briques ;
- `brick_border_vertical` : murs latéraux (sinon le segment droit est réutilisé).

Les autres clés (`bench`, `potting_table`, `pi_box`, `nft_end_left`, `nft_middle`, `nft_end_right`, `nft_water` en `states.on`…) sont à brancher au fil de l'eau : banc (`Monde.banc`), canal NFT continu par rangée hydro, boîtier Pi pour l'enveloppe de publication.

## Planche 09 — Interface

> ⬜ **À faire** (priorité 5). En jeu : code à écrire (cœurs, jauges, SerrePhone et 9-slice restent en CSS pour l'instant).

```
[style preamble]

Game UI sheet: full heart, half heart, empty heart (8x8 each, drawn at 16x16 cell);
gauge frame 48x8 with green / orange / red fills; small icons 16x16: thermometer,
humidity drop, sun, moon, cloud, rain, lightning bolt (energy), water tap, leaf, bug,
camera, clock, gear, warning sign, check mark, cross mark;
a "SerrePhone" smartphone frame 48x80 in cream and wood with a leaf logo;
wooden button 32x16 in 3 states (normal, hover, pressed) designed for nine-slice;
cream panel 48x48 with wooden border designed for nine-slice (4 px border);
a pointing-hand cursor 16x16 and a green build cursor 16x16.
```

Une clé par élément sous `assets.ui`. Mettre `"rendering": "nine_slice"` sur les panneaux et boutons (fichier PNG séparé exporté par `make sprites`), puis remplacer `dialogue_box.png` dans `ui/pixel.css`.

## Planche 10 — Ambiance

> ⬜ **À faire** (priorité 6). En jeu : code à écrire (les effets restent dessinés par le jeu).

```
[style preamble]

Ambient effects sheet, mostly semi-transparent white or colored pixels, tileable where
stated: condensation fog band 64x16 tileable, sun rays from the top-left 64x64,
pink-purple LED light cone 32x32, warm orange heat haze 32x16, rain drops on glass
32x32 tileable (3 frames), small dust particles (4 frames), fireflies at night (4 frames).
```

Les effets restent dessinés par le jeu (`scenes/Serre.ts`, `dessinerAmbiance`) tant qu'ils ne sont pas branchés. Prévoir les clés `fog_band`, `sun_rays`, `led_cone`, `heat_haze`, `rain_glass`.

## Après chaque planche

- [ ] `decouper_sprites.py --auto`, puis vérification de `apercu.png` : aucun sprite fusionné ni coupé.
- [ ] Planche déclarée dans `sources` et assets ajoutés au manifeste, avec `especes` et `stades_modele` pour les plantes.
- [ ] `make sprites`, puis lecture de `atlas_apercu.png` : échelles cohérentes, voile effacé.
- [ ] `cd frontend && npm test` : `mapping.test.ts` vérifie que chaque espèce × stade × santé donne une frame existante.
- [ ] `/jeu?demo=1` : ajouter l'espèce à `public/demo/serre-demo.json` pour la voir en situation.
- [ ] Origine notée dans `frontend/public/sprites/LICENCES.md`.
- [ ] Mettre à jour le tableau [État d'avancement](#état-davancement) et la ligne de statut de la planche (⬜ → ✅).
