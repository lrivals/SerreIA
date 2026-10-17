# Sprites : origine et licences

| Fichier source | Origine | Licence / usage |
|---|---|---|
| `sprites-src/brut/planche_01.png` | générée avec ChatGPT (génération d'images), réduite et nettoyée par `tools/construire_atlas.py` | usage du projet ; pas d'asset tiers |
| `sprites-src/brut/planche_02.png` (actions du jardinier) | générée avec ChatGPT le 17/10/2026, prompt de `sprites-src/PROMPTS.md` | usage du projet ; pas d'asset tiers |
| `sprites-src/brut/planche_03.png` (solanacées et cucurbitacées) | générée avec ChatGPT le 17/10/2026, prompt de `sprites-src/PROMPTS.md` | usage du projet ; pas d'asset tiers |
| `sprites-src/brut/planche_04.png` (salades et feuilles) | générée avec ChatGPT le 17/10/2026, prompt de `sprites-src/PROMPTS.md` | usage du projet ; pas d'asset tiers |

`atlas.png`, `atlas.json` et `ui/*.png` sont produits par `make sprites` à partir de `sprites-src/` : ne pas les éditer à la main. Ajouter une ligne par nouvelle planche (outil, date, pack et licence s'il s'agit d'un pack téléchargé).
