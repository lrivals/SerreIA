// API data → world of the game view (docs/13 §3). Pure: the scene is rebuilt from it on
// every update, no business state lives only in Phaser. Coordinates in tiles.
import type {
  Actionneur,
  Alerte,
  Camera,
  Capteur,
  Cuve,
  DecisionSummary,
  Disposition,
  Noeud,
  Serre,
  Tableau,
  Zone,
  ZonePlan,
} from "@/api/types";
import { CATALOGUE, type Catalogue } from "./catalogue";
import {
  animActionneur,
  capteurEnLigne,
  familleCapteur,
  solZone,
  spriteCamera,
  spriteCapteur,
  spriteContenant,
  spriteCuve,
  spritePlante,
  type AnimObjet,
  type Bulle,
} from "./mapping";

export interface Donnees {
  serre: Serre | null;
  zones: Zone[];
  plans: ZonePlan[];
  actionneurs: Actionneur[];
  capteurs: Capteur[];
  cameras: Camera[];
  cuves: Cuve[];
  noeuds: Noeud[];
  tableaux: Record<string, Tableau | undefined>;
  alertes: Alerte[];
  propositions: DecisionSummary[];
  /** Consistency warnings (builder): shown as "!" on the objects they name. */
  avertissements?: string[];
}

export type Genre = "emplacement" | "actionneur" | "capteur" | "camera" | "cuve";

export interface Ref {
  genre: Genre;
  id: string;
}

export const cleRef = (r: Ref) => `${r.genre}:${r.id}`;

export interface Entite {
  ref: Ref;
  zone: string;
  x: number;
  y: number;
  /** Frames drawn bottom-anchored on the tile, bottom to top (container, then plant). */
  couches: { frame: string; dy?: number; teinte?: number; recadrer?: boolean }[];
  anim?: AnimObjet | null;
  overlay?: "cloche" | "spores" | null;
  bulle?: Bulle | null;
  info?: string; // tooltip
  grise?: boolean;
  /** Tiles covered (sensors and cameras: highlighted on hover). */
  couvre?: string[];
}

export interface ZoneMonde {
  id: string;
  nom: string;
  x: number;
  y: number;
  largeur: number;
  hauteur: number;
  sol: string | null;
  porte: { x: number; y: number };
  jour: boolean;
  /** Ambience (docs/13 §3): fog when RH > setpoint, LED halo, warm/cold tint. */
  buee: boolean;
  halo: boolean;
  teinte: "chaud" | "froid" | null;
}

export interface Monde {
  largeur: number;
  hauteur: number;
  zones: ZoneMonde[];
  entites: Entite[];
  /** Tiles where the gardener cannot walk ("x,y"). */
  bloques: Set<string>;
  /** Where the gardener rests at night. */
  banc: { x: number; y: number };
}

export const cleCase = (x: number, y: number) => `${x},${y}`;

const MARGE = 1; // outer path around the zones

/** Default size of a zone: actuator row, plant rows (a plant is two tiles tall) with a
 * walkway between them, sensor row; walls around. */
function tailleParDefaut(plan: ZonePlan | undefined, nAct: number, nCapt: number, cuve: boolean) {
  const grille = (plan?.emplacements ?? []).filter((e) => e.rangee && e.colonne);
  const hors = (plan?.emplacements ?? []).length - grille.length;
  const cols = Math.max(0, ...grille.map((e) => e.colonne!));
  const rows = Math.max(0, ...grille.map((e) => e.rangee!)) + (hors > 0 ? Math.ceil(hors / Math.max(cols, 4)) : 0);
  const interieur = Math.max(2 * cols + 1, hors > 0 ? 9 : 0, 2 * nAct + 1, 2 * nCapt + (cuve ? 3 : 1), 7);
  return { largeur: interieur + 2, hauteur: 3 + 3 * Math.max(rows, 1) + 2 + 1 };
}

export function construireMonde(d: Donnees, c: Catalogue = CATALOGUE): Monde {
  const zones: ZoneMonde[] = [];
  const entites: Entite[] = [];
  const bloques = new Set<string>();
  const noeuds = Object.fromEntries(d.noeuds.map((n) => [n.id, n.status]));
  const avert = d.avertissements ?? [];
  const alerteSur = (id: string) => avert.some((w) => new RegExp(`\\b${id.replace(/[-]/g, "\\-")}\\b`).test(w));

  // zones: their disposition, else side by side after the placed ones
  let curseur = MARGE;
  for (const z of d.zones) {
    const disp = z.disposition;
    if (disp?.largeur && disp.hauteur) curseur = Math.max(curseur, disp.x + disp.largeur + 1);
  }
  const zonesTriees = [...d.zones].sort((a, b) => a.id.localeCompare(b.id, "fr", { numeric: true }));
  for (const z of zonesTriees) {
    const plan = d.plans.find((p) => p.zone.id === z.id);
    const acts = d.actionneurs.filter((a) => a.zone_id === z.id);
    const capts = groupeCapteurs(d.capteurs.filter((x) => x.zone === z.id));
    const cuve = z.cuve_id ? d.cuves.find((x) => x.id === z.cuve_id) : undefined;
    const defaut = tailleParDefaut(plan, acts.length, capts.length, !!z.cuve_id);
    const disp = z.disposition;
    const placee = !!(disp?.largeur && disp.hauteur);
    const zx = placee ? disp!.x : curseur;
    const zy = placee ? disp!.y : MARGE;
    const largeur = placee ? disp!.largeur! : defaut.largeur;
    const hauteur = placee ? disp!.hauteur! : defaut.hauteur;
    if (!placee) curseur += largeur + 1;
    const tableau = d.tableaux[z.id];
    const zm: ZoneMonde = {
      id: z.id,
      nom: z.nom,
      x: zx,
      y: zy,
      largeur,
      hauteur,
      sol: solZone((plan?.emplacements ?? []).map((e) => e.mode_culture), c),
      porte: { x: zx + Math.floor(largeur / 2), y: zy + hauteur - 1 },
      jour: tableau?.jour ?? true,
      ...ambiance(tableau, acts),
    };
    zones.push(zm);
    // walls, door open
    for (let x = zx; x < zx + largeur; x++) {
      bloques.add(cleCase(x, zy));
      if (x !== zm.porte.x) bloques.add(cleCase(x, zy + hauteur - 1));
    }
    for (let y = zy; y < zy + hauteur; y++) {
      bloques.add(cleCase(zx, y));
      bloques.add(cleCase(zx + largeur - 1, y));
    }
    const occupe = new Set<string>();
    const poser = (disp: Disposition | null | undefined, defaut: { x: number; y: number }) => {
      let p = disp ? { x: disp.x, y: disp.y } : { x: zx + defaut.x, y: zy + defaut.y };
      if (!disp) p = libreProche(p, occupe, zm);
      occupe.add(cleCase(p.x, p.y));
      bloques.add(cleCase(p.x, p.y));
      return p;
    };

    // emplacements: grid, then off-grid ones on the following rows
    const emps = plan?.emplacements ?? [];
    const grille = emps.filter((e) => e.rangee && e.colonne);
    const rows = Math.max(0, ...grille.map((e) => e.rangee!));
    const parLigne = Math.max(1, Math.floor((largeur - 2) / 2));
    let hors = 0;
    for (const e of emps) {
      let def: { x: number; y: number };
      if (e.rangee && e.colonne) def = { x: 2 * e.colonne - 1, y: 3 + 3 * (e.rangee - 1) };
      else {
        def = { x: 1 + 2 * (hors % parLigne), y: 3 + 3 * (rows + Math.floor(hors / parLigne)) };
        hors++;
      }
      const p = poser(e.disposition, def);
      const couches: Entite["couches"] = [];
      const cont = e.disposition?.sprite ?? spriteContenant(e.contenant, e.mode_culture, c);
      if (cont) couches.push({ frame: cont, recadrer: true });
      let overlay: Entite["overlay"] = null;
      let bulle: Bulle | null = null;
      if (e.plante) {
        const sp = spritePlante(e.plante, c);
        if (sp.frame) couches.push({ frame: sp.frame, dy: cont ? -c.facteur * 4 : 0 });
        overlay = sp.overlay;
        if (e.plante.stade === "recolte" && e.plante.etat_sante === "sain") bulle = "heart";
      }
      if (e.plante && (e.plante.etat_sante === "a_surveiller" || e.plante.etat_sante === "malade")) bulle = "question";
      if (e.vision && e.vision.sante === "anormal" && !bulle) bulle = "question";
      if (d.propositions.some((pr) => pr.emplacements.includes(e.id))) bulle = "thinking";
      if (alerteSur(e.id)) bulle = "alert";
      entites.push({
        ref: { genre: "emplacement", id: e.id },
        zone: z.id,
        ...p,
        couches,
        overlay,
        bulle,
        info: e.plante ? `${e.code} · ${e.plante.espece} (${e.plante.stade})` : `${e.code} · vide`,
      });
    }

    // actuators along the top wall
    acts.forEach((a, i) => {
      const anim = animActionneur(a, c);
      const p = poser(a.disposition, { x: 1 + 2 * i, y: 1 });
      const propose = d.propositions.some((pr) => pr.zone === z.id && pr.actions.some((x) => x.includes(a.type)));
      entites.push({
        ref: { genre: "actionneur", id: a.id },
        zone: z.id,
        ...p,
        couches: anim ? [{ frame: anim.frames[0] }] : [],
        anim,
        bulle: propose ? "thinking" : alerteSur(a.id) ? "alert" : null,
        info: `${a.type} · ${anim?.actif ? "en marche" : "arrêté"}`,
      });
    });

    // sensors (one box per device) along the bottom wall, tank on the right
    capts.forEach((g, i) => {
      const enLigne = g.canaux.every((x) => capteurEnLigne(x, noeuds));
      const sp = spriteCapteur(g.famille, enLigne, c);
      const p = poser(g.disposition, { x: 1 + 2 * i, y: hauteur - 2 });
      const retard = g.canaux.some((x) => x.etalonnage_en_retard);
      entites.push({
        ref: { genre: "capteur", id: g.id },
        zone: z.id,
        ...p,
        couches: sp.frame ? [{ frame: sp.frame }] : [],
        grise: sp.grise,
        bulle: !enLigne || g.canaux.some((x) => alerteSur(x.id)) ? "alert" : retard ? "question" : null,
        info: `${g.id} · ${g.canaux.map((x) => x.type).join(", ")}${enLigne ? "" : " · hors ligne"}`,
        couvre: [...new Set(g.canaux.flatMap((x) => x.emplacements_couverts))],
      });
    });
    if (cuve) {
      const niveau = tableau?.mesures.find((m) => m.type === "niveau_cuve")?.valeur;
      const sp = spriteCuve(niveau, c);
      const p = poser(cuve.disposition, { x: largeur - 2, y: hauteur - 2 });
      entites.push({
        ref: { genre: "cuve", id: cuve.id },
        zone: z.id,
        ...p,
        couches: sp ? [{ frame: sp }] : [],
        info: `cuve ${cuve.id}${niveau != null ? ` · ${Math.round(niveau)} %` : ""}`,
      });
    }

    // cameras in the top corners
    d.cameras
      .filter((cam) => cam.zone_id === z.id)
      .forEach((cam, i) => {
        const p = poser(cam.disposition, { x: i % 2 === 0 ? largeur - 2 : 1, y: 1 + Math.floor(i / 2) });
        const fr = spriteCamera(false, c);
        entites.push({
          ref: { genre: "camera", id: cam.id },
          zone: z.id,
          ...p,
          couches: fr ? [{ frame: fr }] : [],
          info: `caméra ${cam.id}`,
          couvre: cam.regions.map((r) => r.emplacement_id),
        });
      });
  }

  for (const a of d.alertes.filter((x) => !x.acquittee && x.niveau === "critique")) {
    const zone = zones.find((z) => z.id === a.zone);
    if (!zone) continue;
    const cible = entites.find((e) => e.zone === zone.id && e.ref.genre === "actionneur") ?? entites.find((e) => e.zone === zone.id);
    if (cible) cible.bulle = "alert";
  }

  const largeur = Math.max(curseur, ...zones.map((z) => z.x + z.largeur + 1), 12) + MARGE - 1;
  const hauteur = Math.max(...zones.map((z) => z.y + z.hauteur + 1), 8) + 2;
  return { largeur, hauteur, zones, entites, bloques, banc: { x: MARGE, y: hauteur - 2 } };
}

interface GroupeCapteurs {
  id: string; // device (materiel) or channel id
  famille: string;
  canaux: Capteur[];
  disposition: Disposition | null | undefined;
}

/** Channels of one device (`materiel`, e.g. sht41-z1) drawn as one box; soil probes one
 * per emplacement. */
export function groupeCapteurs(capteurs: Capteur[]): GroupeCapteurs[] {
  const groupes = new Map<string, GroupeCapteurs>();
  for (const x of capteurs) {
    const id = x.materiel ?? x.id;
    const g = groupes.get(id) ?? { id, famille: familleCapteur(x.type), canaux: [], disposition: null };
    g.canaux.push(x);
    g.disposition ??= x.disposition;
    groupes.set(id, g);
  }
  return [...groupes.values()];
}

function libreProche(p: { x: number; y: number }, occupe: Set<string>, z: ZoneMonde) {
  if (!occupe.has(cleCase(p.x, p.y))) return p;
  for (let r = 1; r < 20; r++)
    for (let dy = -r; dy <= r; dy++)
      for (let dx = -r; dx <= r; dx++) {
        const q = { x: p.x + dx, y: p.y + dy };
        if (q.x > z.x && q.x < z.x + z.largeur - 1 && q.y > z.y && q.y < z.y + z.hauteur - 1 && !occupe.has(cleCase(q.x, q.y)))
          return q;
      }
  return p;
}

function ambiance(t: Tableau | undefined, acts: Actionneur[]): Pick<ZoneMonde, "buee" | "halo" | "teinte"> {
  const tuile = (type: string) => t?.mesures.find((m) => m.type === type && !m.emplacement);
  const hr = tuile("humidite");
  const temp = tuile("temperature");
  const led = acts.find((a) => a.type === "led");
  let teinte: ZoneMonde["teinte"] = null;
  if (temp?.plage && temp.statut !== "ok" && temp.statut !== "inconnu")
    teinte = temp.valeur > temp.plage[1] ? "chaud" : temp.valeur < temp.plage[0] ? "froid" : null;
  return {
    buee: !!(hr?.plage && hr.valeur > hr.plage[1]),
    halo: !!led && (led.etat?.action === "on" || (led.etat?.action === "pwm" && (led.etat.valeur ?? 0) > 0)),
    teinte,
  };
}

/** A free tile next to an object, for the gardener to stand on (below first). */
export function caseDevant(m: Monde, x: number, y: number): { x: number; y: number } {
  for (const [dx, dy] of [
    [0, 1],
    [1, 0],
    [-1, 0],
    [0, -1],
    [1, 1],
    [-1, 1],
    [0, 2],
  ])
    if (!m.bloques.has(cleCase(x + dx, y + dy)) && x + dx >= 0 && y + dy >= 0 && x + dx < m.largeur && y + dy < m.hauteur)
      return { x: x + dx, y: y + dy };
  return { x, y: y + 1 };
}

/** Can an object be dropped here (builder)? Inside a zone, off the walls, free. */
export function caseLibre(m: Monde, x: number, y: number, ignorer?: Ref): { ok: boolean; zone: ZoneMonde | null; raison?: string } {
  const zone = m.zones.find((z) => x > z.x && x < z.x + z.largeur - 1 && y > z.y && y < z.y + z.hauteur - 1) ?? null;
  if (!zone) return { ok: false, zone, raison: "hors zone" };
  const occupant = m.entites.find((e) => e.x === x && e.y === y && !(ignorer && cleRef(e.ref) === cleRef(ignorer)));
  if (occupant) return { ok: false, zone, raison: `case occupée (${occupant.ref.id})` };
  return { ok: true, zone };
}

export const entiteA = (m: Monde, x: number, y: number) => m.entites.find((e) => e.x === x && e.y === y) ?? null;
