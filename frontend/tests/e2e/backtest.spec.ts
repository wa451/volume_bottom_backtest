import { test, expect } from "@playwright/test";
test("実APIと独立Workerで、設定・ヒートマップ・検索・CSV・履歴・再実行", async ({
  page,
  request,
}) => {
  const baseline = await (await request.get("/api/backtests?limit=1")).json();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  await page
    .getByRole("link", { name: "＋ 新規バックテスト", exact: true })
    .last()
    .click();
  await expect(
    page.getByRole("heading", { name: "新規バックテスト" }),
  ).toBeVisible();
  await page
    .getByLabel("対象銘柄コード")
    .fill(process.env.E2E_TICKERS || "130A,4477,6758,7203,8306");
  await expect(
    page.getByRole("button", { name: "バックテストを実行 →" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "バックテストを実行 →" }).dblclick();
  await expect(page).toHaveURL(/\/backtests\/[a-f0-9-]+/);
  const jid = page.url().split("/").pop()!;
  expect(
    (await (await request.get("/api/backtests?limit=1")).json()).total,
  ).toBe(baseline.total + 1);
  await expect(page.getByRole("tab", { name: "ヒートマップ" })).toBeVisible({
    timeout: 180000,
  });
  await expect(
    page.getByText("Survivorship Bias", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "ヒートマップ" }).click();
  await expect(
    page.getByRole("button", { name: "下落率30% 出来高3倍", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "下落率30% 出来高3倍", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: /条件詳細/ })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "リターン分布", exact: true }),
  ).toBeVisible();
  await page.getByLabel("セルの指標").selectOption("win_rate");
  await page.getByLabel("保有期間", { exact: true }).selectOption("60");
  await page.getByRole("button", { name: "Mega", exact: true }).click();
  await page.getByLabel("評価期間").selectOption("test");
  await page.getByRole("tab", { name: "時価総額別", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "時価総額別の比較" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "市場別", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "市場別の比較" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "パラメータ比較", exact: true }).click();
  await page.getByLabel("並び順").selectOption("num_trades");
  await expect(
    page.getByRole("heading", { name: "パラメータ比較 · TEST" }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "取引一覧", exact: true }).click();
  await page.getByLabel("取引銘柄検索").fill("7203");
  await expect(
    page.getByRole("link", { name: "現在の条件で CSV ↓" }),
  ).toBeVisible();
  const csv = await request.get(
    "/api/backtests/" + jid + "/trades.csv?period_type=full&search=7203",
  );
  expect(csv.status()).toBe(200);
  expect(await csv.text()).toContain("signal_price");
  const params = await request.get(
    "/api/backtests/" + jid + "/files/parameter_results.csv",
  );
  expect(params.status()).toBe(200);
  await expect(
    page.getByText("取引を読み込み中…", { exact: true }),
  ).toHaveCount(0);
  await page.screenshot({ path: "test-results/trades.png", fullPage: true });
  await page.getByRole("tab", { name: "ヒートマップ" }).click();
  await page.getByRole("button", { name: "ALL", exact: true }).click();
  await page.getByLabel("評価期間").selectOption("train");
  await expect(
    page.getByRole("button", { name: "下落率30% 出来高3倍", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("取引を読み込み中…", { exact: true }),
  ).toHaveCount(0);
  await page.screenshot({ path: "test-results/heatmap.png", fullPage: true });
  await page.getByRole("button", { name: "同じ条件で再実行" }).click();
  await expect(page).not.toHaveURL(new RegExp(jid));
  await expect(
    page.getByRole("tab", { name: "概要", exact: true }),
  ).toBeVisible({ timeout: 180000 });
  await page.goto("/backtests");
  await expect(page.getByRole("heading", { name: "検証履歴" })).toBeVisible();
  await page.goto("/data");
  await expect(
    page.getByRole("heading", { name: "市場データ", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "市場データを更新", exact: true }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
