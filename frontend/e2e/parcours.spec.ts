import { expect, test } from "@playwright/test";

// Create a zone → add an emplacement → drop a plant → publish the configuration →
// see a simulated decision → validate a proposal (docs/12 §6).
test("parcours constructeur puis validation d'une proposition", async ({ page, request }) => {
  await page.goto("/constructeur?zone=z1");
  await expect(page.getByTestId("emplacement-z1-A1")).toContainText("tomate");

  await page.getByRole("button", { name: "Zone", exact: true }).click();
  await page.getByLabel("Nom").fill("Semis e2e");
  await page.getByRole("button", { name: "Créer" }).click();
  await expect(page).toHaveURL(/zone=z3/);

  await page.getByRole("button", { name: "Créer l'emplacement A1" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Créer" }).click();
  const cell = page.getByTestId("emplacement-z3-A1");
  await expect(cell).toContainText("vide");

  await page.getByTestId("palette-tomate").dragTo(cell);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Nouvelle plante sur z3-A1");
  await dialog.getByRole("button", { name: "Planter" }).click();
  await expect(cell).toContainText("tomate");
  await expect(page.getByRole("complementary", { name: "Emplacement z3-A1" })).toBeVisible();

  await page.getByRole("button", { name: "Publier la configuration" }).click();
  await expect(page.getByRole("dialog")).toContainText("z3-A1");
  await page.getByRole("dialog").getByRole("button", { name: "Publier" }).click();
  await expect(page.getByRole("dialog")).toContainText(/Configuration v\d+ publiée/);
  await page.keyboard.press("Escape");

  // The simulated mildew on z1-A1 gives a proposal (isolate the plant).
  await expect
    .poll(async () => (await (await request.get("/api/decisions?statut=proposee")).json()).length, { timeout: 90_000 })
    .toBeGreaterThan(0);
  await page.goto("/tableau?zone=z1");
  await expect(page.getByTestId("tuile").first()).toBeVisible();
  const card = page.getByTestId("proposition").first();
  const id = (await card.getByRole("link").first().textContent())!;
  await card.getByRole("button", { name: "Valider" }).click();

  await page.goto(`/decisions/${id}`);
  await expect(page.getByText(/validée|exécutée|terminée/).first()).toBeVisible();
  await expect(page.getByText("[validée par ui:ui]", { exact: false })).toBeVisible();
});
