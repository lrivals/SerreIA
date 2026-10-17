// Builder mode inside the greenhouse scene (docs/13 §4): snapping grid, ghost preview (red
// when the tile is forbidden), drag of objects, zone rectangle. Every gesture goes up to
// React through the bus; React calls the existing CRUD routes then the world is rebuilt.
import Phaser from "phaser";
import type { Bus, Outil } from "../bus";
import { tilePx } from "../catalogue";
import { caseLibre, type Monde } from "../monde";
import type { Objet } from "../entities/Objet";

const OK = 0x5d8c45;
const INTERDIT = 0xd94f45;

export class ModeConstruction {
  actif = false;
  outil: Outil = "poser";
  private grille: Phaser.GameObjects.Graphics;
  private fantome: Phaser.GameObjects.Graphics;
  private rect: { x0: number; y0: number; x1: number; y1: number } | null = null;
  private glisse: { objet: Objet; x: number; y: number } | null = null;

  constructor(
    private scene: Phaser.Scene,
    private bus: Bus,
    private monde: () => Monde | null,
  ) {
    this.grille = scene.add.graphics().setDepth(90_000);
    this.fantome = scene.add.graphics().setDepth(90_001);
    bus.on("mode:construction", ({ actif, outil }) => {
      this.actif = actif;
      this.outil = outil;
      this.dessinerGrille();
      this.fantome.clear();
    });
    bus.on("construction:survol", (s) => {
      if (!s) return void this.fantome.clear();
      const c = this.caseEcran(s.clientX, s.clientY);
      if (c) this.dessinerFantome(c.x, c.y, s.largeur ?? 1, s.hauteur ?? 1);
    });
  }

  /** Tile under a screen point (drop from the React inventory). */
  caseEcran(clientX: number, clientY: number): { x: number; y: number } | null {
    const canvas = this.scene.game.canvas.getBoundingClientRect();
    const p = this.scene.cameras.main.getWorldPoint(clientX - canvas.left, clientY - canvas.top);
    return this.caseMonde(p.x, p.y);
  }

  caseMonde(wx: number, wy: number) {
    const T = tilePx();
    return { x: Math.floor(wx / T), y: Math.floor(wy / T) };
  }

  dessinerGrille() {
    this.grille.clear();
    const m = this.monde();
    if (!this.actif || !m) return;
    const T = tilePx();
    this.grille.lineStyle(1, 0xf3e5c8, 0.25);
    for (let x = 0; x <= m.largeur; x++) this.grille.lineBetween(x * T, 0, x * T, m.hauteur * T);
    for (let y = 0; y <= m.hauteur; y++) this.grille.lineBetween(0, y * T, m.largeur * T, y * T);
  }

  private dessinerFantome(x: number, y: number, largeur = 1, hauteur = 1, ignorer?: Objet) {
    const m = this.monde();
    if (!m) return;
    const T = tilePx();
    const ok = largeur > 1 || hauteur > 1 ? zoneLibre(m, x, y, largeur, hauteur) : caseLibre(m, x, y, ignorer?.entite.ref).ok;
    this.fantome.clear().fillStyle(ok ? OK : INTERDIT, 0.35).fillRect(x * T, y * T, largeur * T, hauteur * T);
    this.fantome.lineStyle(2, ok ? OK : INTERDIT, 0.9).strokeRect(x * T, y * T, largeur * T, hauteur * T);
  }

  // --- pointer gestures (called by the scene) ---------------------------------------

  /** True when the gesture is taken by the builder (no camera pan). */
  down(p: Phaser.Input.Pointer, objet: Objet | null): boolean {
    if (!this.actif) return false;
    const c = this.caseMonde(p.worldX, p.worldY);
    if (this.outil === "deplacer" && objet) {
      this.glisse = { objet, ...c };
      return true;
    }
    if (this.outil === "zone" && !objet) {
      this.rect = { x0: c.x, y0: c.y, x1: c.x, y1: c.y };
      return true;
    }
    return false;
  }

  move(p: Phaser.Input.Pointer) {
    const c = this.caseMonde(p.worldX, p.worldY);
    if (this.glisse) {
      const T = tilePx();
      this.glisse.objet.conteneur.setPosition(p.worldX - T / 2, p.worldY + T / 2).setAlpha(0.7);
      this.dessinerFantome(c.x, c.y, 1, 1, this.glisse.objet);
    } else if (this.rect) {
      this.rect.x1 = c.x;
      this.rect.y1 = c.y;
      const r = normaliser(this.rect);
      this.dessinerFantome(r.x, r.y, r.largeur, r.hauteur);
    } else if (this.actif && this.outil !== "gomme") this.dessinerFantome(c.x, c.y);
  }

  up(p: Phaser.Input.Pointer) {
    const c = this.caseMonde(p.worldX, p.worldY);
    if (this.glisse) {
      const { objet } = this.glisse;
      objet.conteneur.setAlpha(1);
      objet.maj(objet.entite); // back in place until the data says otherwise
      if (c.x !== objet.entite.x || c.y !== objet.entite.y) this.bus.emit("objet:deplace", { ref: objet.entite.ref, ...c });
      this.glisse = null;
    } else if (this.rect) {
      const r = normaliser(this.rect);
      this.rect = null;
      const m = this.monde();
      if (r.largeur >= 4 && r.hauteur >= 4 && m && zoneLibre(m, r.x, r.y, r.largeur, r.hauteur)) this.bus.emit("construction:zone", r);
    }
    this.fantome.clear();
  }
}

function normaliser(r: { x0: number; y0: number; x1: number; y1: number }) {
  const x = Math.min(r.x0, r.x1);
  const y = Math.min(r.y0, r.y1);
  return { x, y, largeur: Math.abs(r.x1 - r.x0) + 1, hauteur: Math.abs(r.y1 - r.y0) + 1 };
}

/** A new zone (with its walls) must not overlap an existing one. */
export function zoneLibre(m: Monde, x: number, y: number, largeur: number, hauteur: number): boolean {
  if (x < 0 || y < 0) return false;
  return !m.zones.some((z) => x < z.x + z.largeur + 1 && x + largeur + 1 > z.x && y < z.y + z.hauteur + 1 && y + hauteur + 1 > z.y);
}
