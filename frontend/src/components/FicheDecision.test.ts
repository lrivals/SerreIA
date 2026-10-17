import type { PreuveCapteur } from "@/api/types";
import { ruleWindow } from "./FicheDecision";

const p = (agregat: string, valeur: number, unite = "%"): PreuveCapteur => ({
  topic: "serre/z1/capteur/humidite",
  agregat,
  valeur,
  unite,
  qualite: "ok",
  seuil: 90,
  emplacement: null,
});
const TS = "2026-10-12T02:00:00Z";
const t = Date.parse(TS);
const H = 3600_000;

test("window used by the rule, from the aggregate", () => {
  expect(ruleWindow(p("duree_au_dessus", 11.2, "h"), TS)).toEqual([t - 11.2 * H, t]);
  expect(ruleWindow(p("moyenne_12h", 17.8, "°C"), TS)).toEqual([t - 12 * H, t]);
  expect(ruleWindow(p("derniere", 93), TS)).toEqual([t - 10 * 60_000, t]);
  expect(ruleWindow(p("autre", 1), TS)).toEqual([t - H, t]);
});

test("the threshold stays in the y domain", async () => {
  const { yDomain } = await import("./Charts");
  const [lo, hi] = yDomain([91.9, 92.1], [90, null])!;
  expect(lo).toBeLessThanOrEqual(90);
  expect(hi).toBeGreaterThanOrEqual(92.1);
});
