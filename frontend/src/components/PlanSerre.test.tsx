import { fireEvent, render, screen } from "@testing-library/react";
import type { EmplacementPlan } from "@/api/types";
import { DND_ESPECE, DND_PLANTE, PlanSerre } from "./PlanSerre";

const emp = (code: string, rangee: number, colonne: number, plante = false): EmplacementPlan => ({
  id: `z1-${code}`,
  zone_id: "z1",
  code,
  mode_culture: "terre",
  rangee,
  colonne,
  contenant_id: null,
  contenant: null,
  capteurs: [],
  cameras: [],
  vision: null,
  plante: plante
    ? {
        id: "tomate-1",
        espece: "tomate",
        variete: null,
        date_semis: null,
        date_plantation: null,
        stade: "floraison",
        recette_id: "tomate-standard",
        etat_sante: "a_surveiller",
        prioritaire: false,
        notes: null,
      }
    : null,
});

function dataTransfer(type: string, value: string) {
  return { types: [type], getData: (t: string) => (t === type ? value : ""), setData: () => {} };
}

test("grid, creation cells, drop of a species and move of a plant", () => {
  const actions = { onSelect: vi.fn(), onDropEspece: vi.fn(), onMovePlante: vi.fn(), onCreateAt: vi.fn() };
  render(<PlanSerre emplacements={[emp("A1", 1, 1, true), emp("A2", 1, 2)]} {...actions} />);

  expect(screen.getByText("tomate")).toBeInTheDocument();
  expect(screen.getByTitle("à surveiller")).toBeInTheDocument();
  // 2 rows × 3 columns: 2 emplacements, 4 "+" cells.
  expect(screen.getAllByRole("button", { name: /Créer l'emplacement/ })).toHaveLength(4);
  fireEvent.click(screen.getByRole("button", { name: "Créer l'emplacement B2" }));
  expect(actions.onCreateAt).toHaveBeenCalledWith("B2", 2, 2);

  const empty = screen.getByTestId("emplacement-z1-A2");
  fireEvent.dragOver(empty, { dataTransfer: dataTransfer(DND_ESPECE, "fraisier") });
  fireEvent.drop(empty, { dataTransfer: dataTransfer(DND_ESPECE, "fraisier") });
  expect(actions.onDropEspece).toHaveBeenCalledWith("z1-A2", "fraisier");
  fireEvent.drop(empty, { dataTransfer: dataTransfer(DND_PLANTE, "tomate-1") });
  expect(actions.onMovePlante).toHaveBeenCalledWith("tomate-1", "z1-A2");

  fireEvent.click(screen.getByTestId("emplacement-z1-A1"));
  expect(actions.onSelect).toHaveBeenCalledWith("z1-A1");
});
