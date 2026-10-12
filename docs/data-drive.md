# Données sur Google Drive

Les datasets ne passent pas par git. Pour les retrouver sur une autre machine ou sur Colab, chaque jeu prêt est archivé en un tar puis copié sur Google Drive, dans `MyDrive/SerreIA/data/`. Les notebooks (`notebooks/`) et `tools/notebooks/drive_data.py:prepare_data` vont le chercher là.

```
MyDrive/SerreIA/
  data/   <jeu>.tar      un tar non compressé par jeu, liens suivis (arborescence de data/)
  runs/   runs/ reports/ mlruns/colab/   sorties des notebooks Colab, même chemin que dans le dépôt
```

Système repris d'EmbeddedComputervision (skill `drive-data-archives`).

## Mise en place de rclone (une fois par PC)

```bash
sudo apt install rclone
rclone config create gdrive drive scope=drive   # ouvre le navigateur : connexion Google
rclone lsd gdrive:                              # dossiers du Drive
rclone about gdrive:                            # espace libre
```

Les archives vont dans `gdrive:SerreIA/data`. Pour changer de destination : variable `DRIVE_REMOTE` (ex. `DRIVE_REMOTE=autre:Dossier/data`), lue par `tools/get_datasets.sh` et `drive_data.prepare_data`.

## Exporter un jeu

Sur le PC qui a le jeu (marqueur présent, `tools/get_datasets.sh check`) :

```bash
tools/get_datasets.sh push <jeu>…
rclone ls gdrive:SerreIA/data   # tailles sur le Drive
ls -l data_archives/            # doivent être identiques ; data_archives/ peut ensuite être vidé
```

`push` lance `pack` (chemins du jeu sous `data/` → `data_archives/<jeu>.tar`, liens suivis, `*.zip`, `*.tar`, `*.part` et les chemins de `EXCLUDE` exclus), puis `rclone copy`. `data_archives/` est ignoré par git.

| Jeu | Contenu archivé (`data/…`) | Taille | Marqueur (`data/…`) | Sur le Drive | Remarque |
|---|---|---|---|---|---|
| `index` | `index.parquet`, `index_rejets.txt` | 7,4 Mo | `index.parquet` | 12/10/2026 | à repousser après chaque `build_index` |
| `plantvillage` | `plantvillage/{color,segmented}` | 1,53 Go | `plantvillage/segmented/Tomato___healthy` | 12/10/2026 | `grayscale/` exclu (inutilisé) |
| `ccmt` | `ccmt/raw` | 1,36 Go | `ccmt/raw/Tomato/healthy` | 12/10/2026 | `augmented/` (6,9 Go, fuite) exclu |
| `plantdoc` | `plantdoc/{train,test,crops}` | 1,71 Go | `plantdoc/crops/test` | 12/10/2026 | images VOC + crops du classifieur |
| `backgrounds` | `backgrounds` | — | `backgrounds` | — | **à constituer** (docs/03 §3.2) |

Tailles : taille des archives (`ls -l data_archives/`). Après un envoi, remplir la colonne « Sur le Drive » avec la date. Vérifier l'espace avec `rclone about gdrive:` avant un gros envoi.

## Accès

**Un jeu présent est utilisé tel quel ; sinon il est récupéré sur le Drive.** Aucun jeu n'a de téléchargement direct : les sources ont été préparées à la main (docs/02-donnees.md §1).

| Où | Jeu absent |
|---|---|
| PC, ligne de commande | `tools/get_datasets.sh pull <jeu>` |
| PC, notebook | la cellule d'environnement lance `pull` (rclone) ; sinon elle s'arrête avec la commande |
| Colab | Drive monté + `unpack` (lecture séquentielle du tar, extraction sur le disque local) |

```python
drive_data.prepare_data("plantvillage")  # "ready" | "drive" | "rclone" | "download"
drive_data.ensure(["index", "plantvillage"])  # comme les notebooks (Colab ou PC)
```

## Sorties des notebooks

Sur Colab, l'entraînement tourne dans `drive_data.PeriodicSync(drive_data.OUTPUTS)` : `runs/` (checkpoints), `reports/` (évaluations, planches) et `mlruns/colab/` (base MLflow de Colab) sont copiés dans `MyDrive/SerreIA/runs/<même chemin>` toutes les 10 min et à la fin. La cellule d'environnement appelle `restore_all` : une nouvelle session retrouve les runs précédents (notebook 03, reprise du notebook 04).

Sur le PC :

```bash
make harvest       # json, csv, md, png, txt, base MLflow (sans les poids)
make harvest-all   # tout, checkpoints compris
mlflow ui --backend-store-uri sqlite:///mlruns/colab/mlflow.db   # runs faits sur Colab
```

Colab écrit dans une base MLflow séparée (`mlruns/colab/mlflow.db`) : la récupération n'écrase jamais `mlruns/mlflow.db` du PC. Les artefacts MLflow enregistrés sur Colab pointent vers `/content/SerreIA/…` ; les checkpoints utiles sont dans `runs/<run_id>/`.

## Pièges

- Seul le tar est lu sur le Drive, d'un bloc ; jamais les fichiers à travers le montage.
- `pack` écrit `<jeu>.tar.part` puis le renomme : un `.tar` est complet. Un `.part` restant peut être supprimé.
- Gros envoi (> 10 Go) : le Drive met plusieurs minutes à finaliser ; rclone peut renvoyer tout le fichier sans le dire. Ne pas relancer `push` (il reconstruit l'archive) : renvoyer le tar existant puis comparer les tailles :
  `rclone copy data_archives/<jeu>.tar gdrive:SerreIA/data --progress --timeout 30m`.
- `rateLimitExceeded` dans les logs rclone (`-vv`) : limite de l'identifiant client partagé de rclone ; rclone réessaie seul. Pour l'éviter, créer son propre client OAuth (`rclone config`, `client_id`).
- Un jeu modifié localement (nouvel index, nouveaux fonds) doit être repoussé ; `pull` ne remplace jamais un jeu présent.
- L'index référence des chemins de `plantvillage`, `ccmt` et `plantdoc` : repousser `index` en même temps qu'un jeu reconstruit.
