// An object of the world (emplacement with its container and plant, actuator, sensor,
// camera, tank): sprites stacked on its tile, animation, overlay and bubble. Updated in
// place from each new `Entite` so that animations do not restart on every rebuild.
import Phaser from "phaser";
import { CATALOGUE, tilePx } from "../catalogue";
import { frameBulle } from "../mapping";
import type { Entite } from "../monde";
import { ATLAS, cleAnim } from "../scenes/Chargement";

const VERRE = 0xbfe3f2;

export class Objet {
  readonly conteneur: Phaser.GameObjects.Container;
  private couches: Phaser.GameObjects.Sprite[] = [];
  private cible: Phaser.GameObjects.Zone;
  private bulle: Phaser.GameObjects.Image | null = null;
  private cloche: Phaser.GameObjects.Graphics | Phaser.GameObjects.Image | null = null;
  private spores: Phaser.Time.TimerEvent | null = null;
  private signature = "";
  entite: Entite;

  constructor(
    private scene: Phaser.Scene,
    entite: Entite,
    private reduireAnimations: () => boolean,
  ) {
    this.entite = entite;
    this.conteneur = scene.add.container(0, 0);
    const T = tilePx();
    // click / hover target: the tile and the one above (plants are two tiles tall)
    this.cible = scene.add.zone(T / 2, -T, T, T * 2).setInteractive({ useHandCursor: true });
    this.cible.setData("objet", this);
    this.conteneur.add(this.cible);
    this.maj(entite);
  }

  maj(e: Entite) {
    this.entite = e;
    const T = tilePx();
    this.conteneur.setPosition(e.x * T, (e.y + 1) * T);
    this.conteneur.setDepth((e.y + 1) * T * 10);
    const signature = JSON.stringify([e.couches, e.anim?.frames, e.anim?.vitesse, e.grise]);
    if (signature !== this.signature) {
      this.signature = signature;
      this.dessinerCouches(e);
    }
    this.majOverlay(e);
    this.majBulle(e);
  }

  private dessinerCouches(e: Entite) {
    this.couches.forEach((s) => s.destroy());
    this.couches = [];
    const T = tilePx();
    for (const c of e.couches) {
      const s = this.scene.add.sprite(T / 2, c.dy ?? 0, ATLAS, c.frame).setOrigin(0.5, 1);
      if (c.recadrer && s.width > T) {
        // containers wider than a tile (planter, NFT channel): the middle tile; bigger
        // square ones (DWC tub, soil patch): halved
        if (s.height > T) s.setScale(T / s.width);
        else s.setCrop((s.width - T) / 2, 0, T, s.height);
      }
      if (e.grise) s.setTint(0x8a8a8a);
      this.couches.push(s);
      this.conteneur.add(s);
    }
    const anim = e.anim;
    const cible = this.couches[0];
    if (anim && cible && anim.frames.length > 1 && !this.reduireAnimations()) {
      cible.play(cleAnim(this.scene, anim.frames, 8));
      cible.anims.timeScale = anim.vitesse || 1;
    }
    // plants sway a little (stronger when the fan runs: set by the scene)
    if (e.ref.genre === "emplacement" && this.couches.length > 1 && !this.reduireAnimations()) {
      const plante = this.couches[this.couches.length - 1];
      this.scene.tweens.add({
        targets: plante,
        angle: { from: -1.5, to: 1.5 },
        duration: 1800 + Math.random() * 800,
        yoyo: true,
        repeat: -1,
        ease: "Sine.InOut",
      });
    }
    if (this.bulle) this.conteneur.bringToTop(this.bulle);
  }

  /** Stronger sway when the zone fan runs (docs/13 §2). */
  vent(fort: boolean) {
    const plante = this.entite.ref.genre === "emplacement" && this.couches.length > 1 ? this.couches[this.couches.length - 1] : null;
    if (!plante) return;
    for (const t of this.scene.tweens.getTweensOf(plante)) t.timeScale = fort ? 2.5 : 1;
  }

  private hauteur(): number {
    return Math.max(tilePx(), ...this.couches.map((s) => s.displayHeight - (s.y ?? 0)));
  }

  private majOverlay(e: Entite) {
    const T = tilePx();
    const clocheSprite = CATALOGUE.ui.bell_jar?.frame;
    if (e.overlay === "cloche" && !this.cloche && clocheSprite) {
      // dedicated sprite of a later sheet (sprites-src/PROMPTS.md, planche 07)
      const s = this.scene.add.image(T / 2, 0, ATLAS, clocheSprite).setOrigin(0.5, 1).setAlpha(0.85);
      this.cloche = s;
      this.conteneur.add(s);
    } else if (e.overlay === "cloche" && !this.cloche) {
      const h = this.hauteur();
      const g = this.scene.add.graphics();
      g.fillStyle(VERRE, 0.28).fillRoundedRect(T * 0.12, -h, T * 0.76, h - 2, { tl: T * 0.38, tr: T * 0.38, bl: 2, br: 2 });
      g.lineStyle(1, 0xffffff, 0.8).strokeRoundedRect(T * 0.12, -h, T * 0.76, h - 2, { tl: T * 0.38, tr: T * 0.38, bl: 2, br: 2 });
      g.fillStyle(0xffffff, 0.6).fillRect(T * 0.25, -h + 6, 2, h / 3);
      this.cloche = g;
      this.conteneur.add(g);
    } else if (e.overlay !== "cloche" && this.cloche) {
      this.cloche.destroy();
      this.cloche = null;
    }
    const spores = e.overlay === "spores" && !this.reduireAnimations();
    if (spores && !this.spores) {
      this.spores = this.scene.time.addEvent({ delay: 700, loop: true, callback: () => this.emettreSpore() });
    } else if (!spores && this.spores) {
      this.spores.remove();
      this.spores = null;
    }
  }

  private emettreSpore() {
    const T = tilePx();
    const frame = ["ui/spore_particles/green/0", "ui/spore_particles/purple/0", "ui/spore_particles/brown/0"].find((f) =>
      this.scene.textures.get(ATLAS).has(f),
    );
    if (!frame) return;
    const s = this.scene.add
      .image(T * (0.2 + Math.random() * 0.6), -this.hauteur() * (0.4 + Math.random() * 0.4), ATLAS, frame)
      .setScale(0.35)
      .setAlpha(0.9);
    this.conteneur.add(s);
    this.scene.tweens.add({ targets: s, y: s.y - T * 0.6, alpha: 0, duration: 1600, onComplete: () => s.destroy() });
  }

  private majBulle(e: Entite) {
    const frame = e.bulle ? frameBulle(e.bulle) : null;
    if (!frame) {
      this.bulle?.destroy();
      this.bulle = null;
      return;
    }
    const T = tilePx();
    if (!this.bulle) {
      this.bulle = this.scene.add.image(T / 2, 0, ATLAS, frame).setOrigin(0.5, 1);
      this.conteneur.add(this.bulle);
      if (!this.reduireAnimations())
        this.scene.tweens.add({ targets: this.bulle, scale: { from: 0.3, to: 1 }, ease: "Back.Out", duration: 350 });
    } else this.bulle.setFrame(frame);
    this.bulle.y = -this.hauteur() - 2;
  }

  /** Photo taken (camera): short flash. */
  flash() {
    const T = tilePx();
    const f = this.scene.add.circle(T / 2, -T * 1.4, T / 2, 0xffffff, 0.9);
    this.conteneur.add(f);
    this.scene.tweens.add({ targets: f, alpha: 0, scale: 2, duration: 300, onComplete: () => f.destroy() });
  }

  detruire() {
    this.spores?.remove();
    this.couches.forEach((s) => this.scene.tweens.killTweensOf(s));
    this.conteneur.destroy();
  }
}
