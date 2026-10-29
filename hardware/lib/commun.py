"""FreeCAD helpers shared by the parts of hardware/pieces (docs/20).

Conventions: millimetres, Z up, every helper returns a new `Part.Shape` (no in-place
transformation), built at the origin unless a position is given.
"""

import math

import FreeCAD as App
import Part

V = App.Vector
ORIG = V(0, 0, 0)
X, Y, Z = V(1, 0, 0), V(0, 1, 0), V(0, 0, 1)


def cyl(d: float, h: float, x=0.0, y=0.0, z=0.0, axe=Z) -> Part.Shape:
    return Part.makeCylinder(d / 2, h, V(x, y, z), axe)


def boite(lo: float, w: float, h: float, x=0.0, y=0.0, z=0.0, centre=False) -> Part.Shape:
    """Box of size lo × w × h; `centre`: centred in X and Y on (x, y), base at z."""
    if centre:
        x, y = x - lo / 2, y - w / 2
    return Part.makeBox(lo, w, h, V(x, y, z))


def boite_arrondie(lo: float, w: float, h: float, r: float, x=0.0, y=0.0, z=0.0) -> Part.Shape:
    """Box centred on (x, y) with vertical edges rounded to r."""
    r = min(r, lo / 2 - 0.01, w / 2 - 0.01)
    coeur = boite(lo - 2 * r, w, h, x, y, z, centre=True).fuse(
        boite(lo, w - 2 * r, h, x, y, z, centre=True)
    )
    for sx in (-1, 1):
        for sy in (-1, 1):
            coeur = coeur.fuse(cyl(2 * r, h, x + sx * (lo / 2 - r), y + sy * (w / 2 - r), z))
    return coeur.removeSplitter()


def tube(d_ext: float, d_int: float, h: float, x=0.0, y=0.0, z=0.0, axe=Z) -> Part.Shape:
    plein = cyl(d_ext, h, x, y, z, axe)
    trou = Part.makeCylinder(d_int / 2, h + 2, V(x, y, z) - V(axe).normalize(), axe)
    return plein.cut(trou)


def hexagone(s: float, h: float, x=0.0, y=0.0, z=0.0) -> Part.Shape:
    """Hexagonal prism, `s` across flats (nut trap, bolt head)."""
    r = s / math.sqrt(3)
    pts = [
        V(x + r * math.cos(math.radians(a)), y + r * math.sin(math.radians(a)), z)
        for a in range(0, 360, 60)
    ]
    return Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 0, h))


def piquet(largeur: float, longueur: float, ep: float, x=0.0, y=0.0) -> Part.Shape:
    """Stake hanging from (x, y) towards -Y, pointed at its end, ep thick from z = 0."""
    pts = [
        V(x - largeur / 2, y, 0),
        V(x + largeur / 2, y, 0),
        V(x + largeur / 2, y - longueur + largeur, 0),
        V(x, y - longueur, 0),
        V(x - largeur / 2, y - longueur + largeur, 0),
    ]
    return Part.Face(Part.makePolygon(pts + [pts[0]])).extrude(V(0, 0, ep))


def secteur(r_ext: float, r_int: float, h: float, angle: float) -> Part.Shape:
    """Ring sector around Z, from +X counter-clockwise over `angle` degrees."""
    s = Part.makeCylinder(r_ext, h, ORIG, Z, angle)
    return s.cut(Part.makeCylinder(r_int, h + 2, V(0, 0, -1), Z))


def pince_tube(d: float, ep: float, largeur: float, enveloppe: float = 210.0) -> Part.Shape:
    """C clip around a tube of Ø d (axis Z, from z = 0 to `largeur`), opening towards -Y.
    The tips are rounded (radius ep / 2) so the clip snaps on without a sharp edge."""
    r = d / 2
    c = secteur(r + ep, r, largeur, enveloppe)
    rm = r + ep / 2
    for a in (0.0, enveloppe):
        a = math.radians(a)
        c = c.fuse(cyl(ep, largeur, rm * math.cos(a), rm * math.sin(a)))
    milieu_ouverture = enveloppe + (360 - enveloppe) / 2
    return c.rotated(ORIG, Z, 270 - milieu_ouverture).removeSplitter()


def bague_tpu(d: float, d_ext: float, h: float = 4.0) -> Part.Shape:
    """TPU ring holding a probe at its depth by friction (inner Ø 0.4 mm under the probe)."""
    return tube(d_ext, d - 0.4, h)


def passe_sonde(d: float, jeu: float, paroi: float, h: float, x=0.0, y=0.0, z=0.0):
    """(boss, hole) of a probe gland: a through hole d + jeu and a counterbore receiving a
    `bague_tpu(d, d + 4)`. Fuse the boss, then cut the hole."""
    d_bague = d + 4
    bossage = cyl(d_bague + 2 * paroi, h, x, y, z)
    trou = cyl(d + jeu, h + 40, x, y, z - 20).fuse(cyl(d_bague + jeu, 4.2, x, y, z + h - 4))
    return bossage, trou


def trou_insert_m3(p, x=0.0, y=0.0, z=0.0, axe=Z) -> Part.Shape:
    """Hole for an M3 heat-set insert whose mouth is at (x, y, z), going along -axe."""
    a = V(axe).normalize()  # copy: normalize() works in place
    return Part.makeCylinder(
        p.insert_m3_d / 2, p.insert_m3_h + 1, V(x, y, z) - a * p.insert_m3_h, a
    )


def graduations(r: float, pas_deg: float, h: float, debut=-90.0, fin=90.0, z=0.0):
    """Raised ticks on a disc of radius r (long tick every 3 steps) for an angle mark."""
    traits = []
    n = int(round((fin - debut) / pas_deg))
    for i in range(n + 1):
        a = debut + i * pas_deg
        long = 4.0 if i % 3 == 0 else 2.0
        t = boite(long, 0.8, h, r - long, -0.4, z).rotated(ORIG, Z, a)
        traits.append(t)
    return traits[0].fuse(traits[1:]) if len(traits) > 1 else traits[0]


def arrondir(shape: Part.Shape, r: float, edges=None) -> Part.Shape:
    """Fillet `edges` (default: all); keeps the sharp shape, with a warning, when OCC fails."""
    try:
        return shape.makeFillet(r, edges if edges is not None else shape.Edges)
    except Exception as e:  # OCC raises Part.OCCError or a plain RuntimeError
        App.Console.PrintWarning(f"fillet r={r} failed ({e}): sharp edges kept\n")
        return shape


def texte(s: str, h: float, ep: float, police: str, x=0.0, y=0.0, z=0.0) -> Part.Shape:
    """Text of cap height ~h extruded by ep, left baseline at (x, y, z)."""
    lettres = Part.makeWireString(s, police, h, 0)
    faces = [Part.Face(w, "Part::FaceMakerBullseye") for w in lettres if w]
    if not faces:
        raise ValueError(f"empty text {s!r}")
    solide = Part.makeCompound(faces).extrude(V(0, 0, ep))
    return solide.translated(V(x, y, z))


def matrice(cellules: list[list[int]], module: float, ep: float, x=0.0, y=0.0, z=0.0):
    """Raised squares of a 0/1 matrix (QR code), row 0 at the top, origin bottom-left."""
    n = len(cellules)
    carres = [
        boite(module, module, ep, x + j * module, y + (n - 1 - i) * module, z)
        for i, ligne in enumerate(cellules)
        for j, v in enumerate(ligne)
        if v
    ]
    return carres[0].fuse(carres[1:]).removeSplitter()
