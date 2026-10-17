// Data → sprite / animation / effect (docs/13 §3). Pure functions over the catalogue:
// everything the catalogue lacks falls back to a generic sprite, so a new sprite sheet
// lights up without touching this file.
import type { Actionneur, Capteur, Contenant, EtatActionneur, Plante } from "@/api/types";
import { CATALOGUE, type Catalogue } from "./catalogue";

export const STADES = ["semis", "croissance", "floraison", "fructification", "recolte"] as const;

/** Species aliases of the model (French, free text) → key of the catalogue species. */
const normaliser = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .trim();

export interface SpritePlante {
  frame: string | null; // null: nothing to draw (plant removed)
  generique: boolean;
  /** Overlays drawn by the game until dedicated sprites exist (docs/13 §2, santé). */
  overlay: "cloche" | "spores" | null;
}

export function spritePlante(p: Pick<Plante, "espece" | "stade" | "etat_sante">, c: Catalogue = CATALOGUE): SpritePlante {
  if (p.etat_sante === "retiree") return { frame: null, generique: false, overlay: null };
  const esp = normaliser(p.espece);
  const cle =
    c.plantes.especes[esp] ??
    Object.entries(c.plantes.especes).find(([alias]) => esp.startsWith(alias) || alias.startsWith(esp))?.[1];
  const sprites = cle ? c.plantes.sprites[cle] : undefined;
  // `isolee`: the sick sprite under a bell jar.
  const sante = p.etat_sante === "isolee" ? "malade" : p.etat_sante;
  const overlay = p.etat_sante === "isolee" ? "cloche" : p.etat_sante === "malade" ? "spores" : null;
  if (sprites) {
    const stade = sprites.stades[p.stade] ?? sprites.stades[plusProche(p.stade, Object.keys(sprites.stades))];
    const frame = stade?.[sante] ?? stade?.sain;
    if (frame) return { frame, generique: false, overlay };
  }
  return { frame: c.plantes.generique, generique: true, overlay };
}

/** Closest known stage (by order of the model), for stages without sprites. */
function plusProche(stade: string, connus: string[]): string {
  const i = STADES.indexOf(stade as (typeof STADES)[number]);
  if (i < 0 || connus.length === 0) return connus[0];
  return connus.reduce((best, s) =>
    Math.abs(STADES.indexOf(s as (typeof STADES)[number]) - i) < Math.abs(STADES.indexOf(best as (typeof STADES)[number]) - i)
      ? s
      : best,
  );
}

/** Container sprite from its `type` (docs/09 §3), then the growing mode. */
export function spriteContenant(
  contenant: Pick<Contenant, "type" | "materiau"> | null,
  modeCulture: string,
  c: Catalogue = CATALOGUE,
): string | null {
  const type = normaliser(contenant?.type ?? "").replace(/\s+/g, "_");
  const candidats = c.contenants.filter((x) => x.type && normaliser(x.type) === type);
  const materiau = normaliser(contenant?.materiau ?? "").replace(/\s+/g, "_");
  const choisi = candidats.find((x) => x.materiau && materiau.includes(normaliser(x.materiau))) ?? candidats.find((x) => !x.materiau) ?? candidats[0];
  if (choisi) return choisi.frame;
  const parMode: Record<string, string> = {
    hydro_nft: "canal_nft",
    hydro_dwc: "bac_dwc",
    aeroponie: "bac_dwc",
    ebb_flow: "jardiniere",
    terre: "pleine_terre",
  };
  const repli = c.contenants.find((x) => x.type && normaliser(x.type) === (parMode[modeCulture] ?? "pot"));
  return (repli ?? c.contenants.find((x) => x.type === "pot") ?? c.contenants[0])?.frame ?? null;
}

/** Floor tile of a zone from its dominant growing mode. */
export function solZone(modes: string[], c: Catalogue = CATALOGUE): string | null {
  const compte = new Map<string, number>();
  for (const m of modes) compte.set(m, (compte.get(m) ?? 0) + 1);
  const dominant = [...compte.entries()].sort((a, b) => b[1] - a[1])[0]?.[0] ?? "terre";
  const cle = dominant.startsWith("hydro") || dominant === "aeroponie" || dominant === "ebb_flow" ? "gravel" : dominant === "substrat" ? "stone_floor" : "soil";
  return c.tuiles[cle]?.frame ?? Object.values(c.tuiles)[0]?.frame ?? null;
}

export interface AnimObjet {
  frames: string[];
  /** Animation speed relative to its fps: pwm → proportional to `valeur` (docs/13 §2). */
  vitesse: number;
  actif: boolean;
  effet: string | null;
}

export function animActionneur(
  a: Pick<Actionneur, "type"> & { etat: Pick<EtatActionneur, "action" | "valeur"> | null },
  c: Catalogue = CATALOGUE,
): AnimObjet | null {
  // nutrient / dosing pumps without sprites use the closest pump
  const cat = c.actionneurs[a.type] ?? (a.type.startsWith("pompe_nutri_") ? c.actionneurs.pompe_ph_down : undefined);
  if (!cat) return null;
  const action = a.etat?.action ?? "off";
  const actif = action === "on" || (action === "pwm" && (a.etat?.valeur ?? 0) > 0);
  if (!actif) return { frames: (cat.etats.off ?? Object.values(cat.etats)[0]).slice(0, 1), vitesse: 0, actif, effet: null };
  const vitesse = action === "pwm" ? Math.max(0.2, Math.min(1, (a.etat?.valeur ?? 100) / 100)) : 1;
  return { frames: cat.etats.on ?? Object.values(cat.etats)[0], vitesse, actif, effet: cat.effets.on ?? null };
}

const FAMILLE: Record<string, string> = {
  temperature: "air",
  humidite: "air",
  co2: "air",
  pression: "air",
  presence: "air",
  humidite_sol: "sol",
  lux: "lumiere",
  ph: "eau",
  ec: "eau",
  temp_eau: "eau",
  niveau_cuve: "eau",
};

export const familleCapteur = (type: string) => FAMILLE[type] ?? "air";

export function spriteCapteur(
  famille: string,
  enLigne: boolean,
  c: Catalogue = CATALOGUE,
): { frame: string | null; grise: boolean } {
  const parFamille = c.capteurs.filter((x) => x.famille === famille && x.frame);
  const statut = enLigne ? "online" : "offline";
  const exact = parFamille.find((x) => x.statut === statut) ?? parFamille.find((x) => !x.statut);
  if (exact) return { frame: exact.frame, grise: !enLigne && exact.statut !== "offline" };
  const air = c.capteurs.find((x) => x.famille === "air" && x.statut === statut) ?? c.capteurs.find((x) => x.frame);
  return { frame: air?.frame ?? null, grise: !enLigne && air?.statut !== "offline" };
}

export function spriteCamera(flash = false, c: Catalogue = CATALOGUE): string | null {
  const cam = c.capteurs.find((x) => x.famille === "camera");
  return cam?.etats?.[flash ? "flash" : "normal"]?.[0] ?? cam?.frame ?? null;
}

/** Tank sprite from `niveau_cuve` (%), None: full. */
export function spriteCuve(niveau: number | null | undefined, c: Catalogue = CATALOGUE): string | null {
  const cuve = c.capteurs.find((x) => x.famille === "cuve");
  if (!cuve?.etats) return cuve?.frame ?? null;
  const etat = niveau == null || niveau > 66 ? "full" : niveau > 25 ? "half" : "low";
  return cuve.etats[etat]?.[0] ?? Object.values(cuve.etats)[0][0];
}

export type Bulle = "alert" | "question" | "thinking" | "heart";

export const frameBulle = (b: Bulle, c: Catalogue = CATALOGUE) => c.ui[b]?.frame ?? null;

/** Synthetic health score out of 5 (decorative, docs/13 §6). */
export function coeurs(etatSante: string, scoreAnomalie?: number | null, ecarts = 0): number {
  const base: Record<string, number> = { sain: 5, a_surveiller: 3, malade: 1, isolee: 1, retiree: 0 };
  let n = base[etatSante] ?? 4;
  if (scoreAnomalie != null && scoreAnomalie > 0.5) n -= 1;
  n -= Math.min(2, ecarts);
  return Math.max(0, Math.min(5, n));
}

/** Gardener animation of an action, with its fallback while the sprite sheet lacks it. */
export function animJardinier(action: string, direction: "down" | "up" | "left" | "right", c: Catalogue = CATALOGUE) {
  const anims = c.personnages.gardener?.animations ?? {};
  const voulu: Record<string, string[]> = {
    marcher: [`walk_${direction}`],
    attendre: ["idle"],
    arroser: [`watering_${direction}`, "watering"],
    // no inspect_left / inspect_up drawn: mirror of the right, or seen from the front
    inspecter: [`inspect_${direction}`, direction === "up" ? "inspect_down" : "inspect_right", "inspect", "idle"],
    ventiler: ["switch", "idle_back", "idle"],
    doser: ["dose", "idle"],
    noter: ["notebook", "idle"],
    dormir: ["sleep", "idle"],
    tapoter: ["tap", "idle_back", "idle"],
  };
  for (const nom of voulu[action] ?? ["idle"]) if (anims[nom]) return { nom, ...anims[nom] };
  const premier = Object.keys(anims)[0];
  return premier ? { nom: premier, ...anims[premier] } : null;
}

/** Portrait of the gardener (dialog with the agent): a dedicated frame if a sheet has one. */
export function portraitJardinier(c: Catalogue = CATALOGUE): string | null {
  const anims = c.personnages.gardener?.animations ?? {};
  return (anims.portrait ?? anims.idle ?? Object.values(anims)[0])?.frames[0] ?? null;
}

export const capteurEnLigne = (c: Pick<Capteur, "noeud">, noeuds: Record<string, string | null | undefined>) =>
  noeuds[c.noeud] !== "offline";
