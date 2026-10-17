// React ↔ Phaser bus (docs/13 §7). Phaser emits gestures (`objet:*`, `construction:*`,
// `jardinier:clic`); React pushes data (`donnees:maj`) and live events (`live:evenement`).
// Phaser never calls the network.
import mitt from "mitt";
import type { LiveEvent } from "@/live/LiveProvider";
import type { Monde, Ref } from "./monde";
import type { Tache } from "./tasks/fileTaches";

export type Outil = "poser" | "deplacer" | "gomme" | "zone";

export type Evenements = {
  // React → Phaser
  "donnees:maj": Monde;
  "live:evenement": { evenement: LiveEvent; ts: number };
  "mode:construction": { actif: boolean; outil: Outil };
  "construction:survol": { clientX: number; clientY: number; largeur?: number; hauteur?: number } | null;
  "horloge:heure": { heure: number } | null; // replay: hour of the simulated clock (null: live)
  "jardinier:enveloppe": void;
  "reduire:animations": boolean;
  "camera:zoom": number; // +1 / -1
  // Phaser → React
  "objet:clic": Ref;
  "objet:deplace": { ref: Ref; x: number; y: number };
  "construction:zone": { x: number; y: number; largeur: number; hauteur: number };
  "jardinier:clic": void;
  "jardinier:tache": Tache | null;
  "scene:prete": void;
};

export type Bus = ReturnType<typeof mitt<Evenements>>;
export const creerBus = (): Bus => mitt<Evenements>();
