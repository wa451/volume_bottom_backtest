"use client";
import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api, useApi } from "@/lib/api";
import { Config, Market, MarketCapBin } from "@/lib/types";
import { number } from "@/lib/format";
import { ErrorBox, Empty, Notice } from "@/components/common";
import { MarketCapLabel } from "@/components/market-cap";
type Defaults = {
  config: Config;
  market_cap_bins: MarketCapBin[];
  minimum_trades: number;
};
export default function NewPage() {
  const { data, error } = useApi<Defaults>("defaults");
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">NEW EXPERIMENT</div>
          <h1>新規バックテスト</h1>
          <p className="subtitle">
            保存済みデータから、条件の組み合わせを総当たりします。
          </p>
        </div>
        <Link href="/data">市場データを確認 ↗</Link>
      </div>
      <ErrorBox error={error} />
      {data ? (
        <BacktestForm defaults={data} />
      ) : (
        <Empty>設定を読み込み中…</Empty>
      )}
    </>
  );
}
function Choices<T extends string | number>({
  title,
  options,
  value,
  onChange,
  label,
}: {
  title: string;
  options: T[];
  value: T[];
  onChange: (v: T[]) => void;
  label: (v: T) => string;
}) {
  return (
    <>
      <div className="choice-title">
        <h3>{title}</h3>
        <button
          type="button"
          className="text-button"
          onClick={() => onChange([...options])}
        >
          すべて選択
        </button>
      </div>
      <div className="choices">
        {options.map((x) => (
          <label key={x}>
            <input
              type="checkbox"
              checked={value.includes(x)}
              onChange={(e) =>
                onChange(
                  e.target.checked
                    ? [...value, x]
                    : value.filter((v) => v !== x),
                )
              }
            />
            {label(x)}
          </label>
        ))}
      </div>
    </>
  );
}
function BacktestForm({ defaults }: { defaults: Defaults }) {
  const [c, setC] = useState(defaults.config);
  const [tickerText, setTickerText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef(false);
  const last = useRef({ body: "", key: "" });
  const router = useRouter();
  const market = useApi<Market>("market-data/status");
  const set = <K extends keyof Config>(key: K, value: Config[K]) =>
    setC((v) => ({ ...v, [key]: value }));
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError("");
    const body = JSON.stringify({
      ...c,
      tickers: tickerText.split(/[\s,、]+/).filter(Boolean),
    });
    if (last.current.body !== body)
      last.current = { body, key: crypto.randomUUID() };
    try {
      const j = await api<{ job_id: string }>("backtests", {
        method: "POST",
        headers: { "Idempotency-Key": last.current.key },
        body,
      });
      router.push("/backtests/" + j.job_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      pending.current = false;
      setBusy(false);
    }
  }
  const caps = ["ALL", ...defaults.market_cap_bins.map((b) => b.name)];
  return (
    <form onSubmit={(e) => void submit(e)}>
      <div className="form-layout">
        <div>
          <div className="panel">
            <h2>01　分析期間</h2>
            <div className="form-grid">
              {(
                [
                  "start_date",
                  "end_date",
                  "train_start",
                  "train_end",
                  "test_start",
                  "test_end",
                ] as const
              ).map((key, i) => (
                <label key={key}>
                  {
                    [
                      "分析開始日",
                      "分析終了日",
                      "Train開始",
                      "Train終了",
                      "Test開始",
                      "Test終了",
                    ][i]
                  }
                  <input
                    required
                    type="date"
                    value={c[key]}
                    onChange={(e) => set(key, e.target.value)}
                  />
                </label>
              ))}
            </div>
            <p className="check-note">
              TrainとTestは重複させず、分析期間内に設定してください。252営業日の指標準備期間を内部で確保します。Train終端をまたぐ取引は候補選択から除外します。
            </p>
          </div>
          <div className="panel">
            <h2>02　戦略パラメータ</h2>
            <Choices
              title="52週高値からの下落率"
              options={defaults.config.drawdown_thresholds}
              value={c.drawdown_thresholds}
              onChange={(v) => set("drawdown_thresholds", v)}
              label={(v) => Math.round(v * 100) + "%"}
            />
            <Choices
              title="20日平均に対する出来高倍率"
              options={defaults.config.volume_ratio_thresholds}
              value={c.volume_ratio_thresholds}
              onChange={(v) => set("volume_ratio_thresholds", v)}
              label={(v) => v + "倍"}
            />
            <Choices
              title="保有期間"
              options={defaults.config.holding_periods}
              value={c.holding_periods}
              onChange={(v) => set("holding_periods", v)}
              label={(v) => v + "営業日"}
            />
            <div className="form-grid">
              <label>
                Cooldown（営業日）
                <input
                  type="number"
                  min="0"
                  max="1000"
                  required
                  value={c.cooldown}
                  onChange={(e) => set("cooldown", Number(e.target.value))}
                />
              </label>
            </div>
          </div>
          <div className="panel">
            <h2>03　対象範囲</h2>
            <Choices
              title="市場区分"
              options={["Prime", "Standard", "Growth"]}
              value={c.markets}
              onChange={(v) => set("markets", v)}
              label={(v) => v}
            />
            <div className="choice-title">
              <h3>シグナル日当時の時価総額</h3>
              <button
                type="button"
                className="text-button"
                onClick={() => set("market_cap_groups", ["ALL"])}
              >
                すべて（欠損を含む）
              </button>
            </div>
            <div className="choices">
              {caps.map((x) => (
                <label key={x}>
                  <input
                    type="checkbox"
                    checked={c.market_cap_groups.includes(x)}
                    onChange={(e) =>
                      set(
                        "market_cap_groups",
                        x === "ALL"
                          ? e.target.checked
                            ? ["ALL"]
                            : []
                          : e.target.checked
                            ? [
                                ...c.market_cap_groups.filter(
                                  (v) => v !== "ALL",
                                ),
                                x,
                              ]
                            : c.market_cap_groups.filter((v) => v !== x),
                      )
                    }
                  />
                  <MarketCapLabel group={x} bins={defaults.market_cap_bins} />
                </label>
              ))}
            </div>
            <p className="check-note">
              各区分は下限以上・上限未満です。シグナル日当時の時価総額を使用し、区分指定時は時価総額欠損シグナルを除外します。
            </p>
            <div className="form-grid">
              <label>
                銘柄コード（任意・空欄は全対象）
                <input
                  aria-label="対象銘柄コード"
                  placeholder="7203, 6758, 8306"
                  value={tickerText}
                  onChange={(e) => setTickerText(e.target.value)}
                />
              </label>
            </div>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                setTickerText(
                  (market.data?.items || [])
                    .filter(
                      (x) =>
                        x.price_valid && c.markets.includes(x.market_segment),
                    )
                    .map((x) => x.code)
                    .join(", "),
                )
              }
            >
              価格キャッシュのある銘柄を指定
            </button>
          </div>
          <ErrorBox error={error} />
          <div className="submit-row">
            <button className="primary" type="submit" disabled={busy}>
              {busy ? "ジョブ登録中…" : "バックテストを実行 →"}
            </button>
          </div>
        </div>
        <aside className="panel form-aside">
          <div className="eyebrow">EXPERIMENT SIZE</div>
          <strong>
            {number(
              c.drawdown_thresholds.length * c.volume_ratio_thresholds.length,
            )}{" "}
            <small style={{ fontSize: 13 }}>条件</small>
          </strong>
          <p>
            × {c.holding_periods.length}保有期間
            <br />={" "}
            {number(
              c.drawdown_thresholds.length *
                c.volume_ratio_thresholds.length *
                c.holding_periods.length,
            )}
            評価の組み合わせ
          </p>
          <hr style={{ border: 0, borderTop: "1px solid var(--line)" }} />
          <p>
            価格キャッシュ {number(market.data?.price_success_count)}銘柄
            <br />
            対象マスター {number(market.data?.stock_count)}銘柄
          </p>
          <p>
            最低取引数 {defaults.minimum_trades}件<br />
            95% CI: 銘柄クラスタBootstrap
          </p>
          <p>
            Entry: 翌営業日始値
            <br />
            Exit: N営業日後終値
            <br />
            価格: 配当・分割調整後
          </p>
          <p>
            この操作ではデータを取得しません。未取得銘柄は記録して処理を続けます。
          </p>
        </aside>
      </div>
      <Notice />
    </form>
  );
}
