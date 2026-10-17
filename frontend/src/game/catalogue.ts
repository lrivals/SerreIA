// What the game can draw: `catalogue.gen.json`, generated from sprites-src/sprites.json by
// tools/construire_atlas.py (`make sprites`). A new sprite sheet only changes this file,
// never the code: missing sprites fall back to generic ones (docs/13 §2).
import brut from "./catalogue.gen.json";

export interface Anim {
  frames: string[];
  flip_x: boolean;
  fps: number;
}

export interface Catalogue {
  version: string | null;
  tuile: number;
  facteur: number;
  personnages: Record<string, { taille: [number, number]; animations: Record<string, Anim> }>;
  plantes: {
    generique: string | null;
    especes: Record<string, string>;
    sprites: Record<string, { taille: [number, number]; stades: Record<string, Record<string, string>> }>;
  };
  contenants: { cle: string; type: string | null; materiau: string | null; frame: string; taille: [number, number] }[];
  tuiles: Record<string, { frame: string; taille: [number, number] }>;
  actionneurs: Record<
    string,
    { cle: string; taille: [number, number]; etats: Record<string, string[]>; effets: Record<string, string> }
  >;
  capteurs: {
    cle: string;
    famille: string | null;
    statut: string | null;
    frame: string | null;
    etats: Record<string, string[]> | null;
    taille: [number, number];
  }[];
  ui: Record<string, { taille: [number, number]; frame?: string; etats?: Record<string, string[]>; fichier?: string }>;
}

export const CATALOGUE = brut as unknown as Catalogue;

/** Size of a tile in atlas pixels (game pixels × facteur). */
export const tilePx = (c: Catalogue = CATALOGUE) => c.tuile * c.facteur;
