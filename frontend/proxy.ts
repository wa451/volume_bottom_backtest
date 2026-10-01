import { NextRequest, NextResponse } from "next/server";
import { timingSafeEqual } from "node:crypto";
export function proxy(request: NextRequest) {
  const password = process.env.WEB_ACCESS_PASSWORD;
  if (!password && process.env.WEB_ENV !== "production")
    return NextResponse.next();
  if (!password)
    return new NextResponse("公開用のWEB_ACCESS_PASSWORDを設定してください", {
      status: 503,
    });
  const authorization = request.headers.get("authorization") || "";
  let provided = "";
  if (authorization.startsWith("Basic ")) {
    try {
      provided = Buffer.from(authorization.slice(6), "base64")
        .toString()
        .split(":")
        .slice(1)
        .join(":");
    } catch {
      /* Invalid auth */
    }
  }
  const a = Buffer.from(provided),
    b = Buffer.from(password);
  if (a.length !== b.length || !timingSafeEqual(a, b))
    return new NextResponse("Authentication required", {
      status: 401,
      headers: {
        "WWW-Authenticate": 'Basic realm="Backtest Research", charset="UTF-8"',
      },
    });
  return NextResponse.next();
}
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
