import { donneesDemo } from "./fixture.test-utils";
import { caseDevant, caseLibre, cleCase, construireMonde, entiteA } from "./monde";

describe("construireMonde", () => {
  it("lays out zones side by side without overlap, objects inside their zone", () => {
    const m = construireMonde(donneesDemo());
    expect(m.zones.map((z) => z.id)).toEqual(["z1", "z2"]);
    const [a, b] = m.zones;
    expect(a.x + a.largeur).toBeLessThanOrEqual(b.x);
    const cases = new Set<string>();
    for (const e of m.entites) {
      const k = cleCase(e.x, e.y);
      expect(cases.has(k), `${e.ref.id} on an occupied tile`).toBe(false);
      cases.add(k);
      const z = m.zones.find((x) => x.id === e.zone)!;
      expect(e.x > z.x && e.x < z.x + z.largeur - 1 && e.y > z.y && e.y < z.y + z.hauteur - 1, `${e.ref.id} inside ${z.id}`).toBe(true);
      expect(m.bloques.has(k)).toBe(true);
    }
    expect(m.largeur).toBeGreaterThanOrEqual(b.x + b.largeur);
  });

  it("follows the grid of the classic plan, then the disposition when present", () => {
    const d = donneesDemo();
    let m = construireMonde(d);
    const a1 = m.entites.find((e) => e.ref.id === "z1-A1")!;
    const a2 = m.entites.find((e) => e.ref.id === "z1-A2")!;
    const b1 = m.entites.find((e) => e.ref.id === "z1-B1")!;
    expect(a2.x - a1.x).toBe(2);
    expect(b1.y - a1.y).toBe(3);
    d.plans[0].emplacements[0].disposition = { x: 4, y: 9 };
    d.zones[1].disposition = { x: 40, y: 2, largeur: 10, hauteur: 8 };
    m = construireMonde(d);
    expect(m.entites.find((e) => e.ref.id === "z1-A1")).toMatchObject({ x: 4, y: 9 });
    expect(m.zones.find((z) => z.id === "z2")).toMatchObject({ x: 40, y: 2, largeur: 10, hauteur: 8 });
  });

  it("shows the data: plant layers, bubbles, ambience, offline sensors", () => {
    const d = donneesDemo();
    d.noeuds[1].status = "offline";
    const m = construireMonde(d);
    const a1 = m.entites.find((e) => e.ref.id === "z1-A1")!;
    expect(a1.couches.map((c) => c.frame)).toEqual(["containers/plastic_pot", "plants/tomato/flowering/sick"]);
    expect(a1.bulle).toBe("thinking"); // proposal waiting on z1-A1
    expect(m.entites.find((e) => e.ref.id === "z1-A4")!.bulle).toBe("heart"); // harvest ready
    expect(m.entites.find((e) => e.ref.id === "z1-B3")!.overlay).toBe("cloche");
    const z1 = m.zones.find((z) => z.id === "z1")!;
    expect(z1.buee && z1.halo).toBe(true); // HR 91 % > 70, LED on
    const ph = m.entites.find((e) => e.ref.genre === "capteur" && e.ref.id === "ph-z2")!;
    expect(ph.bulle).toBe("alert");
    const sht = m.entites.find((e) => e.ref.id === "sht41-z1")!;
    expect(sht.couvre).toContain("z1-B4"); // one box for the two channels
    expect(m.entites.filter((e) => e.ref.id === "sht41-z1")).toHaveLength(1);
    expect(m.entites.find((e) => e.ref.genre === "cuve")?.couches[0].frame).toBe("sensors/water_tank/half/0");
  });

  it("names the objects of the consistency warnings", () => {
    const d = donneesDemo();
    d.avertissements = ["z1-B4 : emplacement sans capteur de sol"];
    expect(construireMonde(d).entites.find((e) => e.ref.id === "z1-B4")!.bulle).toBe("alert");
  });
});

describe("builder helpers", () => {
  const m = construireMonde(donneesDemo());
  const z1 = m.zones[0];

  it("a free tile is inside a zone, off the walls, not occupied", () => {
    const a1 = entiteA(m, ...([m.entites[0].x, m.entites[0].y] as const))!;
    expect(caseLibre(m, a1.x, a1.y).ok).toBe(false);
    expect(caseLibre(m, a1.x, a1.y, a1.ref).ok).toBe(true); // moving it onto itself
    expect(caseLibre(m, z1.x, z1.y + 2)).toMatchObject({ ok: false, raison: "hors zone" });
    expect(caseLibre(m, z1.x + 2, z1.y + 2).ok).toBe(true);
  });

  it("the gardener stands on a walkable tile next to an object", () => {
    for (const e of m.entites) {
      const c = caseDevant(m, e.x, e.y);
      expect(m.bloques.has(cleCase(c.x, c.y)), e.ref.id).toBe(false);
    }
  });
});
