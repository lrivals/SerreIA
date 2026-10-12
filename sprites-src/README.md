# Sprites — sources

Pixel art de la vue jeu ([docs/13](../docs/13-interface-jeu-pixel-art.md)).

```
sprites-src/
├── brut/          # sprite sheets telles que générées ou téléchargées (ChatGPT, packs itch.io…)
├── decoupe/       # sprites découpés, un sous-dossier par sprite sheet : decoupe/<nom_image>/sprite_001.png
└── sprites.json   # manifeste : asset → taille cible, états/animations, numéros des sprites sources
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

## Ensuite

1. Renommer les sprites découpés (`tomate_floraison_sain.png`, `jardinier_marche_bas_1.png`…).
2. Les ramener à la taille réelle (16×16, 16×24) en *nearest neighbor* et nettoyer les pixels parasites (Aseprite).
3. Noter l'origine et la licence de chaque image dans `LICENCES.md`.
4. Exporter les atlas finaux vers `frontend/public/sprites/` (quand le front existera).
