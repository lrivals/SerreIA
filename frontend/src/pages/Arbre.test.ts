import type { TreeNode } from "@/api/types";
import { flatten } from "./Arbre";

const tree: TreeNode = {
  id: "serre",
  type: "serre",
  label: "Serre",
  children: [
    {
      id: "z1",
      type: "zone",
      label: "z1",
      children: [
        {
          id: "z1/routine",
          type: "groupe",
          label: "Routines",
          children: [{ id: "z1/routine/r", type: "routine", regle: "r", label: "r", cycles: 14, decisions: ["d1", "d2"] }],
        },
        {
          id: "z1/exceptionnelle",
          type: "groupe",
          label: "Exceptionnelles",
          children: [
            {
              id: "dec-x",
              type: "decision",
              statut: "executee",
              children: [{ id: "act-x-01", type: "action", cible: "actionneur:ventilo", label: "ventilo on", resultat: "confirmee" }],
            },
          ],
        },
      ],
    },
  ],
};

test("routines collapsed, exceptional decisions open", () => {
  const ids = flatten(tree, new Set(), new Set()).nodes.map((n) => n.id);
  expect(ids).toContain("act-x-01");
  expect(ids).not.toContain("d1");
  const open = flatten(tree, new Set(["z1/routine/r"]), new Set(["dec-x"]));
  expect(open.nodes.map((n) => n.id)).toEqual(expect.arrayContaining(["d1", "d2"]));
  expect(open.nodes.map((n) => n.id)).not.toContain("act-x-01");
  expect(open.edges).toContainEqual(expect.objectContaining({ source: "z1/routine/r", target: "d1" }));
});
