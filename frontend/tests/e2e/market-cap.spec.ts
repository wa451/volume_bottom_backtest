import { test, expect } from "@playwright/test";

test("時価総額区分の金額帯を既存結果・フィルタ・比較表・設定画面に表示", async ({
  page,
  request,
}) => {
  const history = await (await request.get("/api/backtests?limit=100")).json();
  const job = history.items.find(
    (j: { status: string }) => j.status === "completed",
  );
  expect(job, "先にバックテストを1件完了してください").toBeTruthy();
  await page.goto("/backtests/" + job.id);
  await expect(
    page.getByRole("heading", { name: "時価総額の区分（シグナル日当時）" }),
  ).toBeVisible();
  const guide = page.locator(".market-cap-guide");
  for (const range of [
    "100億円未満",
    "100億円以上〜500億円未満",
    "500億円以上〜1,000億円未満",
    "1,000億円以上〜5,000億円未満",
    "5,000億円以上〜1兆円未満",
    "1兆円以上",
  ])
    await expect(guide.getByText(range, { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "ヒートマップ", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Micro", exact: true }),
  ).toContainText("100億円未満");
  await expect(
    page.getByRole("button", { name: "Small", exact: true }),
  ).toContainText("100億円以上〜500億円未満");
  await expect(
    page.getByRole("button", { name: "Mega", exact: true }),
  ).toContainText("1兆円以上");
  await expect(
    page.getByRole("button", { name: "ALL", exact: true }),
  ).toContainText("全規模（欠損を含む）");
  await expect(
    page.getByRole("button", { name: "下落率30% 出来高3倍", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/market-cap-ranges.png",
    fullPage: true,
  });
  await page.getByRole("tab", { name: "時価総額別", exact: true }).click();
  await expect(
    page.getByRole("cell").filter({ hasText: "Small100億円以上〜500億円未満" }),
  ).toBeVisible();
  await page.goto("/backtest/new");
  await expect(
    page.getByText("100億円以上〜500億円未満", { exact: true }),
  ).toBeVisible();
});
