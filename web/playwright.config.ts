import { defineConfig, devices } from "@playwright/test";

// Teste de ponta a ponta contra a stack no ar (docker compose up):
//   npx playwright test
// LUMIO_URL e SIMULATOR_URL mudam os endereços padrão.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 10_000 },
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.LUMIO_URL ?? "http://localhost:3000",
    locale: "pt-BR",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
