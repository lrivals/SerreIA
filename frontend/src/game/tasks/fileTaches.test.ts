import type { LiveEvent } from "@/live/LiveProvider";
import { FileTaches, PEREMPTION_MS, tachesDe, type Contexte } from "./fileTaches";

const ctx: Contexte = {
  actionneur: (zone, type) => `${type}-${zone}`,
  emplacementsCamera: () => ["z1-A1", "z1-A2"],
  capteurNoeud: (n) => (n === "esp32-z1" ? "sht41-z1" : null),
};
const ev = (kind: LiveEvent["kind"], payload: unknown, subject: string | null = null, zone: string | null = "z1"): LiveEvent => ({ kind, zone, subject, payload });

describe("tachesDe", () => {
  it("maps each event of docs/13 §5 to its task and priority", () => {
    const [alerte] = tachesDe(ev("alerte", { niveau: "critique", message: "T° 41 °C" }), ctx, 0);
    expect(alerte).toMatchObject({ priorite: 1, action: "courir", persistante: true, bulle: "alert" });
    const [vent] = tachesDe(
      ev("decision", { type: "exceptionnelle", statut: "executee", regle: { id: "maladie.mildiou.ventilation" }, ordres: [{ cible: "actionneur:ventilo", action: "on" }] }),
      ctx,
      0,
    );
    expect(vent).toMatchObject({ priorite: 2, action: "ventiler", cible: { genre: "actionneur", id: "ventilo-z1" }, texte: "maladie.mildiou.ventilation" });
    const [dose] = tachesDe(ev("decision", { type: "securite", statut: "executee", ordres: [{ cible: "actionneur:pompe_ph_down", action: "on" }] }), ctx, 0);
    expect(dose.action).toBe("doser");
    const vision = tachesDe(ev("vision", { camera: "cam-z1-a", detections: [{ sante: "anormal", classe: "mildiou", classe_conf: 0.81 }] }, "cam-z1-a"), ctx, 0);
    expect(vision.map((t) => [t.priorite, t.action, t.cible?.id])).toEqual([
      [2, "inspecter", "z1-A1"],
      [2, "inspecter", "z1-A2"],
    ]);
    const [valider] = tachesDe(ev("decision", { statut: "proposee", explication: "isoler", emplacements: ["z1-A1"], ordres: [{ cible: "plante:z1-A1", action: "isolee" }] }), ctx, 0);
    expect(valider).toMatchObject({ priorite: 3, action: "noter", persistante: true, cible: { genre: "emplacement", id: "z1-A1" } });
    const [arroser] = tachesDe(ev("etat", { action: "on" }, "pompe_nutri"), ctx, 0);
    expect(arroser).toMatchObject({ priorite: 4, action: "arroser" });
    const [tap] = tachesDe(ev("status", "offline", "esp32-z1", null), ctx, 0);
    expect(tap).toMatchObject({ priorite: 3, action: "tapoter", cible: { genre: "capteur", id: "sht41-z1" } });
  });

  it("ignores routines and healthy images", () => {
    expect(tachesDe(ev("decision", { type: "routine", statut: "executee", ordres: [{ cible: "actionneur:led", action: "on" }] }), ctx, 0)).toEqual([]);
    expect(tachesDe(ev("vision", { detections: [{ sante: "sain", classe: "sain", classe_conf: 0.9 }] }, "cam"), ctx, 0)).toEqual([]);
    expect(tachesDe(ev("etat", { action: "off" }, "ventilo"), ctx, 0)).toEqual([]);
    expect(tachesDe(ev("capteur", { valeur: 20 }, "temperature"), ctx, 0)).toEqual([]);
  });
});

describe("FileTaches", () => {
  const routine = (now: number) => tachesDe(ev("etat", { action: "on" }, "pompe_nutri"), ctx, now)[0];

  it("plays the highest priority first, then the oldest", () => {
    const f = new FileTaches();
    f.ajouter(routine(0));
    f.ajouter(tachesDe(ev("alerte", { niveau: "critique", message: "x" }), ctx, 10)[0]);
    f.ajouter(tachesDe(ev("status", "offline", "esp32-z1", null), ctx, 5)[0]);
    expect([f.suivante(20)?.action, f.suivante(20)?.action, f.suivante(20)?.action, f.suivante(20)]).toEqual(["courir", "tapoter", "arroser", null]);
  });

  it("groups the same task as ×n", () => {
    const f = new FileTaches();
    f.ajouter(routine(0));
    f.ajouter(routine(1));
    f.ajouter(routine(2));
    expect(f.taille).toBe(1);
    expect(f.suivante(3)?.compteur).toBe(3);
  });

  it("drops stale tasks except alerts and validations", () => {
    const f = new FileTaches();
    f.ajouter(routine(0));
    f.ajouter(tachesDe(ev("alerte", { niveau: "critique", message: "x" }), ctx, 0)[0]);
    f.ajouter(tachesDe(ev("decision", { statut: "proposee", explication: "isoler", emplacements: ["z1-A1"] }), ctx, 0)[0]);
    f.purger(PEREMPTION_MS + 1);
    expect(f.apercu().map((t) => t.action)).toEqual(["courir", "noter"]);
    f.retirer((t) => t.action === "noter");
    expect(f.taille).toBe(1);
  });
});
