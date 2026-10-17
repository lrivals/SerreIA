// The gardener (docs/13 §5): an avatar of the real events, not a simulation. He walks
// (A* on the tile grid) to the object of the current task and plays its animation; idle,
// he makes a round between emplacements; at night he sleeps on the bench.
import EasyStar from "easystarjs";
import Phaser from "phaser";
import { CATALOGUE, tilePx } from "../catalogue";
import { animJardinier, frameBulle } from "../mapping";
import { caseDevant, cleCase, cleRef, type Monde } from "../monde";
import type { ActionJardinier, Tache } from "../tasks/fileTaches";
import { ATLAS, cleAnim } from "../scenes/Chargement";

type Direction = "down" | "up" | "left" | "right";
const VITESSE_MS = 220; // per tile
const DUREE_ACTION_MS = 2600;
const PAUSE_RONDE_MS = 2500;

const ANIM_ACTION: Record<ActionJardinier, string> = {
  courir: "attendre",
  ventiler: "ventiler",
  doser: "doser",
  arroser: "arroser",
  inspecter: "inspecter",
  noter: "noter",
  tapoter: "tapoter",
  attendre: "attendre",
};

export class Jardinier {
  readonly sprite: Phaser.GameObjects.Sprite;
  private bulle: Phaser.GameObjects.Image;
  private etiquette: Phaser.GameObjects.Text;
  private astar = new EasyStar.js();
  private monde: Monde | null = null;
  private chemin: { x: number; y: number }[] = [];
  private occupe = false;
  private tache: Tache | null = null;
  private direction: Direction = "down";
  private attenteJusqua = 0;
  x = 1;
  y = 1;
  reduireAnimations = false;
  nuit = false;

  constructor(
    private scene: Phaser.Scene,
    private prochaineTache: () => Tache | null,
    private surTache: (t: Tache | null) => void,
  ) {
    const premier = animJardinier("attendre", "down");
    this.sprite = scene.add.sprite(0, 0, ATLAS, premier?.frames[0]).setOrigin(0.5, 1).setInteractive({ useHandCursor: true });
    this.bulle = scene.add.image(0, 0, ATLAS, frameBulle("thinking") ?? undefined).setOrigin(0.5, 1).setVisible(false);
    this.etiquette = scene.add
      .text(0, 0, "", { fontFamily: '"Press Start 2P"', fontSize: "8px", color: "#F3E5C8", backgroundColor: "#49352Bcc", padding: { x: 2, y: 2 } })
      .setOrigin(0.5, 1)
      .setResolution(4)
      .setVisible(false);
    this.astar.setAcceptableTiles([0]);
    this.astar.disableCornerCutting();
    this.jouer("attendre");
  }

  setMonde(m: Monde) {
    const premierMonde = !this.monde;
    this.monde = m;
    const grille = Array.from({ length: m.hauteur }, (_, y) => Array.from({ length: m.largeur }, (_, x) => (m.bloques.has(cleCase(x, y)) ? 1 : 0)));
    this.astar.setGrid(grille);
    if (premierMonde) {
      this.x = m.banc.x;
      this.y = m.banc.y;
      this.placer();
    }
  }

  get tacheEnCours() {
    return this.tache;
  }

  /** Go and play a task right away (the envelope to the Pi, a click of the user). */
  imposer(t: Tache) {
    this.chemin = [];
    this.occupe = false;
    this.commencer(t);
  }

  update(now: number) {
    this.astar.calculate();
    if (this.occupe || this.chemin.length > 0 || now < this.attenteJusqua) return;
    const t = this.prochaineTache();
    if (t) this.commencer(t);
    else if (this.nuit) this.allerA(this.monde?.banc ?? { x: 1, y: 1 }, () => this.jouer("dormir"));
    else this.ronde(now);
  }

  private commencer(t: Tache) {
    this.tache = t;
    this.surTache(t);
    const cible = this.caseCible(t);
    this.occupe = true;
    const fin = () => {
      this.jouer(ANIM_ACTION[t.action]);
      this.montrerBulle(t);
      this.scene.time.delayedCall(DUREE_ACTION_MS, () => {
        this.cacherBulle();
        this.tache = null;
        this.surTache(null);
        this.occupe = false;
        this.attenteJusqua = this.scene.time.now + 400;
      });
    };
    if (cible) this.allerA(cible, fin, t.action === "courir" ? 0.5 : 1);
    else fin();
  }

  private caseCible(t: Tache): { x: number; y: number } | null {
    const m = this.monde;
    if (!m) return null;
    if (t.cible) {
      const e = m.entites.find((x) => cleRef(x.ref) === cleRef(t.cible!));
      if (e) return caseDevant(m, e.x, e.y);
    }
    const z = m.zones.find((x) => x.id === t.zone);
    return z ? { x: z.porte.x, y: z.porte.y - 1 } : null;
  }

  private ronde(now: number) {
    const m = this.monde;
    if (!m) return;
    const plantes = m.entites.filter((e) => e.ref.genre === "emplacement" && e.couches.length > 1);
    const choix = plantes.length ? plantes[Math.floor(Math.random() * plantes.length)] : null;
    if (!choix) {
      this.attenteJusqua = now + PAUSE_RONDE_MS;
      return;
    }
    this.occupe = true;
    this.allerA(caseDevant(m, choix.x, choix.y), () => {
      this.direction = "up";
      this.jouer("attendre");
      this.occupe = false;
      this.attenteJusqua = this.scene.time.now + PAUSE_RONDE_MS;
    });
  }

  private allerA(cible: { x: number; y: number }, fin: () => void, rythme = 1) {
    if (this.reduireAnimations) {
      this.x = cible.x;
      this.y = cible.y;
      this.placer();
      fin();
      return;
    }
    if (cible.x === this.x && cible.y === this.y) return fin();
    this.chemin = [{ x: -1, y: -1 }]; // pending: blocks a new task while A* searches
    this.astar.findPath(this.x, this.y, cible.x, cible.y, (chemin) => {
      if (!chemin || chemin.length < 2) {
        // unreachable (walled in): teleport, the event still gets illustrated
        this.chemin = [];
        this.x = cible.x;
        this.y = cible.y;
        this.placer();
        fin();
        return;
      }
      this.chemin = chemin.slice(1);
      this.pas(fin, rythme);
    });
  }

  private pas(fin: () => void, rythme: number) {
    const suivant = this.chemin.shift();
    if (!suivant) return fin();
    const dx = suivant.x - this.x;
    const dy = suivant.y - this.y;
    this.direction = dx > 0 ? "right" : dx < 0 ? "left" : dy < 0 ? "up" : "down";
    this.jouer("marcher");
    this.x = suivant.x;
    this.y = suivant.y;
    const T = tilePx();
    this.scene.tweens.add({
      targets: this.sprite,
      x: this.x * T + T / 2,
      y: (this.y + 1) * T - 2,
      duration: VITESSE_MS * rythme,
      onUpdate: () => this.suivre(),
      onComplete: () => (this.chemin.length ? this.pas(fin, rythme) : fin()),
    });
  }

  private jouer(action: string) {
    const a = animJardinier(action, this.direction);
    if (!a) return;
    // sprite sheets draw the right side only: left = mirror (docs/13 §2)
    const mirroir = a.flip_x || (this.direction === "left" && !a.nom.endsWith("_left") && !a.nom.startsWith("walk"));
    this.sprite.setFlipX(mirroir);
    this.sprite.play(cleAnim(this.scene, a.frames, a.fps), true);
    if (action === "dormir") this.sprite.anims.timeScale = 0.3;
    else this.sprite.anims.timeScale = 1;
  }

  private montrerBulle(t: Tache) {
    const frame = t.bulle ? frameBulle(t.bulle) : null;
    if (frame) {
      this.bulle.setFrame(frame).setVisible(true).setScale(1);
      if (!this.reduireAnimations) this.scene.tweens.add({ targets: this.bulle, scale: { from: 0.4, to: 1 }, ease: "Back.Out", duration: 300 });
    }
    const texte = [t.compteur > 1 ? `×${t.compteur}` : "", t.texte].filter(Boolean).join(" ");
    this.etiquette.setText(texte.length > 38 ? `${texte.slice(0, 36)}…` : texte).setVisible(!!texte);
    this.suivre();
  }

  private cacherBulle() {
    this.bulle.setVisible(false);
    this.etiquette.setVisible(false);
  }

  private placer() {
    const T = tilePx();
    this.sprite.setPosition(this.x * T + T / 2, (this.y + 1) * T - 2);
    this.suivre();
  }

  private suivre() {
    const h = CATALOGUE.personnages.gardener?.taille[1] ?? 48;
    this.sprite.setDepth(this.sprite.y * 10 + 5);
    this.bulle.setPosition(this.sprite.x, this.sprite.y - h - 2).setDepth(100_000);
    this.etiquette.setPosition(this.sprite.x, this.bulle.y - (this.bulle.visible ? this.bulle.height : 0) - 2).setDepth(100_001);
  }
}
