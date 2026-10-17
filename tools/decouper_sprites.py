"""Découpe d'une sprite sheet en sprites individuels (doc 13 §2).

Deux modes :
- `--auto` : détecte chaque sprite d'après le canal alpha et les enregistre tous,
  avec une image `apercu.png` où chaque cadre porte son numéro (fonctionne avec
  l'OpenCV headless du projet) ;
- interactif (par défaut) : sélectionner un sprite à la souris, Entrée/Espace pour
  l'enregistrer, Échap (ou sélection vide) pour terminer. Nécessite OpenCV avec
  interface graphique (`opencv-python`), l'extra `vision` n'ayant que la version headless :
    python3 -m venv ~/.venvs/sprites && ~/.venvs/sprites/bin/pip install opencv-python
    ~/.venvs/sprites/bin/python tools/decouper_sprites.py sprites-src/brut/<image>.png
"""

import argparse
from pathlib import Path

import cv2
import numpy as np

# Alpha au-dessus duquel un pixel appartient sûrement à un sprite : les images générées
# posent certains objets sur des carrés blancs semi-transparents (alpha 140–237).
ALPHA_COEUR = 240
# Un morceau plus petit (aire du cadre en px²) est rattaché au sprite le plus proche :
# tige d'une jeune pousse séparée de sa motte, gouttes d'eau, étincelles.
AIRE_FRAGMENT = 600
DISTANCE_FRAGMENT = 20
# Bande basse (hauteur ≤, en px, cadre dilaté) quasi collée verticalement à un autre
# cadre qu'elle recouvre horizontalement : motte de terre séparée de sa plante.
HAUTEUR_BANDE = 40
ECART_BANDE = 10
# Morceau dont le cadre chevauche celui d'un sprite bien plus grand (aire < ce ratio) :
# objet tenu à la main (flacon, outil), plus gros qu'un simple fragment.
RATIO_CHEVAUCHEMENT = 0.25
MARGE = 4


def sur_fond(image: np.ndarray, couleur=(255, 0, 255)) -> np.ndarray:
    """Composite BGRA → BGR sur un fond uni, pour voir la vraie transparence."""
    if image.ndim != 3 or image.shape[2] != 4:
        return image
    alpha = image[..., 3:] / 255.0
    fond = np.empty_like(image[..., :3])
    fond[:] = couleur
    return (image[..., :3] * alpha + fond * (1 - alpha)).astype(np.uint8)


def detecter(image: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Cadres (x, y, w, h) des sprites, triés par lignes puis de gauche à droite."""
    masque = (image[..., 3] > ALPHA_COEUR).astype(np.uint8)
    masque = cv2.dilate(masque, np.ones((9, 9), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(masque)
    cadres = [list(s[:4]) for s in stats[1:] if s[4] > 30]

    def distance(a, b):
        dx = max(b[0] - (a[0] + a[2]), a[0] - (b[0] + b[2]), 0)
        dy = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]), 0)
        return max(dx, dy)

    def empile(a, b):
        """Bande basse (motte de terre, tige) collée au-dessus ou au-dessous d'un autre cadre."""
        recouvrement = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
        ecart_v = max(b[1] - (a[1] + a[3]), a[1] - (b[1] + b[3]))
        return (
            min(a[3], b[3]) <= HAUTEUR_BANDE
            and recouvrement >= min(a[2], b[2]) / 2
            and ecart_v <= ECART_BANDE
        )

    def chevauche(a, b):
        """Petit cadre dont la boîte recouvre en partie celle d'un cadre bien plus grand."""
        return distance(a, b) == 0 and a[2] * a[3] < RATIO_CHEVAUCHEMENT * b[2] * b[3]

    # Rattacher les fragments au cadre le plus proche, jusqu'à stabilité
    fusion = True
    while fusion:
        fusion = False
        cadres.sort(key=lambda c: c[2] * c[3])
        for i, petit in enumerate(cadres):
            autres = [c for j, c in enumerate(cadres) if j != i]
            if not autres:
                break
            proche = min(autres, key=lambda c: distance(petit, c))
            fragment = (
                petit[2] * petit[3] < AIRE_FRAGMENT and distance(petit, proche) <= DISTANCE_FRAGMENT
            )
            if not fragment:
                proche = next((c for c in autres if empile(petit, c) or chevauche(petit, c)), None)
                if proche is None:
                    continue
            x0, y0 = min(petit[0], proche[0]), min(petit[1], proche[1])
            x1 = max(petit[0] + petit[2], proche[0] + proche[2])
            y1 = max(petit[1] + petit[3], proche[1] + proche[3])
            proche[:] = [x0, y0, x1 - x0, y1 - y0]
            cadres.pop(i)
            fusion = True
            break

    # Retirer la marge de dilatation, puis en remettre une petite (brume, halo)
    h_img, w_img = image.shape[:2]
    resultat = []
    for x, y, w, h in cadres:
        x0, y0 = max(x + 4 - MARGE, 0), max(y + 4 - MARGE, 0)
        x1, y1 = min(x + w - 4 + MARGE, w_img), min(y + h - 4 + MARGE, h_img)
        resultat.append((x0, y0, x1 - x0, y1 - y0))

    # Tri en lignes : un cadre rejoint une ligne si son centre vertical tombe dans la
    # hauteur du premier cadre de cette ligne
    resultat.sort(key=lambda c: c[1] + c[3] / 2)
    lignes: list[list[tuple[int, int, int, int]]] = []
    for c in resultat:
        centre = c[1] + c[3] / 2
        ligne = next((li for li in lignes if li[0][1] <= centre <= li[0][1] + li[0][3]), None)
        if ligne is None:
            lignes.append([c])
        else:
            ligne.append(c)
    return [c for ligne in lignes for c in sorted(ligne)]


def decouper_auto(image: np.ndarray, output_dir: Path) -> int:
    cadres = detecter(image)
    apercu = sur_fond(image)
    for n, (x, y, w, h) in enumerate(cadres, start=1):
        cv2.imwrite(str(output_dir / f"sprite_{n:03d}.png"), image[y : y + h, x : x + w])
        cv2.rectangle(apercu, (x, y), (x + w - 1, y + h - 1), (0, 200, 0), 1)
        for couleur, epaisseur in (((0, 0, 0), 2), ((255, 255, 255), 1)):
            cv2.putText(
                apercu, str(n), (x + 1, y + 10), cv2.FONT_HERSHEY_PLAIN, 0.8, couleur, epaisseur
            )
    cv2.imwrite(str(output_dir / "apercu.png"), apercu)
    return len(cadres)


def decouper_manuel(image: np.ndarray, output_dir: Path) -> int:
    # Reprendre la numérotation si le dossier contient déjà des sprites
    count = len(list(output_dir.glob("sprite_*.png")))
    # selectROI n'affiche pas le canal alpha : on montre l'image sur fond magenta
    preview = sur_fond(image)

    print("Sélectionne un sprite avec la souris.")
    print("Entrée : enregistrer | Échap : terminer")

    while True:
        x, y, w, h = map(
            int,
            cv2.selectROI("Decoupage des sprites", preview, showCrosshair=True, fromCenter=False),
        )
        if w == 0 or h == 0:
            break

        count += 1
        output_path = output_dir / f"sprite_{count:03d}.png"
        cv2.imwrite(str(output_path), image[y : y + h, x : x + w])
        print(f"Enregistré : {output_path}")

    cv2.destroyAllWindows()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", type=Path, help="sprite sheet (PNG, transparence conservée)")
    parser.add_argument(
        "--sortie",
        type=Path,
        default=Path("sprites-src/decoupe"),
        help="dossier de sortie (un sous-dossier au nom de l'image y est créé)",
    )
    parser.add_argument("--auto", action="store_true", help="détection automatique, sans fenêtre")
    args = parser.parse_args()

    image = cv2.imread(str(args.image), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(f"Image introuvable : {args.image}")
    if args.auto and (image.ndim != 3 or image.shape[2] != 4):
        raise ValueError("--auto nécessite une image avec transparence (canal alpha)")

    output_dir = args.sortie / args.image.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    count = decouper_auto(image, output_dir) if args.auto else decouper_manuel(image, output_dir)
    print(f"\nTerminé : {count} sprites dans {output_dir}/")


if __name__ == "__main__":
    main()
