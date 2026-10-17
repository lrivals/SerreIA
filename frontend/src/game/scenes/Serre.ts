// Greenhouse scene (docs/13 §3, §5): floor and walls of the zones, objects reconciled from
// each new world, gardener, ambience (night, fog, LED halo, warm / cold tint), camera with
// integer zoom and pan, hover highlights, clicks sent to React.
import Phaser from "phaser";
import type { Bus } from "../bus";
import { CATALOGUE, tilePx } from "../catalogue";
import { Jardinier } from "../entities/Jardinier";
import { Objet } from "../entities/Objet";
import { cleCase, cleRef, type Monde } from "../monde";
import type { FileTaches } from "../tasks/fileTaches";
import { ATLAS } from "./Chargement";
import { ModeConstruction } from "./Construction";

const MUR = 0xa66e43;
const MUR_HAUT = 0xc4895a;
const CONTOUR = 0x49352b;
const NUIT = 0x141c38;
const ZOOM_MAX = 8; // screen pixels per game pixel

/** Depth of an object, or of its container (click targets live in containers). */
const depth = (g: Phaser.GameObjects.GameObject) =>
  (g as Phaser.GameObjects.Components.Depth & Phaser.GameObjects.GameObject).parentContainer?.depth ??
  (g as unknown as Phaser.GameObjects.Components.Depth).depth ??
  0;

export class Serre extends Phaser.Scene {
  private bus!: Bus;
  private file!: FileTaches;
  private monde: Monde | null = null;
  private geometrie = "";
  private sol: Phaser.GameObjects.RenderTexture | null = null;
  private murs!: Phaser.GameObjects.Graphics;
  private decor: Phaser.GameObjects.GameObject[] = [];
  private ambiance!: Phaser.GameObjects.Graphics;
  private halo!: Phaser.GameObjects.Graphics;
  private nuit!: Phaser.GameObjects.Rectangle;
  private surbrillance!: Phaser.GameObjects.Graphics;
  private infobulle!: Phaser.GameObjects.Text;
  private objets = new Map<string, Objet>();
  private jardinier!: Jardinier;
  private construction!: ModeConstruction;
  private reduire = false;
  private heure = 12;
  private zoomAjuste = false;
  private pan: { x: number; y: number; sx: number; sy: number; bouge: boolean; pris: boolean } | null = null;

  constructor() {
    super("Serre");
  }

  create() {
    this.bus = this.registry.get("bus");
    this.file = this.registry.get("file");
    this.reduire = !!this.registry.get("reduire");
    this.cameras.main.setBackgroundColor("#2f3b2a");
    this.cameras.main.setRoundPixels(true);
    this.murs = this.add.graphics().setDepth(1);
    this.ambiance = this.add.graphics().setDepth(80_000);
    this.nuit = this.add.rectangle(0, 0, 10, 10, NUIT, 0).setOrigin(0).setDepth(85_000);
    this.halo = this.add.graphics().setDepth(86_000).setBlendMode(Phaser.BlendModes.ADD);
    this.surbrillance = this.add.graphics().setDepth(89_000);
    this.infobulle = this.add
      .text(0, 0, "", { fontFamily: '"Press Start 2P"', fontSize: "8px", color: "#F3E5C8", backgroundColor: "#49352Bdd", padding: { x: 3, y: 3 } })
      .setResolution(4)
      .setDepth(100_002)
      .setVisible(false);
    this.jardinier = new Jardinier(
      this,
      () => this.file.suivante(Date.now()),
      (t) => this.bus.emit("jardinier:tache", t),
    );
    this.jardinier.reduireAnimations = this.reduire;
    this.construction = new ModeConstruction(this, this.bus, () => this.monde);

    this.bus.on("donnees:maj", this.appliquer);
    this.bus.on("horloge:heure", this.surHeure);
    this.bus.on("live:evenement", this.surLive);
    this.bus.on("reduire:animations", this.surReduire);
    this.bus.on("camera:zoom", this.surZoom);
    this.bus.on("jardinier:enveloppe", this.surEnveloppe);
    this.events.once(Phaser.Scenes.Events.SHUTDOWN, () => {
      this.bus.off("donnees:maj", this.appliquer);
      this.bus.off("horloge:heure", this.surHeure);
      this.bus.off("live:evenement", this.surLive);
      this.bus.off("reduire:animations", this.surReduire);
      this.bus.off("camera:zoom", this.surZoom);
      this.bus.off("jardinier:enveloppe", this.surEnveloppe);
    });
    this.entrees();
    this.scale.on(Phaser.Scale.Events.RESIZE, () => this.ajusterZoom(true));
    const initial = this.registry.get("monde") as Monde | undefined;
    if (initial) this.appliquer(initial);
    this.bus.emit("scene:prete");
  }

  update(time: number) {
    this.jardinier.nuit = this.estNuit();
    this.jardinier.update(time);
  }

  // --- data ----------------------------------------------------------------------------

  private appliquer = (m: Monde) => {
    this.monde = m;
    const geo = JSON.stringify([m.largeur, m.hauteur, m.zones.map((z) => [z.x, z.y, z.largeur, z.hauteur, z.sol, z.nom])]);
    if (geo !== this.geometrie) {
      this.geometrie = geo;
      this.dessinerDecor(m);
      this.ajusterZoom(!this.zoomAjuste);
    }
    const vus = new Set<string>();
    for (const e of m.entites) {
      const k = cleRef(e.ref);
      vus.add(k);
      const o = this.objets.get(k);
      if (o) o.maj(e);
      else this.objets.set(k, new Objet(this, e, () => this.reduire));
    }
    for (const [k, o] of this.objets)
      if (!vus.has(k)) {
        o.detruire();
        this.objets.delete(k);
      }
    // stronger sway in the zones whose fan runs
    const vent = new Set(m.entites.filter((e) => e.ref.genre === "actionneur" && e.anim?.actif && e.anim.frames[0]?.startsWith("devices/fan")).map((e) => e.zone));
    for (const o of this.objets.values()) o.vent(vent.has(o.entite.zone));
    this.jardinier.setMonde(m);
    this.dessinerAmbiance();
    this.construction.dessinerGrille();
  };

  private dessinerDecor(m: Monde) {
    const T = tilePx();
    this.decor.forEach((d) => d.destroy());
    this.decor = [];
    this.sol?.destroy();
    this.sol = this.add.renderTexture(0, 0, m.largeur * T, m.hauteur * T).setOrigin(0).setDepth(0);
    const dehors = CATALOGUE.tuiles.stone_floor?.frame ?? CATALOGUE.tuiles.wooden_path?.frame;
    for (let y = 0; y < m.hauteur; y++)
      for (let x = 0; x < m.largeur; x++) {
        const z = m.zones.find((z) => x >= z.x && x < z.x + z.largeur && y >= z.y && y < z.y + z.hauteur);
        const frame = z?.sol ?? dehors;
        if (frame) this.sol.drawFrame(ATLAS, frame, x * T, y * T);
      }
    // low walls; front glass panes behind the top wall; door in the bottom wall
    this.murs.clear();
    const vitre = CATALOGUE.tuiles.greenhouse_glass_front?.frame;
    const porte = CATALOGUE.tuiles.greenhouse_door?.frame;
    for (const z of m.zones) {
      const x0 = z.x * T;
      const y0 = z.y * T;
      const w = z.largeur * T;
      const h = z.hauteur * T;
      const ep = Math.round(T * 0.4);
      if (vitre)
        for (let x = z.x + 1; x + 2 <= z.x + z.largeur - 1; x += 2)
          this.decor.push(this.add.image(x * T, y0 + T, ATLAS, vitre).setOrigin(0, 1).setDepth(2).setAlpha(0.85));
      const rects: [number, number, number, number][] = [
        [x0, y0 + T - ep, w, ep], // top
        [x0, y0 + h - T, (z.porte.x - z.x) * T, ep], // bottom, left of the door
        [(z.porte.x + 1) * T, y0 + h - T, x0 + w - (z.porte.x + 1) * T, ep], // bottom, right
        [x0 + (T - ep) / 2, y0 + T - ep, ep, h - T], // left
        [x0 + w - (T + ep) / 2, y0 + T - ep, ep, h - T], // right
      ];
      const brique = CATALOGUE.tuiles.brick_border_straight?.frame;
      const briqueV = CATALOGUE.tuiles.brick_border_vertical?.frame ?? brique;
      if (brique && briqueV) {
        // tileable wall sprites (sprites-src/PROMPTS.md, planche 08): one per border tile
        for (let x = z.x; x < z.x + z.largeur; x++) {
          this.decor.push(this.add.image(x * T, y0, ATLAS, brique).setOrigin(0).setDepth(2));
          if (x !== z.porte.x) this.decor.push(this.add.image(x * T, y0 + h - T, ATLAS, brique).setOrigin(0).setDepth((z.y + z.hauteur) * T * 10));
        }
        for (let y = z.y + 1; y < z.y + z.hauteur - 1; y++) {
          this.decor.push(this.add.image(x0, y * T, ATLAS, briqueV).setOrigin(0).setDepth(2));
          this.decor.push(this.add.image(x0 + w - T, y * T, ATLAS, briqueV).setOrigin(0).setDepth(2));
        }
        rects.length = 0;
      }
      for (const [rx, ry, rw, rh] of rects) {
        if (rw <= 0) continue;
        this.murs.fillStyle(MUR, 1).fillRect(rx, ry, rw, rh);
        this.murs.fillStyle(MUR_HAUT, 1).fillRect(rx, ry, rw, Math.max(2, rh / 4));
        this.murs.lineStyle(2, CONTOUR, 1).strokeRect(rx, ry, rw, rh);
      }
      if (porte)
        this.decor.push(
          this.add
            .image((z.porte.x + 0.5) * T, (z.porte.y + 1) * T - ep / 2, ATLAS, porte)
            .setOrigin(0.5, 1)
            .setDepth((z.porte.y + 1) * T * 10 - 1)
            .setAlpha(0.9),
        );
      const libelle = this.add
        .text(x0 + 4, y0 + h + 4, `${z.id}${z.nom ? ` · ${z.nom}` : ""}`, {
          fontFamily: '"Press Start 2P"',
          fontSize: "8px",
          color: "#49352B",
          backgroundColor: "#F3E5C8",
          padding: { x: 3, y: 3 },
        })
        .setResolution(4)
        .setDepth(3);
      this.decor.push(libelle);
    }
    this.nuit.setSize(m.largeur * T, m.hauteur * T);
    this.cameras.main.setBounds(-T * 4, -T * 4, (m.largeur + 8) * T, (m.hauteur + 8) * T);
  }

  private dessinerAmbiance() {
    const m = this.monde;
    if (!m) return;
    const T = tilePx();
    this.ambiance.clear();
    this.halo.clear();
    for (const z of m.zones) {
      const [x, y, w, h] = [(z.x + 1) * T, (z.y + 1) * T, (z.largeur - 2) * T, (z.hauteur - 2) * T];
      if (z.teinte) this.ambiance.fillStyle(z.teinte === "chaud" ? 0xff9a3c : 0x5fa8ff, 0.12).fillRect(x, y, w, h);
      if (z.buee) {
        // fog on the glass: a veil, thicker along the front panes
        this.ambiance.fillStyle(0xeef5f7, 0.16).fillRect(x, y, w, h);
        this.ambiance.fillStyle(0xffffff, 0.35).fillRect(z.x * T, (z.y - 1) * T, z.largeur * T, T * 2);
      }
      if (z.halo) this.halo.fillStyle(0xd45be8, 0.07).fillRect(x, y, w, h);
    }
    const n = this.estNuit() ? 0.5 : this.heure >= 19 || this.heure < 7 ? 0.22 : 0;
    this.nuit.setFillStyle(NUIT, n);
  }

  private estNuit() {
    return this.heure >= 21 || this.heure < 6;
  }

  private surHeure = (h: { heure: number } | null) => {
    if (h) this.heure = h.heure;
    this.dessinerAmbiance();
  };

  private surLive = ({ evenement }: { evenement: { kind: string; subject: string | null } }) => {
    if (evenement.kind === "vision" && evenement.subject) this.objets.get(`camera:${evenement.subject}`)?.flash();
  };

  private surReduire = (r: boolean) => {
    this.reduire = r;
    this.jardinier.reduireAnimations = r;
  };

  private surEnveloppe = () => {
    const z = this.monde?.zones[0];
    this.jardinier.imposer({
      cle: "enveloppe",
      priorite: 1,
      action: "courir",
      zone: z?.id ?? null,
      cible: null,
      bulle: "heart",
      texte: "configuration publiée ✉",
      cree: Date.now(),
      compteur: 1,
      persistante: false,
    });
  };

  // --- camera and pointer -------------------------------------------------------------

  private ajusterZoom(recentrer: boolean) {
    const m = this.monde;
    if (!m) return;
    const T = tilePx();
    const cam = this.cameras.main;
    if (recentrer || !this.zoomAjuste) {
      // largest whole number of screen pixels per game pixel that shows the whole greenhouse
      const g = CATALOGUE.tuile;
      const k = Math.floor(Math.min(this.scale.width / (m.largeur * g), this.scale.height / (m.hauteur * g)));
      cam.setZoom(Phaser.Math.Clamp(k, 1, ZOOM_MAX) / CATALOGUE.facteur);
      cam.centerOn((m.largeur * T) / 2, (m.hauteur * T) / 2);
      this.zoomAjuste = true;
    }
  }

  /** Zoom in steps of one screen pixel per game pixel: never a fractional pixel (the atlas
   * is drawn at `facteur` × the game pixels, docs/13 §2). */
  private surZoom = (d: number) => {
    const cam = this.cameras.main;
    const k = Math.round(cam.zoom * CATALOGUE.facteur) + Math.sign(d);
    cam.setZoom(Phaser.Math.Clamp(k, 1, ZOOM_MAX) / CATALOGUE.facteur);
  };

  private objetSous(over: Phaser.GameObjects.GameObject[]): Objet | null {
    for (const g of over) {
      const o = g.getData?.("objet") as Objet | undefined;
      if (o) return o;
    }
    return null;
  }

  private entrees() {
    this.input.on("pointerdown", (p: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]) => {
      const pris = this.construction.down(p, this.objetSous(over));
      this.pan = { x: p.x, y: p.y, sx: this.cameras.main.scrollX, sy: this.cameras.main.scrollY, bouge: false, pris };
    });
    this.input.on("pointermove", (p: Phaser.Input.Pointer) => {
      this.construction.move(p);
      if (!this.pan || !p.isDown) return;
      if (Math.abs(p.x - this.pan.x) + Math.abs(p.y - this.pan.y) > 4) this.pan.bouge = true;
      if (this.pan.bouge && !this.pan.pris) {
        const z = this.cameras.main.zoom;
        this.cameras.main.setScroll(this.pan.sx - (p.x - this.pan.x) / z, this.pan.sy - (p.y - this.pan.y) / z);
      }
    });
    this.input.on("pointerup", (p: Phaser.Input.Pointer, over: Phaser.GameObjects.GameObject[]) => {
      const pan = this.pan;
      this.pan = null;
      this.construction.up(p);
      if (!pan || pan.bouge || pan.pris) return;
      // the topmost one: the gardener in front of a plant, or the plant in front of him
      const dessus = [...over].sort((a, b) => depth(b) - depth(a))[0];
      if (dessus === this.jardinier.sprite) return void this.bus.emit("jardinier:clic");
      const o = this.objetSous(dessus ? [dessus] : []);
      if (o) this.bus.emit("objet:clic", o.entite.ref);
    });
    this.input.on("wheel", (_p: unknown, _o: unknown, _dx: number, dy: number) => this.surZoom(-dy));
    this.input.on("gameobjectover", (_p: Phaser.Input.Pointer, g: Phaser.GameObjects.GameObject) => {
      const o = g.getData?.("objet") as Objet | undefined;
      if (o) this.survol(o);
    });
    this.input.on("gameobjectout", () => {
      this.surbrillance.clear();
      this.infobulle.setVisible(false);
    });
  }

  /** Hover: the emplacements covered by a sensor or seen by a camera (docs/13 §3). */
  private survol(o: Objet) {
    const T = tilePx();
    const e = o.entite;
    this.surbrillance.clear();
    const couverts = new Set(e.couvre ?? []);
    if (couverts.size && this.monde) {
      this.surbrillance.lineStyle(2, 0xe8c957, 1).fillStyle(0xe8c957, 0.18);
      for (const x of this.monde.entites)
        if (x.ref.genre === "emplacement" && couverts.has(x.ref.id)) {
          this.surbrillance.fillRect(x.x * T, x.y * T, T, T).strokeRect(x.x * T, x.y * T, T, T);
        }
    }
    this.surbrillance.lineStyle(2, 0xf3e5c8, 0.9).strokeRect(e.x * T, e.y * T, T, T);
    if (e.info) this.infobulle.setText(e.info).setPosition(e.x * T, (e.y + 1) * T + 4).setVisible(true);
  }

  /** Builder: tile under a screen point (React inventory drop). */
  caseEcran(clientX: number, clientY: number) {
    return this.construction.caseEcran(clientX, clientY);
  }

  /** Screen point (client coordinates) of the centre of a tile: end-to-end tests. */
  ecranDeCase(x: number, y: number) {
    const T = tilePx();
    const cam = this.cameras.main;
    const r = this.game.canvas.getBoundingClientRect();
    return { x: r.left + ((x + 0.5) * T - cam.worldView.x) * cam.zoom, y: r.top + ((y + 0.5) * T - cam.worldView.y) * cam.zoom };
  }

  libre(x: number, y: number) {
    return !!this.monde && !this.monde.bloques.has(cleCase(x, y));
  }
}
