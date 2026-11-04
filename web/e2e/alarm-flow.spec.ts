// Critério de pronto da sprint 4, num navegador de verdade:
// provocar uma falha no simulador e ver o alarme aparecer no dashboard.
import { expect, test, type APIRequestContext } from "@playwright/test";

const SIMULATOR = process.env.SIMULATOR_URL ?? "http://localhost:8080";

async function scenario(request: APIRequestContext, body: object) {
  const resp = await request.post(`${SIMULATOR}/scenarios`, { data: body });
  expect(resp.ok()).toBeTruthy();
}

test.beforeEach(async ({ request }) => scenario(request, { type: "reset" }));
test.afterEach(async ({ request }) => scenario(request, { type: "reset" }));

test("falha no simulador aparece no dashboard em tempo real", async ({ page, request }) => {
  // 1. conta nova do provedor
  await page.goto("/");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await page.getByLabel("Empresa (provedor)").fill("Provedor E2E");
  await page.getByLabel("Seu nome").fill("Ana Operadora");
  await page.getByLabel("E-mail").fill(`e2e-${Date.now()}@e2e.lumio.com.br`);
  await page.getByLabel("Senha").fill("senha-forte-123");
  await page.getByRole("button", { name: "Criar conta" }).click();
  await expect(page.getByRole("link", { name: "Cadastrar OLT" })).toBeVisible();

  // 2. cadastra a OLT do simulador, testando a conexão antes
  await page.getByRole("link", { name: "Cadastrar OLT" }).click();
  await page.getByRole("button", { name: "Nova OLT" }).click();
  await page.getByLabel("Nome", { exact: true }).fill("Centro");
  await page.getByLabel("Endereço (IP ou nome)").fill("simulator");
  await page.getByLabel("Porta").fill("16101");
  await page.getByLabel("Community").fill("public");
  await page.getByRole("button", { name: "Testar conexão" }).click();
  await expect(page.getByText(/Huawei MA5800-X7/)).toBeVisible();
  await page.getByRole("button", { name: "Salvar" }).click();
  await expect(page.getByText(/4 portas PON e 64 ONUs descobertas/)).toBeVisible();

  // 3. espera o coletor pegar o cadastro (relê a cada 30 s) e a primeira coleta
  await expect(page.getByText("Coletando")).toBeVisible({ timeout: 75_000 });

  // 4. tela de alarmes aberta, sem nada
  await page.getByRole("link", { name: "Alarmes" }).click();
  await expect(page.getByText("Nenhum alarme aberto. Rede normal.")).toBeVisible();
  await expect(page.getByText("Ao vivo")).toBeVisible();

  // 5. falha no simulador; o alarme tem de aparecer sem recarregar a página.
  //    O polling de reserva é de 30 s: aparecer em até 5 s só é possível pelo tempo real.
  const t0 = Date.now();
  await scenario(request, { type: "fiber_cut", olt: "olt-centro", pon: "0/1/2" });
  const row = page.locator("tr", { hasText: "Rompimento de fibra" });
  await expect(row).toBeVisible({ timeout: 5_000 });
  const latency = Date.now() - t0;
  console.log(`falha no simulador -> alarme na tela: ${latency} ms`);
  await expect(row.getByText("Crítico")).toBeVisible();
  await expect(row.getByText("Centro · PON 0/1/2")).toBeVisible();
  await expect(row.getByText("novo")).toBeVisible();
  await expect(page.getByRole("link", { name: /Alarmes.*1 abertos/ })).toBeVisible();

  // 6. as 16 ONUs afetadas ficam dentro do rompimento
  await row.getByRole("button", { name: "Ver 16 ONUs afetadas" }).click();
  await expect(page.getByRole("list", { name: /ONUs afetadas/ }).getByRole("listitem")).toHaveCount(16);

  // 7. reconhecer
  await row.getByRole("button", { name: "Reconhecer" }).click();
  await expect(row.getByText("Reconhecido")).toBeVisible();
  await expect(row.getByText("por Ana Operadora")).toBeVisible();

  // 8. visão geral reflete a falha
  await page.getByRole("link", { name: "Visão geral" }).click();
  await expect(page.getByRole("region", { name: "ONUs online" }).getByText("48 / 64")).toBeVisible();

  // 9. a rede volta: o alarme sai dos abertos sozinho
  await page.getByRole("link", { name: /Alarmes/ }).click();
  await scenario(request, { type: "reset" });
  await expect(page.getByText("Nenhum alarme aberto. Rede normal.")).toBeVisible({ timeout: 5_000 });
});
