# Sprites — sources

Pixel art de la vue jeu ([docs/13](../docs/13-interface-jeu-pixel-art.md)).

```
sprites-src/
├── brut/          # sprite sheets telles que générées ou téléchargées (ChatGPT, packs itch.io…)
├── decoupe/       # sprites découpés, un sous-dossier par sprite sheet : decoupe/<nom_image>/sprite_001.png
├── sprites.json   # manifeste : asset → taille cible, états/animations, numéros des sprites sources
├── PROMPTS.md     # prompts des planches suivantes
└── atlas_apercu.png  # aperçu ×3 de l'atlas produit par `make sprites`
```

`sprites.json` relie chaque asset du jeu aux fichiers découpés (`source.sprites` = numéros visibles sur `decoupe/<planche>/apercu.png`). Si une planche est redécoupée avec d'autres réglages, vérifier que la numérotation n'a pas changé.

## Découper une sprite sheet

### Automatique (recommandé)

L'image doit avoir un fond transparent. Le script détecte chaque sprite d'après le canal alpha, les enregistre tous et produit `apercu.png`, où chaque cadre porte son numéro :

```bash
.venv/bin/python tools/decouper_sprites.py sprites-src/brut/<image>.png --auto
```

Vérifier `apercu.png` : un sprite coupé en deux ou deux sprites fusionnés se corrigent en mode manuel.

### Manuel

Le script a besoin d'OpenCV **avec fenêtres** (`opencv-python`) ; celui du `.venv` du projet est la version headless. Environnement dédié, à créer une fois :

```bash
python3 -m venv ~/.venvs/sprites
~/.venvs/sprites/bin/pip install opencv-python
```

Puis, depuis la racine du dépôt :

```bash
~/.venvs/sprites/bin/python tools/decouper_sprites.py sprites-src/brut/<image>.png
```

Sélectionner un sprite à la souris, puis **Entrée** pour l'enregistrer ; **Échap** pour terminer.

## Ensuite : l'atlas du jeu

1. Décrire les nouveaux assets dans `sprites.json` (numéros de `apercu.png`, `especes` et `stades_modele` pour une plante, `type` pour un contenant, `actuator` pour un actionneur, `famille` pour un capteur).
2. `make sprites` (`tools/construire_atlas.py`) : nettoyage du voile, réduction à `size × export.facteur`, atlas `frontend/public/sprites/atlas.{png,json}`, catalogue `frontend/src/game/catalogue.gen.json`, aperçu `atlas_apercu.png` à vérifier.
3. Vérifier en jeu sur `/jeu?demo=1`, et `cd frontend && npm test`.
4. Noter l'origine et la licence dans `frontend/public/sprites/LICENCES.md`.

Retouche manuelle (Aseprite) facultative : retoucher le PNG découpé, puis relancer `make sprites`. Prompts des prochaines planches : [`PROMPTS.md`](PROMPTS.md).
