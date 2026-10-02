import { test, expect } from "@playwright/test";

for (const mode of ["portfolio", "event_study"]) {
  test(`AI分析: ${mode} 保存済み結果を分析・再利用`, async ({
    page,
    request,
  }) => {
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    const history = await (
      await request.get("/api/backtests?limit=100")
    ).json();
    const job = history.items.find(
      (j: { status: string; summary: { analysis_mode?: string } }) =>
        j.status === "completed" &&
        (mode === "portfolio"
          ? j.summary.analysis_mode === "portfolio"
          : j.summary.analysis_mode !== "portfolio"),
    );
    expect(job).toBeTruthy();
    await page.goto(`/backtests/${job.id}`);
    await page.getByRole("tab", { name: "AI分析", exact: true }).click();
    const panel = page.getByRole("tabpanel", { name: "AI分析", exact: true });
    await expect(
      panel.getByRole("heading", { name: "この判断の理由", exact: true }),
    ).toBeVisible({ timeout: 120000 });
    await expect(
      panel.getByRole("heading", { name: "手法別の最上位候補", exact: true }),
    ).toBeVisible();
    await expect(
      panel.getByRole("heading", {
        name: "時価総額帯別の最上位候補",
        exact: true,
      }),
    ).toBeVisible();
    await expect(
      panel.getByText("1兆円以上", { exact: true }).first(),
    ).toBeVisible();
    const analysis = await (
      await request.get(`/api/backtests/${job.id}/analysis`)
    ).json();
    expect(analysis.status).toBe("completed");
    expect(analysis.report.mode).toBe(mode);
    await expect(
      panel.getByText(analysis.report.conclusion, { exact: true }),
    ).toBeVisible();
    if (analysis.report.status === "insufficient")
      await expect(
        panel.getByText("根拠不足・推奨保留", { exact: true }),
      ).toBeVisible();
    if (analysis.report.generation.provider === "statistical")
      await expect(panel.getByText(/統計ルールによる自動分析/)).toBeVisible();
    const reuse = await (
      await request.post(`/api/backtests/${job.id}/analysis`)
    ).json();
    expect(reuse.job_id).toBe(analysis.job_id);
    await page
      .getByRole("tab", {
        name: mode === "portfolio" ? "結果比較" : "概要",
        exact: true,
      })
      .click();
    await page.getByRole("tab", { name: "AI分析", exact: true }).click();
    await expect(
      panel.getByText(analysis.report.conclusion, { exact: true }),
    ).toBeVisible();
    const after = await (
      await request.get(`/api/backtests/${job.id}/analysis`)
    ).json();
    expect(after.report.generated_at).toBe(analysis.report.generated_at);
    expect(errors).toEqual([]);
    await page.screenshot({
      path: `test-results/ai-analysis-${mode}-preview.png`,
    });
    await page.screenshot({
      path: `test-results/ai-analysis-${mode}.png`,
      fullPage: true,
    });
  });
}
