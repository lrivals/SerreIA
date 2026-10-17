// Mounts one Phaser instance in a div and bridges it with React (docs/13 §7): the bus, the
// gardener's task queue and the first world go through the game registry.
import Phaser from "phaser";
import { forwardRef, useEffect, useImperativeHandle, useRef } from "react";
import type { Bus } from "./bus";
import type { Monde } from "./monde";
import { Chargement } from "./scenes/Chargement";
import { Serre } from "./scenes/Serre";
import type { FileTaches } from "./tasks/fileTaches";

export interface PhaserApi {
  /** Tile under a screen point (drop of the inventory), null before the scene is ready. */
  caseEcran: (clientX: number, clientY: number) => { x: number; y: number } | null;
  ecranDeCase: (x: number, y: number) => { x: number; y: number } | null;
}

export const PhaserVue = forwardRef<PhaserApi, { bus: Bus; file: FileTaches; monde: Monde | null; reduire: boolean; className?: string }>(
  function PhaserVue({ bus, file, monde, reduire, className }, ref) {
    const div = useRef<HTMLDivElement>(null);
    const jeu = useRef<Phaser.Game | null>(null);
    const premier = useRef({ monde, reduire });
    premier.current = { monde, reduire };

    useImperativeHandle(ref, () => ({
      caseEcran: (x, y) => {
        const s = jeu.current?.scene.getScene("Serre") as Serre | null;
        return s?.sys.isActive() ? s.caseEcran(x, y) : null;
      },
      ecranDeCase: (x, y) => {
        const s = jeu.current?.scene.getScene("Serre") as Serre | null;
        return s?.sys.isActive() ? s.ecranDeCase(x, y) : null;
      },
    }));

    useEffect(() => {
      if (!div.current) return;
      let detruit = false;
      let game: Phaser.Game | null = null;
      // the pixel font must be there before Phaser draws its texts
      const police = document.fonts?.load('8px "Press Start 2P"').catch(() => undefined) ?? Promise.resolve();
      police.then(() => {
        if (detruit || !div.current) return;
        game = new Phaser.Game({
          type: Phaser.AUTO,
          parent: div.current,
          pixelArt: true,
          roundPixels: true,
          backgroundColor: "#2f3b2a",
          scale: { mode: Phaser.Scale.RESIZE, width: div.current.clientWidth || 800, height: div.current.clientHeight || 500 },
          scene: [Chargement, Serre],
          banner: false,
          callbacks: {
            preBoot: (g) => {
              g.registry.set("bus", bus);
              g.registry.set("file", file);
              g.registry.set("monde", premier.current.monde);
              g.registry.set("reduire", premier.current.reduire);
            },
          },
        });
        jeu.current = game;
      });
      return () => {
        detruit = true;
        game?.destroy(true);
        jeu.current = null;
      };
    }, [bus, file]);

    useEffect(() => {
      jeu.current?.registry.set("monde", monde);
    }, [monde]);

    return <div ref={div} className={className} data-testid="jeu-canvas" />;
  },
);
