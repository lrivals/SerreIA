import { expect, test, type Page } from "@playwright/test";

// Game view (docs/13 §9): build from the game (a pot then a tomato, undo), a manual
// decision played by the gardener, "Demander à l'agent" opens the chat pre-filled.

type Monde = {
  zones: { id: string; x: number; y: number; largeur: number; hauteur: number }[];
  entites: { ref: { genre: string; id: string }; x: number; y: number }[];
};

const monde = (page: Page) => page.evaluate(() => (window as unknown as { __serreJeu: { monde: () => Monde } }).__serreJeu.monde());
const ecran = (page: Page, x: number, y: number) =>
  page.evaluate(([x, y]) => (window as unknown as { __serreJeu: { ecran: (x: number, y: number) => { x: number; y: number } } }).__serreJeu.ecran(x, y), [x, y]);

/** HTML5 drag of an inventory item onto the screen point of a tile. */
async function deposer(page: Page, item: string, x: number, y: number) {
  const p = await ecran(page, x, y);
  const canvas = page.getByTestId("jeu-canvas");
  const box = (await canvas.boundingBox())!;
  await page.getByTitle(`Glisser sur une case libre : ${item}`).dragTo(canvas, { targetPosition: { x: p.x - box.x, y: p.y - box.y } });
}

test("construire en jeu, puis le jardinier joue une décision", async ({ page, request }) => {
  await page.goto("/jeu");
  await expect(page.getByText(/Serre « /)).toBeVisible();
  await expect.poll(async () => (await page.evaluate(() => !!(window as unknown as { __serreJeu?: unknown }).__serreJeu)) && (await monde(page))?.zones.length).toBeGreaterThan(0);

  await page.getByRole("button", { name: "🔨 Construire" }).click();
  await page.waitForTimeout(500); // the canvas narrows next to the inventory

  // a free tile of z1, visible on screen, away from the existing objects
  const m = await monde(page);
  const z1 = m.zones.find((z) => z.id === "z1")!;
  const pris = new Set(m.entites.map((e) => `${e.x},${e.y}`));
  const box = (await page.getByTestId("jeu-canvas").boundingBox())!;
  let libre: { x: number; y: number } | null = null;
  for (let y = z1.y + z1.hauteur - 3; y > z1.y + 1 && !libre; y--)
    for (let x = z1.x + 2; x < z1.x + z1.largeur - 2 && !libre; x++) {
      if (pris.has(`${x},${y}`)) continue;
      const p = await ecran(page, x, y);
      if (p.x > box.x + 40 && p.x < box.x + box.width - 40 && p.y > box.y + 40 && p.y < box.y + box.height - 40) libre = { x, y };
    }
  expect(libre).not.toBeNull();

  await page.getByRole("tab", { name: "Contenants" }).click();
  await deposer(page, "pot", libre!.x, libre!.y);
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Nouvel emplacement dans z1");
  const code = await dialog.getByLabel("Code").inputValue();
  await dialog.getByRole("button", { name: "Créer" }).click();
  await expect
    .poll(async () => (await (await request.get(`/api/emplacements/z1-${code}`)).json()).disposition)
    .toEqual({ x: libre!.x, y: libre!.y });

  await page.getByRole("tab", { name: "Plantes" }).click();
  await deposer(page, "tomate", libre!.x, libre!.y);
  await expect(dialog).toContainText(`Nouvelle plante sur z1-${code}`);
  await dialog.getByRole("button", { name: "Planter" }).click();
  const plantes = async () => (await (await request.get("/api/plantes")).json()) as { id: string; emplacement: string | null }[];
  await expect.poll(async () => (await plantes()).some((p) => p.emplacement === `z1-${code}`)).toBe(true);

  await page.getByRole("button", { name: "↶ Annuler" }).click();
  await expect.poll(async () => (await plantes()).some((p) => p.emplacement === `z1-${code}`)).toBe(false);

  // a manual decision: the fan runs, the gardener goes and switches it
  await page.getByRole("button", { name: "▶ Serre vivante" }).click();
  const r = await request.post("/api/actions/manuelle", {
    data: { zone: "z1", actionneur: "ventilo", action: "on", duree_s: 120, justification: "e2e jeu" },
  });
  expect(r.ok()).toBe(true);
  await expect(page.getByRole("status").filter({ hasText: "actionne" })).toBeVisible({ timeout: 30_000 });

  // inspection bubble of z1-A1 → ask the agent, chat pre-filled
  const a1 = (await monde(page)).entites.find((e) => e.ref.id === "z1-A1")!;
  const p = await ecran(page, a1.x, a1.y);
  await page.mouse.click(p.x, p.y);
  await expect(page.getByRole("dialog", { name: /z1-A1/ })).toBeVisible();
  await page.getByRole("button", { name: "Demander à l'agent" }).click();
  await expect(page.getByLabel("Message à l'agent")).toHaveValue(/z1-A1/);
});
