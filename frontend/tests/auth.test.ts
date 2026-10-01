import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { proxy } from "../proxy";
afterEach(() => vi.unstubAllEnvs());
describe("公開Frontendのアクセス制御", () => {
  it("個人ローカルは認証なし", () => {
    vi.stubEnv("WEB_ENV", "development");
    vi.stubEnv("WEB_ACCESS_PASSWORD", undefined);
    expect(
      proxy(new NextRequest("http://localhost/")).headers.get(
        "x-middleware-next",
      ),
    ).toBe("1");
  });
  it("公開時のパスワード未設定は拒否", () => {
    vi.stubEnv("WEB_ENV", "production");
    vi.stubEnv("WEB_ACCESS_PASSWORD", undefined);
    expect(proxy(new NextRequest("https://app.example/")).status).toBe(503);
  });
  it("不正なBasic認証を拒否", () => {
    vi.stubEnv("WEB_ACCESS_PASSWORD", "test-password");
    const r = proxy(
      new NextRequest("https://app.example/api/backtests", {
        headers: { authorization: "Basic invalid" },
      }),
    );
    expect(r.status).toBe(401);
    expect(r.headers.get("www-authenticate")).toContain("Basic");
  });
  it("正しい認証で画面とAPIを許可", () => {
    vi.stubEnv("WEB_ACCESS_PASSWORD", "test-password");
    const authorization =
      "Basic " + Buffer.from("research:test-password").toString("base64");
    expect(
      proxy(
        new NextRequest("https://app.example/api/backtests", {
          headers: { authorization },
        }),
      ).headers.get("x-middleware-next"),
    ).toBe("1");
  });
});
