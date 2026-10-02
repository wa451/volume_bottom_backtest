import { test, expect } from "@playwright/test";
test("Kenmo戦略選択から実Workerの比較・曲線・理由・CSV・再実行", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/backtest/new");
  await expect(
    page.getByRole("heading", { name: "Strategy　戦略選択・比較" }),
  ).toBeVisible();
  await page.getByLabel("Kenmo Breakout", { exact: true }).check();
  await page.getByLabel("Kenmo Earnings Momentum", { exact: true }).check();
  await page.getByLabel("Kenmo Growth", { exact: true }).check();
  // Keep Bottom in this comparison, using a one-cell legacy grid.
  for (const label of ["30%", "40%", "50%", "60%"])
    await page
      .locator(".panel")
      .filter({
        has: page.getByRole("heading", { name: "02　戦略パラメータ" }),
      })
      .getByLabel(label, { exact: true })
      .uncheck();
  const bottom = page
    .locator(".panel")
    .filter({ has: page.getByRole("heading", { name: "02　戦略パラメータ" }) });
  for (const label of [
    "2倍",
    "3倍",
    "4倍",
    "5倍",
    "20営業日",
    "120営業日",
    "250営業日",
  ])
    await bottom.getByLabel(label, { exact: true }).uncheck();
  await page.getByLabel("高値更新条件 ON").uncheck();
  await page
    .locator(".strategy-section")
    .filter({
      has: page.getByRole("heading", { name: "Kenmo Breakout", exact: true }),
    })
    .getByLabel("出来高条件 ON")
    .uncheck();
  const dates = [
    ["分析開始日", "2025-01-01"],
    ["分析終了日", "2025-12-31"],
    ["Train開始", "2025-01-01"],
    ["Train終了", "2025-06-30"],
    ["Test開始", "2025-07-01"],
    ["Test終了", "2025-12-31"],
  ];
  for (const [label, value] of dates)
    await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByLabel("対象銘柄コード").fill("7203,6758,8306");
  await expect(
    page.getByText("評価の組み合わせ：4 / 上限256", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "バックテストを実行 →" }).click();
  await expect(page).toHaveURL(/\/backtests\/[a-f0-9-]+/);
  const jid = page.url().split("/").pop()!;
  await expect(
    page.getByRole("heading", { name: "戦略比較・ポートフォリオ検証" }),
  ).toBeVisible({ timeout: 180000 });
  await expect(
    page.getByRole("img", { name: "資産曲線とベンチマーク" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "同条件の戦略を横並び比較" }),
  ).toBeVisible();
  await page
    .getByLabel("並び替え", { exact: true })
    .selectOption("max_drawdown");
  await page.getByLabel("集計期間").selectOption("train");
  await page
    .locator(".panel")
    .filter({
      has: page.getByRole("heading", { name: "パラメータ比較", exact: true }),
    })
    .getByRole("row")
    .filter({ hasText: "Kenmo Breakout" })
    .getByRole("button", { name: "曲線・取引", exact: true })
    .click();
  await expect(
    page.getByRole("columnheader", { name: "Entry理由", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("読み込み中…", { exact: true })).toHaveCount(0);
  await expect(
    page.getByRole("cell", { name: "Kenmo Breakout", exact: true }).first(),
  ).toBeVisible();
  await expect(page.locator(".error[role=alert]")).toHaveCount(0);
  await expect(
    page.getByRole("img", { name: "ドローダウン曲線", exact: true }),
  ).toBeVisible();
  const details = await request.get(
    "/api/backtests/" +
      jid +
      "/strategy-trades?period_type=train&strategy_id=kenmo_breakout",
  );
  expect(details.status()).toBe(200);
  expect((await details.json()).items[0].entry_reason).toContain(
    "Kenmo Breakout",
  );
  const csv = await request.get(
    "/api/backtests/" + jid + "/files/strategy_results.csv",
  );
  expect(csv.status()).toBe(200);
  expect(await csv.text()).toContain("train_selected");
  await page.screenshot({
    path: "test-results/kenmo-comparison.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "同じ条件で再実行" }).click();
  await expect(page).not.toHaveURL(new RegExp(jid));
  await expect(
    page.getByRole("heading", { name: "戦略比較・ポートフォリオ検証" }),
  ).toBeVisible({ timeout: 180000 });
  expect(errors).toEqual([]);
});
