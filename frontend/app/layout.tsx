import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
export const metadata: Metadata = {
  title: "底値出来高研究 | Japanese Equity Lab",
  description: "日本株の底値・出来高急増戦略をEvent Studyで検証",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ja">
      <body>
        <aside className="sidebar">
          <Link className="brand" href="/">
            <span className="brand-mark">▥</span>
            <strong>
              底値出来高研究<small>JAPANESE EQUITY LAB</small>
            </strong>
          </Link>
          <div className="nav-label">WORKSPACE</div>
          <nav>
            <Link href="/">◫　Dashboard</Link>
            <Link href="/data">▤　市場データ</Link>
            <Link href="/backtests">◷　検証履歴</Link>
            <Link className="nav-cta" href="/backtest/new">
              ＋　新規バックテスト
            </Link>
          </nav>
          <div className="sidebar-foot">
            252日高値 × 20日平均出来高
            <br />
            <span>EVENT STUDY · V1</span>
          </div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <span>日本株 / 現在上場・国内普通株</span>
            <span className="research-tag">RESEARCH WORKSPACE</span>
          </header>
          <main>{children}</main>
          <footer>
            JPY / 営業日基準 · Trainで候補選択 → Testで検証 ·
            無料データの品質をご確認ください
          </footer>
        </div>
      </body>
    </html>
  );
}
