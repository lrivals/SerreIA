import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test-utils";
import { donneesDemo, DEMO } from "../fixture.test-utils";
import { BulleDialogue } from "./BulleDialogue";

describe("BulleDialogue", () => {
  it("plant: stage, hearts, gauges against the setpoint with their icon, vision", () => {
    renderWithProviders(
      <BulleDialogue cible={{ genre: "emplacement", id: "z1-A1" }} donnees={donneesDemo()} reduire onFermer={() => undefined} onAgent={() => undefined} />,
    );
    expect(screen.getByRole("dialog", { name: /Tomate « Cœur de bœuf » · z1-A1/ })).toBeInTheDocument();
    expect(screen.getByText(/floraison · plantée il y a \d+ j · recette tomate-standard · malade/)).toBeInTheDocument();
    expect(screen.getByLabelText(/santé \d sur 5/)).toBeInTheDocument();
    const hr = screen.getByTestId("jauge-humidite");
    expect(hr).toHaveTextContent("91 %");
    expect(hr).toHaveTextContent("(55–70)");
    expect(hr).toHaveTextContent("✖");
    expect(screen.getByTestId("jauge-temperature")).toHaveTextContent("✔");
    expect(screen.getByTestId("jauge-humidite_sol")).toBeInTheDocument(); // probe of z1-A1
    expect(screen.getByText(/mildiou 0,81/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Demander à l'agent" })).toBeInTheDocument();
  });

  it("hydro station, actuator and sensor", () => {
    const d = donneesDemo();
    const { unmount } = renderWithProviders(<BulleDialogue cible={{ genre: "cuve", id: "cuve-z2" }} donnees={d} reduire onFermer={() => undefined} />);
    expect(screen.getByTestId("jauge-ph")).toHaveTextContent("5,9");
    expect(screen.getByText(/Pompe pH−/)).toBeInTheDocument();
    unmount();
    renderWithProviders(
      <BulleDialogue cible={{ genre: "actionneur", id: "led-z1" }} donnees={d} conso={DEMO.conso} reduire onFermer={() => undefined} onCommande={() => undefined} />,
    );
    expect(screen.getByText(/en marche depuis/)).toBeInTheDocument();
    expect(screen.getByText(/6,5 h en marche · 0,78 kWh/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Commande manuelle" })).toBeInTheDocument();
  });

  it("read-only demo: no manual command", () => {
    renderWithProviders(
      <BulleDialogue cible={{ genre: "capteur", id: "ph-z2" }} donnees={donneesDemo()} reduire lectureSeule onFermer={() => undefined} />,
    );
    expect(screen.getByText(/à refaire/)).toBeInTheDocument(); // calibration overdue
  });
});
