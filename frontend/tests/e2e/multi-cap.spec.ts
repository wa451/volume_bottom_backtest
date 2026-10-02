import { test, expect } from "@playwright/test";
import type { Job } from "../../lib/types";

test("時価総額を複数選択し、区分ごとのセル詳細・CSVと共通フィルタを表示", async ({
  page,
  request,
}) => {
  const history = await (await request.get("/api/backtests?limit=100")).json();
  const job: Job = history.items.find(
    (j: Job) =>
      j.status === "completed" &&
      j.config.holding_periods.includes(60) &&
      j.config.drawdown_thresholds.includes(0.3) &&
      j.config.volume_ratio_thresholds.includes(3),
  );
  expect(job, "標準条件のバックテストを先に完了してください").toBeTruthy();
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/backtests/" + job.id);
  await page.getByRole("tab", { name: "ヒートマップ", exact: true }).click();
  const group = (name: string) =>
    page.getByRole("region", { name: name + "のヒートマップ", exact: true });
  const cell = "下落率30% 出来高3倍";
  await expect(group("ALL")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "ALL", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Small", exact: true }).click();
  await page.getByRole("button", { name: "Mega", exact: true }).click();
  for (const name of ["ALL", "Small", "Mega"]) {
    await expect(
      page.getByRole("button", { name, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(group(name)).toBeVisible();
  }
  await expect(group("Micro")).toHaveCount(0);
  await page.getByRole("button", { name: "ALL", exact: true }).click();
  await expect(group("ALL")).toHaveCount(0);
  await expect(group("Small")).toContainText("100億円以上〜500億円未満");
  await expect(group("Mega")).toContainText("1兆円以上");

  await group("Small").getByRole("button", { name: cell, exact: true }).click();
  const detail = page.getByRole("region", {
    name: "選択条件の詳細",
    exact: true,
  });
  await expect(detail.locator(".detail-scope")).toContainText("Small");
  const csv = page.getByRole("link", {
    name: "現在の条件で CSV ↓",
    exact: true,
  });
  await expect(csv).toHaveAttribute("href", /market_cap_group=small&/);
  await expect(group("Small").locator("button.selected")).toHaveCount(1);
  await expect(group("Mega").locator("button.selected")).toHaveCount(0);
  await group("Mega").getByRole("button", { name: cell, exact: true }).click();
  await expect(detail.locator(".detail-scope")).toContainText("Mega");
  await expect(csv).toHaveAttribute("href", /market_cap_group=mega&/);
  const exportResponse = await request.get((await csv.getAttribute("href"))!);
  expect(exportResponse.status()).toBe(200);
  expect(await exportResponse.text()).toContain("signal_price");

  await page.getByLabel("保有期間", { exact: true }).selectOption("60");
  await page.getByLabel("評価期間").selectOption("test");
  await page.getByLabel("市場", { exact: true }).selectOption("Prime");
  await page.getByLabel("セルの指標").selectOption("win_rate");
  for (const name of ["Small", "Mega"]) {
    const response = await request.get(
      `/api/backtests/${job.id}/results?period_type=test&holding_period=60&market_segment=Prime&market_cap_group=${name.toLowerCase()}&drawdown_threshold=0.3&volume_ratio_threshold=3`,
    );
    const result = (await response.json()).items[0];
    await expect(
      group(name)
        .getByRole("button", { name: cell, exact: true })
        .locator("small"),
    ).toContainText(result.num_trades + " trades");
  }
  await expect(csv).toHaveAttribute("href", /period_type=test/);
  await expect(csv).toHaveAttribute("href", /holding_period=60/);
  await expect(csv).toHaveAttribute("href", /market_segment=Prime/);
  await page.screenshot({
    path: "test-results/multi-cap-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  const smallBox = await group("Small").boundingBox();
  const megaBox = await group("Mega").boundingBox();
  expect(megaBox!.y).toBeGreaterThan(smallBox!.y + smallBox!.height);
  await page.screenshot({
    path: "test-results/multi-cap-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Mega", exact: true }).click();
  await expect(group("Mega")).toHaveCount(0);
  await expect(detail.locator(".detail-scope")).toContainText("Small");
  await expect(csv).toHaveAttribute("href", /market_cap_group=small&/);
  await expect(
    page.getByRole("button", { name: "Small", exact: true }),
  ).toBeDisabled();
  expect(errors).toEqual([]);
});

test("同じ値は区分が違っても同じ色になり、複数選択をタブ移動後も保持", async ({
  page,
  request,
}) => {
  const history = await (await request.get("/api/backtests?limit=100")).json();
  const job: Job = history.items.find(
    (j: Job) =>
      j.status === "completed" && j.config.drawdown_thresholds.length > 1,
  );
  expect(job).toBeTruthy();
  const [dd, otherDd] = job.config.drawdown_thresholds;
  const vr = job.config.volume_ratio_thresholds[0];
  await page.route("**/api/backtests/*/results?**", async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    data.items = data.items.map(
      (r: {
        market_cap_group: string;
        drawdown_threshold: number;
        mean_return: number;
      }) => ({
        ...r,
        mean_return:
          r.drawdown_threshold === dd
            ? 0.1
            : r.drawdown_threshold === otherDd && r.market_cap_group === "small"
              ? 0.5
              : 0.2,
      }),
    );
    await route.fulfill({ response, json: data });
  });
  await page.goto("/backtests/" + job.id);
  await page.getByRole("tab", { name: "ヒートマップ", exact: true }).click();
  await page.getByRole("button", { name: "Small", exact: true }).click();
  await page.getByRole("button", { name: "Mega", exact: true }).click();
  await page.getByRole("button", { name: "ALL", exact: true }).click();
  const name = "下落率" + Math.round(dd * 100) + "% 出来高" + vr + "倍";
  const small = page
    .getByRole("region", { name: "Smallのヒートマップ", exact: true })
    .getByRole("button", { name, exact: true });
  const mega = page
    .getByRole("region", { name: "Megaのヒートマップ", exact: true })
    .getByRole("button", { name, exact: true });
  await expect(small.locator("strong")).toHaveText("+10.00%");
  await expect(mega.locator("strong")).toHaveText("+10.00%");
  expect(await small.evaluate((el) => el.style.backgroundColor)).toBe(
    await mega.evaluate((el) => el.style.backgroundColor),
  );
  await page.getByRole("tab", { name: "取引一覧", exact: true }).click();
  await page.getByRole("tab", { name: "ヒートマップ", exact: true }).click();
  await expect(small).toBeVisible();
  await expect(mega).toBeVisible();
});
