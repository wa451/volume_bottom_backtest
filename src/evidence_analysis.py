"""Explain frozen backtest aggregates. Selection uses Train only, never Test/FULL."""

import json
import math
from .strategies import REGISTRY

VERSION = "evidence-v3"
METRICS = (
    "num_trades",
    "num_signals",
    "num_tickers",
    "total_return",
    "cagr",
    "max_drawdown",
    "sharpe_ratio",
    "profit_factor",
    "profit_factor_no_losses",
    "profit_factor_infinite",
    "mean_return",
    "median_return",
    "win_rate",
    "ci95_lower",
    "ci95_upper",
    "robustness_score",
    "neighbor_count",
    "open_positions",
    "metrics_valid",
    "top_10_profit_dependency",
)


def finite(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def percent(value):
    return f"{value * 100:+.2f}%" if finite(value) else "欠損"


def cap_range(group, bins):
    if group == "ALL":
        return "全規模（当時時価総額の欠損を含む）"
    b = next((b for b in bins if b["name"] == group), None)
    if not b:
        return "当時時価総額不明／区分未定義"

    def bound(v):
        return f"{v / 1e12:g}兆円" if v >= 1e12 else f"{v / 1e8:g}億円"

    if b["max"] is None:
        return bound(b["min"]) + "以上"
    if b["min"] == 0:
        return bound(b["max"]) + "未満"
    return bound(b["min"]) + "以上〜" + bound(b["max"]) + "未満"


def identity(row, portfolio):
    params = (
        row.get("parameters")
        if portfolio
        else {
            "drawdown_threshold": row["drawdown_threshold"],
            "volume_ratio": row["volume_ratio_threshold"],
            "holding_period": row["holding_period"],
        }
    )
    if isinstance(params, str):
        params = json.loads(params)
    sid = row.get("strategy_id", "bottom_volume")
    pid = row.get("parameter_id") or json.dumps(params, sort_keys=True)
    return (sid, pid, row["market_cap_group"], row["market_segment"]), params


def metric_subset(row):
    return {k: row.get(k) for k in METRICS} if row else None


def build_report(rows, config, summary, source_id):
    portfolio = summary.get("analysis_mode") == "portfolio"
    min_trades = max(1, int(config["validation"]["minimum_trades"]))
    bins = config["market_cap_bins"]
    # Separate scopes overlap; do not sum their trades or pool returns across them.
    indexed = {}
    for row in rows:
        key, _ = identity(row, portfolio)
        indexed[(row["period_type"], key)] = row
    candidates = []
    for row in rows:
        if row["period_type"] != "train":
            continue
        key, params = identity(row, portfolio)
        sid, pid, cap, market = key
        n = row.get("num_trades") or 0
        value = row.get("cagr" if portfolio else "mean_return")
        valid = finite(value) and n > 0
        if portfolio:
            valid = (
                valid
                and row.get("metrics_valid") is True
                and finite(row.get("max_drawdown"))
            )
        blockers = []
        if n < min_trades:
            blockers.append(f"Train取引数{n}件が最低{min_trades}件に未達")
        if not valid:
            blockers.append("有効な取引・評価指標が不足")
        if not finite(value) or value <= 0:
            blockers.append("Train収益が正でない")
        if not portfolio and (
            not finite(row.get("ci95_lower")) or row["ci95_lower"] <= 0
        ):
            blockers.append("Train平均リターンの95%区間下限が正でない／欠損")
        if cap not in ["ALL", *[b["name"] for b in bins]]:
            blockers.append("当時時価総額の帯を特定できない")
        score = (
            (
                value / (0.05 + abs(row["max_drawdown"]))
                if portfolio
                else row.get("ci95_lower")
            )
            if valid
            else None
        )
        if not finite(score):
            score = None
        train = metric_subset(row)
        test = metric_subset(indexed.get(("test", key)))
        candidates.append(
            dict(
                strategy_id=sid,
                strategy_name=REGISTRY[sid].name if sid in REGISTRY else sid,
                parameter_id=pid,
                parameters=params,
                market_cap_group=cap,
                market_cap_range=cap_range(cap, bins),
                market_segment=market,
                train=train,
                test=test,
                score=score,
                eligible=not blockers,
                blockers=blockers,
                evaluable=valid,
            )
        )
    # Positive, sampled, valid Train results first. Deterministic tie breaks only use Train/identity.
    candidates.sort(
        key=lambda x: (
            not x["eligible"],
            not x["evaluable"],
            -(x["score"] if finite(x["score"]) else -1e30),
            -(x["train"].get("num_trades") or 0),
            (
                x["market_cap_group"] == "ALL"
                if x["evaluable"]
                else x["market_cap_group"] != "ALL"
            ),
            x["market_segment"] != "ALL",
            x["strategy_id"],
            x["parameter_id"],
            x["market_cap_group"],
            x["market_segment"],
        )
    )
    selected = next((x for x in candidates if x["eligible"]), None)
    reference = selected or next((x for x in candidates if x["evaluable"]), None)
    reasons, risks = [], []
    status = "insufficient"
    conclusion = (
        "推奨を確定できません。件数・収益・指標の条件を満たすTrain候補がありません。"
    )
    if reference:
        x = reference
        title = f'{x["strategy_name"]} × {x["market_cap_group"]}（{x["market_cap_range"]}）× {x["market_segment"]}'
        reasons.append(
            f'{"Train選択候補" if selected else "参考候補"}は{title}。Train取引数は{x["train"]["num_trades"]}件です。'
        )
        if portfolio:
            reasons.append(
                f'Train CAGR {percent(x["train"]["cagr"])}、最大ドローダウン {percent(x["train"]["max_drawdown"])}。CAGR ÷（5% + 最大下落率の絶対値）で収益と下落リスクを比較し、評価値は{x["score"]:.3f}です。'
            )
        else:
            reasons.append(
                f'Train平均 {percent(x["train"]["mean_return"])}、中央値 {percent(x["train"]["median_return"])}、平均の95%区間 {percent(x["train"]["ci95_lower"])}〜{percent(x["train"]["ci95_upper"])}。区間下限を優先して比較します。'
            )
        pf = x["train"].get("profit_factor")
        pf_text = (
            f"{pf:.2f}"
            if finite(pf)
            else (
                "損失なし（有限値未定義）"
                if (
                    x["train"].get("profit_factor_no_losses")
                    or x["train"].get("profit_factor_infinite")
                )
                else "欠損"
            )
        )
        reasons.append(
            f'Train勝率 {percent(x["train"]["win_rate"])}、PF {pf_text}、中央値 {percent(x["train"]["median_return"])}。勝率やPFの一つだけでは選択していません。'
        )
        if portfolio and (x["train"].get("open_positions") or 0) > 0:
            text = f'Trainに未決済{x["train"]["open_positions"]}件があります。CAGRはその評価損益を含み、勝率・PF・中央値は完了取引だけです。'
            risks.append(text)
            reasons.append(text)
        if not portfolio:
            reasons.append(
                f'Trainの近傍条件は{x["train"].get("neighbor_count") or 0}件、近傍評価値は{x["train"].get("robustness_score")}。近傍がない場合はパラメータの安定性を確認できません。'
            )
        risks.extend(x["blockers"])
        t = x["test"]
        test_value = t.get("cagr" if portfolio else "mean_return") if t else None
        test_ok = bool(
            t
            and (t.get("num_trades") or 0) >= min_trades
            and finite(test_value)
            and test_value > 0
        )
        if portfolio:
            test_ok = test_ok and t.get("metrics_valid") is True
        else:
            test_ok = test_ok and finite(t.get("ci95_lower")) and t["ci95_lower"] > 0
        if t:
            reasons.append(
                f'同じ設定のTestは{t["num_trades"]}件、{"CAGR" if portfolio else "平均リターン"} {percent(test_value)}。Testは選択後の評価にだけ使います。'
            )
        if selected:
            status = "supported" if test_ok else "unconfirmed"
            conclusion = f"この検証内の第一候補は{title}です。" + (
                "同じ設定がTestでも件数・正の収益条件を満たしました。"
                if test_ok
                else "Testでの再現性を確認できず、実運用の推奨は保留です。"
            )
        if not test_ok:
            risks.append(
                "Testの件数・正の収益・有効指標が揃っておらず、再現性は未確認です。"
            )
        p = x["parameters"]
        if (
            x["strategy_id"] == "kenmo_breakout"
            and p.get("mode") == "price_only"
            and not p.get("high_enabled")
            and not p.get("volume_enabled")
        ):
            risks.append(
                "Breakoutの高値更新・出来高条件がともにOFFです。この結果は定期的な買いの検証であり、ブレイクアウト条件の優位性を示しません。"
            )
        if x["strategy_id"].startswith("kenmo_") and p.get("mode") == "price_only":
            risks.append(
                "価格のみモードのため、増収増益・ROE・PERの条件は検証していません。"
            )
        if x["market_cap_group"] == "ALL":
            risks.append(
                "全規模の候補です。特定の時価総額帯が最適とまでは判断できません。"
            )
    # Explain why alternatives did not win; zero-trade rows have no ranking evidence.
    strategy_comparison = [
        next(x for x in candidates if x["strategy_id"] == sid)
        for sid in sorted({x["strategy_id"] for x in candidates})
    ]
    for other in strategy_comparison:
        if reference and other["strategy_id"] == reference["strategy_id"]:
            continue
        label = "CAGR" if portfolio else "平均リターン"
        value = other["train"].get("cagr" if portfolio else "mean_return")
        if not other["evaluable"]:
            explanation = "有効な完了取引・評価指標がなく、優劣を判断できません。"
        elif other["blockers"]:
            explanation = (
                "採用条件を満たしません（" + "、".join(other["blockers"]) + "）。"
            )
        else:
            explanation = "Trainの比較評価値が第一候補を上回らなかったため、優先順位を下げました（同点は表示した決定規則によります）。"
        reasons.append(
            f'{other["strategy_name"]}の比較候補はTrain {other["train"]["num_trades"]}件、{label} {percent(value)}。{explanation}'
        )
        p = other["parameters"]
        if (
            other["strategy_id"] == "kenmo_breakout"
            and p.get("mode") == "price_only"
            and not p.get("high_enabled")
            and not p.get("volume_enabled")
        ):
            risks.append(
                "Breakoutの比較候補は高値更新・出来高条件がともにOFFです。定期的な買いの検証であり、ブレイクアウト条件の優位性を示しません。"
            )
        if other["strategy_id"].startswith("kenmo_") and p.get("mode") == "price_only":
            risks.append(
                "Kenmoの価格のみモードでは、増収増益・ROE・PERの条件は検証していません。"
            )
    reasons.append(
        f'Trainで比較した戦略・条件・規模・市場の組は{len(candidates)}件、採用条件を満たす組は{sum(x["eligible"] for x in candidates)}件です。重複する集計範囲の件数は合算しません。'
    )
    quality = summary.get("quality", {})
    stock_count = quality.get("stock_count", quality.get("universe_count"))
    if stock_count is not None:
        reasons.append(
            f"検証対象は{stock_count}銘柄です。結果の適用範囲はこの保存済みの期間・銘柄・条件に限られます。"
        )
    costs = config.get("cost", {})
    if not any(costs.values()):
        risks.append(
            "売買コスト・スリッページは0設定です。費用を加えた収益を再確認してください。"
        )
    risks.extend(str(x) for x in summary.get("warnings", []))
    risks.append(
        "多数の条件探索と現存銘柄による生存者バイアスがあり、単一のTrain/Test分割では将来の優位性を保証できません。"
    )

    def best_by(field, values):
        return [
            next((x for x in candidates if x[field] == value), None) for value in values
        ]

    # Keep summaries for every strategy/cap, even when the leading comparison is truncated.
    return dict(
        version=VERSION,
        source_job_id=source_id,
        mode="portfolio" if portfolio else "event_study",
        status=status,
        minimum_trades=min_trades,
        conclusion=conclusion,
        reasons=reasons,
        risks=list(dict.fromkeys(risks)),
        next_steps=[
            "対象銘柄と期間を広げ、各Train/Testで最低取引数を確保する。",
            "候補の近傍パラメータと別期間のWalk-forwardで安定性を確認する。",
            "売買コスト・スリッページを設定して同条件を再検証する。",
        ],
        methodology="選択はTrainのみ。Portfolio: 正のCAGR・有効指標・最低取引数を条件にCAGR/(0.05+|MDD|)降順。Event Study: 正の平均・95%区間下限・最低取引数を条件に区間下限降順。同点はTrain件数、具体的な規模帯、全市場、ID順。Test/FULLで再選択しない。スコアは比較のための仮定で、統計的有意性や過学習確率ではない。",
        selected=selected,
        reference=reference,
        comparison=candidates[:20],
        strategy_comparison=strategy_comparison,
        cap_comparison=[
            x
            for x in best_by("market_cap_group", ["ALL", *[b["name"] for b in bins]])
            if x
        ],
        periods={"train": config["train"], "test": config["test"]},
        costs=costs,
        generation={
            "provider": "statistical",
            "label": "統計ルールによる自動分析（生成AI未設定）",
        },
    )
