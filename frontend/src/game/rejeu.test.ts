import type { TreeNode } from "@/api/types";
import { actifsA, chronologie, entre, valeurA } from "./rejeu";

const arbre: TreeNode = {
  id: "serre",
  type: "serre",
  debut: "2026-10-16T00:00:00Z",
  fin: "2026-10-17T00:00:00Z",
  children: [
    {
      id: "z1",
      type: "zone",
      children: [
        { id: "z1/routine", type: "groupe", children: [{ id: "z1/routine/x", type: "routine" }] },
        {
          id: "z1/exceptionnelle",
          type: "groupe",
          children: [
            {
              id: "dec-1",
              type: "decision",
              ts: "2026-10-16T02:31:00Z",
              statut: "executee",
              regle: "maladie.mildiou.ventilation",
              resume: "mildiou",
              children: [
                { id: "a1", type: "action", cible: "actionneur:ventilo", ts_debut: "2026-10-16T02:31:00Z", ts_fin: "2026-10-16T02:46:00Z" },
                { id: "a2", type: "action", cible: "plante:z1-A1", ts_debut: "2026-10-16T02:31:00Z" },
              ],
            },
          ],
        },
      ],
    },
  ],
};
const t = (iso: string) => new Date(iso).getTime();

describe("replay", () => {
  const c = chronologie(arbre, [
    {
      zone: "z1",
      debut: "",
      fin: "",
      agregat: "moy_15min",
      series: [{ type: "humidite", emplacement: null, unite: "%", n_mesures: 2, min: 0, max: 0, moyenne: 0, points: [["2026-10-16T02:00:00Z", 92], ["2026-10-16T03:00:00Z", 70]] }],
    },
  ]);

  it("turns exceptional decisions and their actions into timed events", () => {
    expect(c.evenements.map((e) => [e.evenement.kind, e.evenement.subject])).toEqual([
      ["decision", "dec-1"],
      ["etat", "ventilo"],
      ["etat", "ventilo"],
    ]);
    expect(c.evenements[0].evenement.payload).toMatchObject({
      type: "exceptionnelle",
      regle: { id: "maladie.mildiou.ventilation" },
      emplacements: ["z1-A1"],
      ordres: [{ cible: "actionneur:ventilo" }, { cible: "plante:z1-A1" }],
    });
    expect(entre(c, t("2026-10-16T02:00:00Z"), t("2026-10-16T02:40:00Z"))).toHaveLength(2);
  });

  it("actuator states and measurements at an instant", () => {
    expect(actifsA(c, t("2026-10-16T02:35:00Z"))).toEqual(new Set(["z1:ventilo"]));
    expect(actifsA(c, t("2026-10-16T03:00:00Z")).size).toBe(0);
    expect(valeurA(c.series.z1.humidite, t("2026-10-16T01:00:00Z"))).toBeNull();
    expect(valeurA(c.series.z1.humidite, t("2026-10-16T02:30:00Z"))).toBe(92);
    expect(valeurA(c.series.z1.humidite, t("2026-10-16T04:00:00Z"))).toBe(70);
  });
});
