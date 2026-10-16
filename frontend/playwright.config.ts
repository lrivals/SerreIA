import { defineConfig } from "@playwright/test";

// End-to-end journey against the real API with a simulated greenhouse (docs/12 §6):
// `python -m backend.api --mqtt sim` serves the built front (`npm run build` first).
const PORT = 8799;
const RUN = `test-results/e2e-${Date.now()}`;
const PYTHON = process.env.PYTHON ?? ".venv/bin/python" // relative to the repository root;

export default defineConfig({
  testDir: "e2e",
  timeout: 120_000,
  expect: { timeout: 15_000 },
  use: { baseURL: `http://127.0.0.1:${PORT}`, trace: "retain-on-failure" },
  webServer: {
    command: [
      `mkdir -p ${RUN} && cd .. && ${PYTHON} -m backend.api`,
      `--db sqlite:///frontend/${RUN}/serre.db --mqtt sim --agent none --prefill-h 1`,
      `--http-port ${PORT} --images frontend/${RUN}/images --config-out frontend/${RUN}/config`,
      "--panne valeur:z1/humidite=92@0 --panne maladie:z1-A1/tomate/maladie/mildiou@15",
    ].join(" "),
    url: `http://127.0.0.1:${PORT}/api/zones`,
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
