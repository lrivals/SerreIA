// Offline demonstrations: the hand-made one and the frozen histories of the simulated
// scenarios (docs/16), checked when they were generated (`make scenario-figer NOM=…`).
import { existsSync, readFileSync } from "node:fs";
import { fichierDemo, type Demo } from "./donnees";
import { construireMonde } from "./monde";

describe("fichierDemo", () => {
  it("maps the demo parameter to a file of public/", () => {
    expect(fichierDemo("1")).toBe("demo/serre-demo.json");
    expect(fichierDemo("journee")).toBe("demo/scenario-journee.json");
    expect(fichierDemo("../secret")).toBe("demo/serre-demo.json");
  });
});

describe.each(["journee", "mildiou"])("scenario %s", (nom) => {
  const path = `public/${fichierDemo(nom)}`;
  it.skipIf(!existsSync(path))("builds the world and replays events in order", () => {
    const demo = JSON.parse(readFileSync(path, "utf8")) as Demo;
    const m = construireMonde(demo.donnees);
    expect(m.zones.map((z) => z.id)).toEqual(["z1", "z2"]);
    expect(demo.evenements.length).toBeGreaterThan(0);
    const t = demo.evenements.map((e) => e.t);
    expect(t).toEqual([...t].sort((a, b) => a - b));
    expect(demo.evenements.some((e) => e.evenement.kind === "decision")).toBe(true);
  });
});
