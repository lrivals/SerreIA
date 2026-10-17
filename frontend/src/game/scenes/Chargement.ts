// Loading scene: the atlas built by tools/construire_atlas.py, then the animations of the
// catalogue (gardener, actuators). Starts the greenhouse scene.
import Phaser from "phaser";
import { CATALOGUE } from "../catalogue";

export const ATLAS = "atlas";

/** Key of an animation from its frames (created on first use). */
export function cleAnim(scene: Phaser.Scene, frames: string[], fps: number): string {
  const key = `${frames[0]}×${frames.length}@${fps}`;
  if (!scene.anims.exists(key))
    scene.anims.create({
      key,
      frames: frames.map((frame) => ({ key: ATLAS, frame })),
      frameRate: fps,
      repeat: -1,
    });
  return key;
}

export class Chargement extends Phaser.Scene {
  constructor() {
    super("Chargement");
  }

  preload() {
    const base = import.meta.env.BASE_URL ?? "/";
    this.load.atlas(ATLAS, `${base}sprites/atlas.png`, `${base}sprites/atlas.json`);
    const barre = this.add.rectangle(this.scale.width / 2, this.scale.height / 2, 0, 6, 0x5d8c45).setOrigin(0.5);
    this.load.on("progress", (p: number) => (barre.width = (this.scale.width / 2) * p));
  }

  create() {
    for (const perso of Object.values(CATALOGUE.personnages))
      for (const a of Object.values(perso.animations)) cleAnim(this, a.frames, a.fps);
    for (const act of Object.values(CATALOGUE.actionneurs))
      for (const frames of Object.values(act.etats)) cleAnim(this, frames, 8);
    this.scene.start("Serre");
  }
}
