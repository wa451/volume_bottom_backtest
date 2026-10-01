import type { MarketCapBin } from "@/lib/types";
import { capLabels, marketCapRange } from "@/lib/format";

export function MarketCapLabel({
  group,
  bins,
}: {
  group: string;
  bins: MarketCapBin[];
}) {
  return (
    <span className="cap-label">
      <span>{capLabels[group] || group}</span>
      <small>{marketCapRange(group, bins)}</small>
    </span>
  );
}

export function MarketCapGuide({ bins }: { bins: MarketCapBin[] }) {
  return (
    <div className="market-cap-guide">
      <h3>時価総額の区分（シグナル日当時）</h3>
      <div className="market-cap-bands">
        {bins.map((b) => (
          <MarketCapLabel key={b.name} group={b.name} bins={bins} />
        ))}
      </div>
      <p className="check-note">
        各区分は下限以上・上限未満です。ALLは全規模と時価総額欠損を含み、規模別の集計では欠損を除外します。この結果を実行した際の設定を表示しています。
      </p>
    </div>
  );
}
