// Rules of the printed-parts configurator (docs/21 §2): part selection, material, derived
// dimensions and checks, measurements and test pieces, safety alerts, exports (§3).
// Pure functions: the page only renders their result.
import {
  COTE,
  COTES,
  FAMILLES,
  PIECES,
  PRIORITES,
  REGLAGES,
  type Echelle,
  type Famille,
  type Materiau,
  type Pertinence,
  type Piece,
  type Priorite,
} from "./catalogue";

export const VOLUME_IMPRESSION = 256; // Elegoo Centauri Carbon 2 (docs/20 §2.1)
const EMMANCHEMENT = 32; // hardware/params.py Params.emmanchement
const PLATINE_EP = 4; // hardware/params.py Params.platine_ep
const JSN_ZONE_AVEUGLE = 250;

export interface Contraintes {
  echelle: Echelle;
  familles: Famille[];
  prioriteMax: Priorite;
  exterieur: boolean;
  driverProche: boolean; // parts within 5 cm of an LED driver
  filaments: Materiau[];
  canvas: boolean;
}

export type Cotes = Record<string, number | null | undefined>;

export const CONTRAINTES_DEFAUT: Contraintes = {
  echelle: "tunnel",
  familles: ["A", "B", "C", "D", "E"],
  prioriteMax: "P1",
  exterieur: false,
  driverProche: false,
  filaments: ["PETG", "ASA", "TPU"],
  canvas: false,
};

export interface ChoixMateriau {
  materiau: Materiau;
  manquant: boolean;
  opaque: boolean;
  joint: boolean;
}

export interface Derivee {
  cle: string;
  libelle: string;
  formule: string;
  valeur: number;
  unite: string;
  pieces: string[];
  nominale: boolean; // computed from at least one unmeasured dimension
}

export interface Controle {
  niveau: "erreur" | "avertissement";
  cle: string;
  message: string;
}

export interface Ligne {
  piece: Piece;
  pertinence: Pertinence;
  choix: ChoixMateriau;
}

export interface Mesure {
  cle: string;
  pieces: string[];
}

export interface Alerte {
  niveau: "erreur" | "avertissement" | "info";
  texte: string;
}

export interface Plan {
  contraintes: Contraintes;
  cotes: Cotes;
  lignes: Ligne[];
  derivees: Derivee[];
  controles: Controle[];
  mesures: Mesure[];
  eprouvettes: string[];
  alertes: Alerte[];
}

const mesuree = (cotes: Cotes, cle: string) => typeof cotes[cle] === "number" && Number.isFinite(cotes[cle]);

/** Measured value, or the nominal one of the catalogue. */
export function valeur(cotes: Cotes, cle: string): number {
  return mesuree(cotes, cle) ? (cotes[cle] as number) : COTE[cle].nominal;
}

export function selectionner(c: Contraintes): Ligne[] {
  const max = PRIORITES.indexOf(c.prioriteMax);
  return PIECES.filter(
    (p) => c.familles.includes(p.famille) && PRIORITES.indexOf(p.priorite) <= max && p.echelles[c.echelle] !== "non",
  ).map((piece) => ({ piece, pertinence: piece.echelles[c.echelle], choix: materiau(piece, c) }));
}

export function materiau(piece: Piece, c: Contraintes): ChoixMateriau {
  let candidats = piece.materiaux.filter((m) => m !== "PLA");
  if (c.driverProche && piece.famille === "C") {
    const chauds: Materiau[] = ["ASA", "ASA-CF", "ABS"];
    candidats = [...candidats.filter((m) => chauds.includes(m)), "ABS"];
  }
  const dispo = candidats.find((m) => c.filaments.includes(m));
  return {
    materiau: dispo ?? candidats[0],
    manquant: !dispo,
    opaque: !!piece.eau,
    joint: !!piece.joint,
  };
}

export function derivees(cotes: Cotes): Derivee[] {
  const d = (
    cle: string,
    libelle: string,
    formule: string,
    sources: string[],
    calcul: (v: (k: string) => number) => number,
    pieces: string[],
  ): Derivee => ({
    cle,
    libelle,
    formule,
    valeur: calcul((k) => valeur(cotes, k)),
    unite: "mm",
    pieces,
    nominale: sources.some((k) => !mesuree(cotes, k)),
  });
  return [
    d("raccord_d_int", "Ø intérieur des raccords", "tube_d + jeu", ["tube_d", "jeu"], (v) => v("tube_d") + v("jeu"), ["B1", "B3", "D4", "D8"]),
    d("emmanchement_min", "Emmanchement minimal", "1,5 × tube_d", ["tube_d"], (v) => 1.5 * v("tube_d"), ["B1"]),
    d("clip_bache_d_int", "Ø intérieur du clip de bâche", "tube_d + 2 × film_ep + jeu", ["tube_d", "film_ep", "jeu"], (v) => v("tube_d") + 2 * v("film_ep") + v("jeu"), ["B2"]),
    d("crochet_faitage_d_int", "Ø intérieur du crochet de faîtage", "tube_faitage_d + jeu", ["tube_faitage_d", "jeu"], (v) => v("tube_faitage_d") + v("jeu"), ["C2"]),
    d("jsn_garde", "Garde du JSN-SR04T au-dessus de l'eau", "cuve_hauteur − cuve_niveau_max + 4", ["cuve_hauteur", "cuve_niveau_max"], (v) => v("cuve_hauteur") - v("cuve_niveau_max") + PLATINE_EP, ["A4"]),
    d("presse_etoupe_ph_d", "Presse-étoupe pH", "sonde_ph_d + jeu", ["sonde_ph_d", "jeu"], (v) => v("sonde_ph_d") + v("jeu"), ["A4"]),
    d("presse_etoupe_ec_d", "Presse-étoupe EC", "sonde_ec_d + jeu", ["sonde_ec_d", "jeu"], (v) => v("sonde_ec_d") + v("jeu"), ["A4"]),
    d("presse_etoupe_ds18b20_d", "Presse-étoupe DS18B20", "ds18b20_d + jeu", ["ds18b20_d", "jeu"], (v) => v("ds18b20_d") + v("jeu"), ["A4"]),
    d("presse_etoupe_cable_d", "Presse-étoupe des câbles", "cable_d + jeu", ["cable_d", "jeu"], (v) => v("cable_d") + v("jeu"), ["D2"]),
    d("netpot_trou_d", "Ø des trous de net-pot", "netpot_d + jeu", ["netpot_d", "jeu"], (v) => v("netpot_d") + v("jeu"), ["A1", "A2", "A3"]),
    d("coulisseau_int", "Intérieur du coulisseau", "profile_cote + jeu", ["profile_cote", "jeu"], (v) => v("profile_cote") + v("jeu"), ["C1"]),
  ];
}

/** Checks of docs/21 §2.3; size checks only for measured values of the selected parts. */
export function controles(cotes: Cotes, ids: string[] = PIECES.map((p) => p.id)): Controle[] {
  const out: Controle[] = [];
  const err = (cle: string, message: string) => out.push({ niveau: "erreur", cle, message });
  const warn = (cle: string, message: string) => out.push({ niveau: "avertissement", cle, message });
  for (const c of COTES) {
    if (mesuree(cotes, c.cle) && ((cotes[c.cle] as number) < c.min || (cotes[c.cle] as number) > c.max))
      warn(c.cle, `${c.cle} = ${fmt(cotes[c.cle] as number)} ${c.unite} hors de la plage ${fmt(c.min)}–${fmt(c.max)} ${c.unite} (saisie ou unité ?)`);
  }
  const v = (k: string) => valeur(cotes, k);
  if (mesuree(cotes, "jeu") && (v("jeu") < 0.1 || v("jeu") > 0.5))
    err("jeu", `jeu ${fmt(v("jeu"))} mm hors 0,1–0,5 mm : réimprimer les anneaux de jeu`);
  for (const k of ["tube_d", "tube_faitage_d"])
    if (1.5 * v(k) > EMMANCHEMENT)
      err(k, `1,5 × ${k} = ${fmt(1.5 * v(k))} mm > emmanchement de params.py (${EMMANCHEMENT} mm) : l'augmenter`);
  if (v("cuve_niveau_max") >= v("cuve_hauteur"))
    err("cuve_niveau_max", "niveau d'eau maximal ≥ hauteur de la cuve");
  else {
    const garde = v("cuve_hauteur") - v("cuve_niveau_max") + PLATINE_EP;
    if (garde < JSN_ZONE_AVEUGLE)
      err("cuve_niveau_max", `JSN-SR04T à ${fmt(garde)} mm de l'eau < ${JSN_ZONE_AVEUGLE} mm (zone aveugle) : rehausse d'au moins ${fmt(JSN_ZONE_AVEUGLE - garde)} mm (jsn_rehausse)`);
  }
  if (mesuree(cotes, "pente_nft") && (v("pente_nft") < 1 || v("pente_nft") > 4))
    warn("pente_nft", `pente NFT ${fmt(v("pente_nft"))} % hors 1–4 %`);
  if (ids.includes("A3") && mesuree(cotes, "seau_d") && v("seau_d") > VOLUME_IMPRESSION)
    warn("seau_d", `couvercle A3 de Ø ${fmt(v("seau_d"))} mm > ${VOLUME_IMPRESSION} mm : à découper en secteurs`);
  if (ids.includes("C1") && mesuree(cotes, "hauteur_max") && v("hauteur_max") > VOLUME_IMPRESSION)
    warn("hauteur_max", `course ${fmt(v("hauteur_max"))} mm > ${VOLUME_IMPRESSION} mm : montants C1 à découper, ou tube / tige filetée achetés`);
  return out;
}

/** Dimensions still to measure, with the selected parts that need them. */
export function mesures(lignes: Ligne[], cotes: Cotes): Mesure[] {
  const besoin = new Map<string, string[]>();
  const ajouter = (cle: string, id: string) => besoin.set(cle, [...(besoin.get(cle) ?? []), id]);
  for (const { piece } of lignes) {
    for (const cle of piece.cotes) ajouter(cle, piece.id);
    if (piece.serre) ajouter("jeu", piece.id);
  }
  return COTES.filter((c) => besoin.has(c.cle) && !mesuree(cotes, c.cle)).map((c) => ({
    cle: c.cle,
    pieces: [...new Set(besoin.get(c.cle))],
  }));
}

export function eprouvettes(lignes: Ligne[], cotes: Cotes): string[] {
  const serrees = lignes.filter((l) => l.piece.serre);
  if (!serrees.length) return [];
  const out: string[] = [];
  if (!mesuree(cotes, "jeu"))
    out.push("Anneaux de jeu 0,1–0,5 mm (hardware/pieces/eprouvettes) pour mesurer `jeu`, avant tout le reste");
  const ds = derivees(cotes);
  for (const { piece } of serrees) {
    const utiles = ds.filter((d) => d.pieces.includes(piece.id) && d.cle !== "emmanchement_min" && d.cle !== "jsn_garde");
    out.push(
      utiles.length
        ? `${piece.id} — anneau de 5 mm : ${utiles.map((d) => `${d.libelle.toLowerCase()} Ø ${fmt(d.valeur)} mm`).join(", ")}`
        : `${piece.id} — tronçon de 5 mm de l'ajustement (filetage, baïonnette, clip) avant la pièce complète`,
    );
  }
  return out;
}

export function alertes(lignes: Ligne[], c: Contraintes): Alerte[] {
  const ids = lignes.map((l) => l.piece.id);
  const familles = new Set(lignes.map((l) => l.piece.famille));
  const out: Alerte[] = [];
  if (familles.has("C"))
    out.push({ niveau: "erreur", texte: "Lampe suspendue : câble de sécurité métallique indépendant de la pièce imprimée ; acheter la suspension à cliquet (C2)." });
  if (ids.includes("C3"))
    out.push({ niveau: "avertissement", texte: "Hauteur motorisée : fins de course haut et bas, durée max gérée par le firmware." });
  if (ids.includes("D2") || ids.includes("D7"))
    out.push({ niveau: "erreur", texte: "230 V : jamais un boîtier imprimé comme seule enveloppe ; boîtier électrique homologué à l'intérieur, presse-étoupes et évent bas." });
  if (lignes.some((l) => ["ASA", "ASA-CF", "ABS"].includes(l.choix.materiau)))
    out.push({ niveau: "avertissement", texte: "ASA / ABS : styrène, imprimer caisson fermé et ventiler la pièce." });
  if (familles.has("A"))
    out.push({ niveau: "avertissement", texte: "Contact avec la solution : PETG ou ASA opaque, parois épaisses, époxy alimentaire si besoin, rincer avant usage." });
  if (c.exterieur && familles.has("B"))
    out.push({ niveau: "avertissement", texte: "Extérieur : la tenue au vent vient des piquets, tubes et sangles ; surdimensionner les raccords d'angle et de faîtage." });
  if (c.driverProche)
    out.push({ niveau: "avertissement", texte: "Pas de PETG à moins de 5 cm d'un driver LED, d'un dissipateur ou du chauffage." });
  const manquants = lignes.filter((l) => l.choix.manquant);
  if (manquants.length)
    out.push({
      niveau: "avertissement",
      texte: `Filament manquant : ${manquants.map((l) => `${l.piece.id} (${l.choix.materiau})`).join(", ")}.`,
    });
  out.push({ niveau: "info", texte: "Modèles tiers : vérifier la licence (souvent CC BY-NC), les cotes et le matériau conseillé avant d'imprimer." });
  return out;
}

export function planifier(c: Contraintes, cotes: Cotes): Plan {
  const lignes = selectionner(c);
  return {
    contraintes: c,
    cotes,
    lignes,
    derivees: derivees(cotes),
    controles: controles(cotes, lignes.map((l) => l.piece.id)),
    mesures: mesures(lignes, cotes),
    eprouvettes: eprouvettes(lignes, cotes),
    alertes: alertes(lignes, c),
  };
}

/** Number as written in files: dot decimal, at most 2 decimals. */
export const fmt = (v: number) => String(Number(v.toFixed(2)));

export function libelleMateriau(ch: ChoixMateriau): string {
  return [ch.materiau, ch.opaque && "opaque", ch.joint && "+ joint TPU"].filter(Boolean).join(" ");
}

/** hardware/mesures.toml: params.py dimensions, the others as comments (load() rejects unknown keys). */
export function versToml(plan: Plan, date: string): string {
  const l = [
    "# Cotes mesurées sur le matériel acheté (docs/20 §5.2), en mm. Elles remplacent les valeurs",
    "# nominales de hardware/params.py ; une cote commentée garde sa valeur nominale.",
    `# Exporté par le configurateur /impression (docs/21) le ${date}.`,
    "",
  ];
  for (const c of COTES.filter((c) => c.params)) {
    l.push(
      mesuree(plan.cotes, c.cle)
        ? `${c.cle} = ${fmt(plan.cotes[c.cle] as number)}  # ${c.libelle}`
        : `# ${c.cle} = ${fmt(c.nominal)}  # À MESURER — ${c.libelle}`,
    );
  }
  l.push("", "# Cotes propres au configurateur (hors params.py, pour information) :");
  for (const c of COTES.filter((c) => !c.params))
    l.push(`# ${c.cle} = ${mesuree(plan.cotes, c.cle) ? fmt(plan.cotes[c.cle] as number) : "?"}  # ${c.unite} — ${c.libelle}`);
  l.push("", "# Cotes dérivées (docs/21 §2.3) :");
  for (const d of plan.derivees)
    l.push(`# ${d.cle} = ${fmt(d.valeur)}  # ${d.unite} — ${d.formule}${d.nominale ? " (valeurs nominales)" : ""}`);
  return l.join("\n") + "\n";
}

export function versMarkdown(plan: Plan, date: string): string {
  const c = plan.contraintes;
  const l = [
    `# Plan d'impression de la serre — ${date}`,
    "",
    `- Échelle : ${c.echelle} · priorité max : ${c.prioriteMax} · familles : ${c.familles.map((f) => `${f} ${FAMILLES[f]}`).join(", ")}`,
    `- Extérieur : ${c.exterieur ? "oui" : "non"} · près d'un driver LED : ${c.driverProche ? "oui" : "non"} · multicouleur : ${c.canvas ? "oui" : "non"}`,
    `- Filaments : ${c.filaments.join(", ")}`,
    "",
    "## Pièces",
    "",
    "| Id | Pièce | Priorité | Matériau | Parois | Remplissage | Remarques |",
    "|---|---|---|---|---|---|---|",
  ];
  for (const { piece, pertinence, choix } of plan.lignes) {
    const r = REGLAGES[piece.usage];
    const rem = [
      pertinence === "partiel" && `partiel : ${piece.partiel}`,
      choix.manquant && "filament manquant",
      piece.nePasImprimer && `ne pas imprimer : ${piece.nePasImprimer}`,
      piece.note,
    ].filter(Boolean);
    l.push(`| ${piece.id} | ${piece.titre} | ${piece.priorite} | ${libelleMateriau(choix)} | ${r.parois} | ${r.remplissage} | ${rem.join(" ; ")} |`);
  }
  l.push("", "## Cotes", "", "| Cote | Valeur | Unité |", "|---|---|---|");
  for (const k of COTES)
    l.push(`| ${k.cle} — ${k.libelle} | ${mesuree(plan.cotes, k.cle) ? fmt(plan.cotes[k.cle] as number) : `à mesurer (nominal ${fmt(k.nominal)})`} | ${k.unite} |`);
  l.push("", "## Cotes dérivées", "");
  for (const d of plan.derivees) l.push(`- ${d.libelle} (${d.pieces.join(", ")}) : ${fmt(d.valeur)} mm = ${d.formule}${d.nominale ? " — nominale" : ""}`);
  const liste = (titre: string, items: string[]) => {
    l.push("", `## ${titre}`, "");
    l.push(...(items.length ? items.map((t) => `- ${t}`) : ["- rien"]));
  };
  liste("À mesurer", plan.mesures.map((m) => `${m.cle} — ${COTE[m.cle].libelle} (${COTE[m.cle].outil}) : ${m.pieces.join(", ")}`));
  liste("Éprouvettes", plan.eprouvettes);
  liste("Contrôles", plan.controles.map((k) => `${k.niveau} : ${k.message}`));
  liste("Sécurité", plan.alertes.map((a) => a.texte));
  return l.join("\n") + "\n";
}

export function versJson(plan: Plan, date: string): string {
  return JSON.stringify(
    {
      version: 1,
      date,
      contraintes: plan.contraintes,
      cotes: Object.fromEntries(COTES.map((c) => [c.cle, mesuree(plan.cotes, c.cle) ? plan.cotes[c.cle] : null])),
      derivees: plan.derivees,
      controles: plan.controles,
      pieces: plan.lignes.map(({ piece, pertinence, choix }) => ({
        id: piece.id,
        titre: piece.titre,
        priorite: piece.priorite,
        pertinence,
        materiau: choix.materiau,
        filament_manquant: choix.manquant,
        opaque: choix.opaque,
        joint_tpu: choix.joint,
        reglages: REGLAGES[piece.usage],
        cotes: piece.cotes,
        modeles: piece.modeles,
      })),
      mesures: plan.mesures,
      eprouvettes: plan.eprouvettes,
      alertes: plan.alertes,
    },
    null,
    2,
  );
}
