import { COTES, PIECES } from "./catalogue";
import {
  CONTRAINTES_DEFAUT,
  controles,
  derivees,
  materiau,
  mesures,
  planifier,
  selectionner,
  versJson,
  versMarkdown,
  versToml,
  type Contraintes,
} from "./plan";

const avec = (c: Partial<Contraintes>): Contraintes => ({ ...CONTRAINTES_DEFAUT, ...c });
const ids = (c: Contraintes) => selectionner(c).map((l) => l.piece.id);
const piece = (id: string) => PIECES.find((p) => p.id === id)!;

test("selection follows the priority and the scale", () => {
  const p0 = ids(avec({ prioriteMax: "P0" }));
  expect(p0.sort()).toEqual(["A4", "D1", "D2", "D4", "D5"]);
  expect(ids(avec({ prioriteMax: "P1" }))).not.toContain("C3");
  expect(ids(avec({ prioriteMax: "Evolution" }))).toContain("C3");
  expect(ids(avec({ echelle: "petite", prioriteMax: "P2" }))).not.toContain("B3");
  const grande = selectionner(avec({ echelle: "grande" })).find((l) => l.piece.id === "B1");
  expect(grande?.pertinence).toBe("partiel");
  expect(ids(avec({ familles: ["D"] })).every((id) => id.startsWith("D"))).toBe(true);
});

test("never PLA, even when no filament is available", () => {
  const c = avec({ filaments: [], prioriteMax: "Evolution" });
  for (const l of selectionner(c)) expect(l.choix.materiau).not.toBe("PLA");
});

test("material: first available candidate, missing filament flagged", () => {
  expect(materiau(piece("B1"), avec({ filaments: ["ASA"] }))).toMatchObject({ materiau: "ASA", manquant: false });
  expect(materiau(piece("B1"), avec({ filaments: ["ASA-CF", "ASA"] })).materiau).toBe("ASA-CF");
  expect(materiau(piece("B2"), avec({ filaments: ["PETG"] }))).toMatchObject({ materiau: "ASA", manquant: true });
});

test("near an LED driver, lighting parts are ASA / ABS only", () => {
  const c1 = materiau(piece("C1"), avec({ driverProche: true, filaments: ["PETG", "PETG-CF", "ABS"] }));
  expect(c1.materiau).toBe("ABS");
  expect(materiau(piece("C1"), avec({ filaments: ["PETG-CF"] })).materiau).toBe("PETG-CF");
});

test("parts touching water are opaque, gasket where needed", () => {
  expect(materiau(piece("A4"), CONTRAINTES_DEFAUT)).toMatchObject({ materiau: "PETG", opaque: true, joint: true });
  expect(materiau(piece("D1"), CONTRAINTES_DEFAUT).opaque).toBe(false);
});

test("derived film clip diameter and nominal flag", () => {
  const clip = (cotes: Record<string, number>) => derivees(cotes).find((d) => d.cle === "clip_bache_d_int")!;
  expect(clip({ tube_d: 20.4, film_ep: 0.15, jeu: 0.25 }).valeur).toBeCloseTo(20.95);
  expect(clip({ tube_d: 20.4, film_ep: 0.15, jeu: 0.25 }).nominale).toBe(false);
  expect(clip({ tube_d: 20.4 }).nominale).toBe(true);
});

test("checks mirror hardware/params.py verifier()", () => {
  expect(controles({}).filter((k) => k.niveau === "erreur")).toEqual([]);
  const jsn = controles({ cuve_hauteur: 400, cuve_niveau_max: 300 }).find((k) => k.cle === "cuve_niveau_max");
  expect(jsn?.niveau).toBe("erreur");
  expect(jsn?.message).toContain("zone aveugle");
  expect(controles({ tube_d: 25 }).some((k) => k.cle === "tube_d" && k.message.includes("emmanchement"))).toBe(true);
  expect(controles({ jeu: 0.05 }).some((k) => k.cle === "jeu" && k.niveau === "erreur")).toBe(true);
  expect(controles({ tube_d: 200 }).some((k) => k.message.includes("hors de la plage"))).toBe(true);
  expect(controles({ seau_d: 300 }, ["A3"]).some((k) => k.cle === "seau_d")).toBe(true);
  expect(controles({ seau_d: 300 }, ["D1"]).some((k) => k.cle === "seau_d")).toBe(false);
  expect(controles({}, ["A3"]).some((k) => k.cle === "seau_d")).toBe(false);
});

test("missing measurements list the parts that need them", () => {
  const lignes = selectionner(avec({ familles: ["B"] }));
  const m = mesures(lignes, { tube_d: 20.2 });
  expect(m.map((x) => x.cle)).toContain("film_ep");
  expect(m.map((x) => x.cle)).not.toContain("tube_d");
  expect(m.find((x) => x.cle === "jeu")?.pieces).toEqual(expect.arrayContaining(["B1", "B2"]));
});

test("test pieces for tight fits, clearance rings first", () => {
  const plan = planifier(avec({ familles: ["B"] }), {});
  expect(plan.eprouvettes[0]).toContain("Anneaux de jeu");
  expect(plan.eprouvettes.some((e) => e.startsWith("B2"))).toBe(true);
  expect(planifier(avec({ familles: ["B"] }), { jeu: 0.3 }).eprouvettes[0]).not.toContain("Anneaux de jeu");
});

test("safety alerts follow the selection", () => {
  const texte = (c: Contraintes) => planifier(c, {}).alertes.map((a) => a.texte).join("\n");
  expect(texte(avec({ familles: ["C"] }))).toContain("câble de sécurité");
  expect(texte(avec({ familles: ["E"], prioriteMax: "P2" }))).not.toContain("câble de sécurité");
  expect(texte(avec({ familles: ["B"], exterieur: true }))).toContain("vent");
  expect(texte(avec({ familles: ["D"], prioriteMax: "P0" }))).toContain("230 V");
});

test("mesures.toml: only params.py keys as values, no undefined / NaN", () => {
  const plan = planifier(CONTRAINTES_DEFAUT, { tube_d: 20.4, film_ep: 0.15, netpot_d: 52 });
  const toml = versToml(plan, "2026-10-29");
  const actives = toml.split("\n").filter((l) => l.trim() && !l.startsWith("#"));
  expect(actives).toEqual(["tube_d = 20.4  # Ø extérieur du tube de structure", "film_ep = 0.15  # Épaisseur du film (0,2 = 200 µm)"]);
  const params = new Set(COTES.filter((c) => c.params).map((c) => c.cle));
  for (const l of actives) expect(params.has(l.split(" ")[0])).toBe(true);
  expect(toml).toContain("# netpot_d = 52");
  expect(toml).toContain("# jeu = 0.3  # À MESURER");
  for (const out of [toml, versMarkdown(plan, "2026-10-29"), versJson(plan, "2026-10-29")]) {
    expect(out).not.toMatch(/undefined|NaN/);
  }
  expect(JSON.parse(versJson(plan, "2026-10-29")).cotes.tube_d).toBe(20.4);
});
