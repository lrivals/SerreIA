import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { DecisionSummary } from "@/api/types";
import { renderWithProviders } from "@/test-utils";
import { CarteProposition } from "./CarteProposition";

const decision: DecisionSummary = {
  id: "dec-20261012-0231-z1-007",
  ts: "2026-10-12T00:31:00Z",
  zone: "z1",
  emplacements: ["z1-A1"],
  niveau: "agent",
  origine: "agent:conv-1",
  regle: { id: "agent.action", version: 1 },
  type: "manuelle",
  statut: "proposee",
  explication: "HR > 90 % depuis 11 h sur z1-A1 → ventilo on 900 s",
  actions: ["proposee:ventilo on 900 s"],
  expire: "2026-10-12T02:31:00Z",
};

afterEach(() => vi.unstubAllGlobals());

test("validate and reject a proposal", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ...decision, statut: "validee" })));
  vi.stubGlobal("fetch", fetch);
  renderWithProviders(<CarteProposition decision={decision} />);

  expect(screen.getByText("ventilo on 900 s")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "z1-A1" })).toHaveAttribute("href", "/constructeur?zone=z1&emplacement=z1-A1");

  fireEvent.click(screen.getByRole("button", { name: /Valider/ }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
  const [url, init] = fetch.mock.calls[0];
  expect(String(url)).toMatch(/\/api\/decisions\/dec-20261012-0231-z1-007\/valider$/);
  expect(init.method).toBe("POST");

  fireEvent.click(screen.getByRole("button", { name: /Rejeter/ }));
  fireEvent.change(screen.getByPlaceholderText("motif (optionnel)"), { target: { value: "porte ouverte" } });
  fireEvent.click(screen.getByRole("button", { name: "Confirmer le rejet" }));
  await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
  expect(String(fetch.mock.calls[1][0])).toMatch(/\/rejeter$/);
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ commentaire: "porte ouverte" });
});

test("no buttons once answered", () => {
  renderWithProviders(<CarteProposition decision={decision} statut="executee" />);
  expect(screen.queryByRole("button", { name: /Valider/ })).toBeNull();
  expect(screen.getByText("exécutée")).toBeInTheDocument();
});
