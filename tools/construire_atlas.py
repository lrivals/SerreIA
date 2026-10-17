"""Atlas du jeu pixel art depuis le manifeste `sprites-src/sprites.json` (doc 13 §2).

Pour chaque asset dont `source.sprites` est rempli, les sprites découpés
(`decoupe/<planche>/sprite_NNN.png`, `tools/decouper_sprites.py --auto`) sont nettoyés
(voile blanc semi-transparent des images générées), recadrés, réduits à `size × facteur`
avec une échelle commune à toutes les images de l'asset (les stades d'une plante gardent
leurs proportions), puis rangés dans un atlas Phaser (JSON Hash).

Sorties :
- `frontend/public/sprites/atlas.png` + `atlas.json` ;
- `frontend/public/sprites/ui/<cle>.png` pour les éléments 9-slice (bordures CSS) ;
- `frontend/src/game/catalogue.gen.json` : ce que le jeu sait afficher (espèce × stade ×
  santé, contenants par type, actionneurs par `Actuator`, capteurs, animations). Le jeu ne
  lit que ce catalogue : ajouter une planche = découper, compléter le manifeste, relancer ;
- `sprites-src/atlas_apercu.png` : l'atlas agrandi ×3 sur damier, pour juger la réduction.

    .venv/bin/python tools/construire_atlas.py        # ou : make sprites
"""

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

RACINE = Path(__file__).resolve().parents[1]
MANIFESTE = RACINE / "sprites-src" / "sprites.json"
SORTIE = RACINE / "frontend" / "public" / "sprites"
CATALOGUE = RACINE / "frontend" / "src" / "game" / "catalogue.gen.json"
APERCU = RACINE / "sprites-src" / "atlas_apercu.png"

# Un pixel source appartient au sprite au-dessus de cet alpha (le fond flou des planches
# générées laisse un halo plus transparent autour des objets).
ALPHA_MIN = 110
# Voile : pixel clair, peu saturé et pas tout à fait opaque (carrés blancs sous les
# actionneurs, capteurs et cuves de planche_01).
VOILE_ALPHA = 245
VOILE_CLAIR = 170
VOILE_SATURATION = 40
# Part de pixels opaques d'un bloc pour que le pixel réduit soit opaque.
COUVERTURE = 0.5
PADDING = 2
LARGEUR_ATLAS = 1024
FPS = 8


# --- traitement d'une image -----------------------------------------------------------


def nettoyer(img: np.ndarray, voile: bool = True) -> np.ndarray:
    """RGBA → RGBA à alpha binaire : halo et voile blanc effacés."""
    rgb = img[..., :3].astype(int)
    alpha = img[..., 3].astype(int)
    garde = alpha > ALPHA_MIN
    if voile:
        mn, mx = rgb.min(-1), rgb.max(-1)
        garde &= ~((alpha < VOILE_ALPHA) & (mn > VOILE_CLAIR) & (mx - mn < VOILE_SATURATION))
    out = img.copy()
    out[..., 3] = np.where(garde, 255, 0)
    return out


def recadrer(img: np.ndarray) -> np.ndarray:
    """Recadre sur les pixels opaques (image vide : 1×1 transparent)."""
    ys, xs = np.nonzero(img[..., 3])
    if len(ys) == 0:
        return np.zeros((1, 1, 4), np.uint8)
    return img[ys.min() : ys.max() + 1, xs.min() : xs.max() + 1]


def reduire(img: np.ndarray, largeur: int, hauteur: int) -> np.ndarray:
    """Réduction « pixel art » : chaque pixel cible prend la couleur dominante (moyenne du
    groupe de couleurs le plus fréquent) des pixels opaques de son bloc, sans mélange."""
    h, w = img.shape[:2]
    ys = np.linspace(0, h, hauteur + 1).round().astype(int)
    xs = np.linspace(0, w, largeur + 1).round().astype(int)
    out = np.zeros((hauteur, largeur, 4), np.uint8)
    for i in range(hauteur):
        y0, y1 = ys[i], max(ys[i + 1], ys[i] + 1)
        for j in range(largeur):
            x0, x1 = xs[j], max(xs[j + 1], xs[j] + 1)
            bloc = img[min(y0, h - 1) : min(y1, h), min(x0, w - 1) : min(x1, w)].reshape(-1, 4)
            opaques = bloc[bloc[:, 3] > 0]
            if len(opaques) < COUVERTURE * len(bloc):
                continue
            rgb = opaques[:, :3].astype(int)
            cles = (rgb[:, 0] >> 4) << 8 | (rgb[:, 1] >> 4) << 4 | rgb[:, 2] >> 4
            valeurs, comptes = np.unique(cles, return_counts=True)
            dominante = rgb[cles == valeurs[comptes.argmax()]]
            out[i, j, :3] = dominante.mean(0).round()
            out[i, j, 3] = 255
    return out


def placer(img: np.ndarray, largeur: int, hauteur: int, ancrage: str) -> np.ndarray:
    """Pose l'image sur un canevas transparent, centrée horizontalement, en bas ou au centre."""
    h, w = img.shape[:2]
    out = np.zeros((hauteur, largeur, 4), np.uint8)
    x = (largeur - w) // 2
    y = hauteur - h if ancrage == "bas" else (hauteur - h) // 2
    out[y : y + h, x : x + w] = img
    return out


# --- manifeste → assets ---------------------------------------------------------------


@dataclass
class Asset:
    categorie: str
    cle: str
    conf: dict
    frames: dict[str, tuple[str, int]]  # nom de frame → (planche, numéro de sprite)
    groupes: dict[str, list[str]] = field(default_factory=dict)  # états / animations

    @property
    def mode(self) -> str:
        if self.conf.get("tileable"):
            return "etirer"
        return "hauteur" if self.categorie in ("characters", "plants") else "ajuster"

    @property
    def ancrage(self) -> str:
        return "centre" if self.categorie == "ui" else "bas"


def lister_assets(manifeste: dict) -> list[Asset]:
    """Assets à exporter : ceux dont la source est renseignée, frames nommées
    `<categorie>/<cle>[/<etat>][/<i>]`."""
    assets = []
    for categorie, entrees in manifeste["assets"].items():
        for cle, conf in entrees.items():
            base = f"{categorie}/{cle}"
            if "animations" in conf:
                a = Asset(categorie, cle, conf, {})
                for anim, ac in conf["animations"].items():
                    src = ac.get("source")
                    if not src:
                        continue
                    noms = [f"{base}/{anim}/{i}" for i in range(len(src["sprites"]))]
                    a.frames.update(
                        {n: (src["sheet"], s) for n, s in zip(noms, src["sprites"], strict=True)}
                    )
                    a.groupes[anim] = noms
                if a.frames:
                    assets.append(a)
                continue
            src = conf.get("source")
            if not src or not src.get("sprites"):
                continue
            sheet, sprites = src["sheet"], src["sprites"]
            a = Asset(categorie, cle, conf, {})
            if sprites and isinstance(sprites[0], list):  # matrice santé × stade
                for r, sante in enumerate(conf["health_states"]):
                    for c, stade in enumerate(conf["growth_stages"]):
                        if c < len(sprites[r]):
                            a.frames[f"{base}/{stade}/{sante}"] = (sheet, sprites[r][c])
            elif "states" in conf or "variants" in conf:
                for etat, nums in (conf.get("states") or conf.get("variants")).items():
                    noms = [f"{base}/{etat}/{i}" for i in range(len(nums))]
                    a.frames.update({n: (sheet, s) for n, s in zip(noms, nums, strict=True)})
                    a.groupes[etat] = noms
            else:
                a.frames[base] = (sheet, sprites[0])
            assets.append(a)
    return assets


def charger(manifeste: dict, racine: Path, sheet: str, numero: int) -> np.ndarray:
    s = manifeste["sources"][sheet]
    nom = s.get("file_pattern", "sprite_{n:03d}.png").format(n=numero)
    return np.array(Image.open(racine / s["cut_dir"] / nom).convert("RGBA"))


def rendre(
    manifeste: dict, racine: Path, assets: list[Asset], facteur: int
) -> dict[str, np.ndarray]:
    """Nom de frame → image réduite. Échelle commune à toutes les frames d'un asset
    (ou reprise d'un autre asset avec `echelle_de`)."""
    sources: dict[str, dict[str, np.ndarray]] = {}
    echelles: dict[str, float] = {}
    for a in assets:
        voile = a.conf.get("nettoyage", True) is not False
        sources[a.cle] = {
            n: recadrer(nettoyer(charger(manifeste, racine, *src), voile))
            for n, src in a.frames.items()
        }
        tw, th = (v * facteur for v in a.conf["size"])
        hmax = max(i.shape[0] for i in sources[a.cle].values())
        wmax = max(i.shape[1] for i in sources[a.cle].values())
        echelles[a.cle] = th / hmax if a.mode == "hauteur" else min(tw / wmax, th / hmax)

    images = {}
    for a in assets:
        tw, th = (v * facteur for v in a.conf["size"])
        e = echelles.get(a.conf.get("echelle_de", a.cle), echelles[a.cle])
        reduites = {}
        for nom, img in sources[a.cle].items():
            if a.mode == "etirer":
                reduites[nom] = reduire(img, tw, th)
            else:
                h, w = img.shape[:2]
                reduites[nom] = reduire(img, max(1, round(w * e)), max(1, min(th, round(h * e))))
        largeur = max([tw] + [i.shape[1] for i in reduites.values()])
        for nom, img in reduites.items():
            images[nom] = placer(img, largeur, th, a.ancrage)
    return images


# --- atlas ----------------------------------------------------------------------------


def ranger(
    tailles: dict[str, tuple[int, int]], largeur: int = LARGEUR_ATLAS
) -> tuple[dict, int, int]:
    """Rangement en étagères (les plus hautes d'abord). Retourne {nom: (x, y)}, largeur,
    hauteur de l'atlas."""
    positions, x, y, etagere = {}, PADDING, PADDING, 0
    largeur = max(largeur, max((w for w, _ in tailles.values()), default=0) + 2 * PADDING)
    for nom in sorted(tailles, key=lambda n: (-tailles[n][1], n)):
        w, h = tailles[nom]
        if x + w + PADDING > largeur:
            x, y, etagere = PADDING, y + etagere + PADDING, 0
        positions[nom] = (x, y)
        x += w + PADDING
        etagere = max(etagere, h)
    return positions, largeur, y + etagere + PADDING


def atlas(images: dict[str, np.ndarray]) -> tuple[Image.Image, dict]:
    tailles = {n: (i.shape[1], i.shape[0]) for n, i in images.items()}
    positions, w, h = ranger(tailles)
    feuille = np.zeros((h, w, 4), np.uint8)
    frames = {}
    for nom, (x, y) in positions.items():
        iw, ih = tailles[nom]
        feuille[y : y + ih, x : x + iw] = images[nom]
        frames[nom] = {
            "frame": {"x": x, "y": y, "w": iw, "h": ih},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": iw, "h": ih},
            "sourceSize": {"w": iw, "h": ih},
        }
    meta = {
        "app": "tools/construire_atlas.py",
        "image": "atlas.png",
        "size": {"w": w, "h": h},
        "scale": "1",
    }
    return Image.fromarray(feuille), {"frames": frames, "meta": meta}


# --- catalogue ------------------------------------------------------------------------


def catalogue(
    manifeste: dict, assets: list[Asset], images: dict[str, np.ndarray], facteur: int
) -> dict:
    """Ce que le jeu sait afficher, dans les termes du modèle de données (docs/09)."""
    modele = manifeste.get("modele", {})
    sante_modele = modele.get("sante", {})
    stades_modele = modele.get("stades", [])
    taille = lambda nom: [images[nom].shape[1], images[nom].shape[0]]  # noqa: E731
    cat: dict = {
        "version": manifeste.get("version"),
        "tuile": manifeste["grid"]["tile_size"][0],
        "facteur": facteur,
        "personnages": {},
        "plantes": {"generique": None, "especes": {}, "sprites": {}},
        "contenants": [],
        "tuiles": {},
        "actionneurs": {},
        "capteurs": [],
        "ui": {},
    }
    for a in assets:
        c = a.conf
        premier = next(iter(a.frames))
        if a.categorie == "characters":
            anims = {}
            for anim, ac in c["animations"].items():
                noms = a.groupes.get(anim) or a.groupes.get(ac.get("miroir_de", ""))
                if noms:
                    anims[anim] = {
                        "frames": noms,
                        "flip_x": bool(ac.get("flip_x")),
                        "fps": ac.get("fps", 4 if len(noms) <= 2 else FPS),
                    }
            cat["personnages"][a.cle] = {"taille": taille(premier), "animations": anims}
        elif a.categorie == "plants":
            if "growth_stages" not in c:
                cat["plantes"]["generique"] = premier
                continue
            stades = {}
            for stade, col in c.get("stades_modele", {}).items():
                if stade not in stades_modele and stades_modele:
                    continue
                gs = c["growth_stages"][col]
                stades[stade] = {
                    s_mod: f"plants/{a.cle}/{gs}/{s_spr}"
                    for s_mod, s_spr in sante_modele.items()
                    if f"plants/{a.cle}/{gs}/{s_spr}" in a.frames
                }
            cat["plantes"]["sprites"][a.cle] = {"taille": taille(premier), "stades": stades}
            for espece in c.get("especes", []):
                cat["plantes"]["especes"][espece] = a.cle
        elif a.categorie == "containers":
            cat["contenants"].append(
                {
                    "cle": a.cle,
                    "type": c.get("type"),
                    "materiau": c.get("materiau"),
                    "frame": premier,
                    "taille": taille(premier),
                }
            )
        elif a.categorie == "tiles":
            cat["tuiles"][a.cle] = {"frame": premier, "taille": taille(premier)}
        elif a.categorie == "devices":
            cat["actionneurs"][c.get("actuator", a.cle)] = {
                "cle": a.cle,
                "taille": taille(premier),
                "etats": a.groupes,
                "effets": c.get("effects", {}),
            }
        elif a.categorie == "sensors":
            cat["capteurs"].append(
                {
                    "cle": a.cle,
                    "famille": c.get("famille"),
                    "statut": c.get("status"),
                    "frame": premier if not a.groupes else None,
                    "etats": a.groupes or None,
                    "taille": taille(premier),
                }
            )
        elif a.categorie == "ui":
            entree = {"taille": taille(premier)}
            if a.groupes:
                entree["etats"] = a.groupes
            else:
                entree["frame"] = premier
            if c.get("rendering") == "nine_slice":
                entree["fichier"] = f"sprites/ui/{a.cle}.png"
            cat["ui"][a.cle] = entree
    return cat


def apercu(feuille: Image.Image, zoom: int = 3) -> Image.Image:
    w, h = feuille.size
    damier = np.indices((h, w)).sum(0) // 8 % 2
    fond = np.where(damier[..., None], [200, 200, 200, 255], [235, 235, 235, 255]).astype(np.uint8)
    img = Image.fromarray(fond)
    img.alpha_composite(feuille)
    return img.resize((w * zoom, h * zoom), Image.NEAREST)


def construire(
    manifeste_path: Path,
    sortie: Path,
    catalogue_path: Path,
    apercu_path: Path | None,
    facteur: int | None = None,
) -> dict:
    manifeste = json.loads(manifeste_path.read_text())
    facteur = facteur or manifeste.get("export", {}).get("facteur", 2)
    assets = lister_assets(manifeste)
    images = rendre(manifeste, manifeste_path.parent, assets, facteur)
    feuille, hash_ = atlas(images)
    sortie.mkdir(parents=True, exist_ok=True)
    feuille.save(sortie / "atlas.png")
    (sortie / "atlas.json").write_text(json.dumps(hash_, indent=1))
    for a in assets:
        if a.conf.get("rendering") == "nine_slice":
            (sortie / "ui").mkdir(exist_ok=True)
            Image.fromarray(images[next(iter(a.frames))]).save(sortie / "ui" / f"{a.cle}.png")
    cat = catalogue(manifeste, assets, images, facteur)
    catalogue_path.parent.mkdir(parents=True, exist_ok=True)
    catalogue_path.write_text(json.dumps(cat, indent=1, ensure_ascii=False) + "\n")
    if apercu_path:
        apercu(feuille).save(apercu_path)
    return {"frames": len(images), "taille": feuille.size, "assets": len(assets)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--manifeste", type=Path, default=MANIFESTE)
    p.add_argument("--sortie", type=Path, default=SORTIE)
    p.add_argument("--catalogue", type=Path, default=CATALOGUE)
    p.add_argument("--facteur", type=int, help="défaut : export.facteur du manifeste")
    p.add_argument("--sans-apercu", action="store_true")
    args = p.parse_args()
    r = construire(
        args.manifeste,
        args.sortie,
        args.catalogue,
        None if args.sans_apercu else APERCU,
        args.facteur,
    )
    print(f"{r['assets']} assets, {r['frames']} frames, atlas {r['taille'][0]}×{r['taille'][1]} px")
    print(f"→ {args.sortie / 'atlas.png'}, {args.catalogue}")


if __name__ == "__main__":
    main()
