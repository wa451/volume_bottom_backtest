from copy import deepcopy
import json
import httpx
import pytest
from src.evidence_analysis import build_report
from backend.app.analysis import add_ai_commentary
from backend.app.settings import Settings


def row(period="train", sid="bottom_volume", pid="a", cap="small", **metrics):
    return (
        dict(
            period_type=period,
            strategy_id=sid,
            parameter_id=pid,
            parameters=json.dumps({"holding_period": 20}),
            market_cap_group=cap,
            market_segment="ALL",
            num_trades=100,
            cagr=0.2,
            max_drawdown=-0.1,
            metrics_valid=True,
        )
        | metrics
    )


def report(rows, config):
    return build_report(rows, config, {"analysis_mode": "portfolio"}, "source")


def test_selection_never_uses_test_or_full(config):
    rows = [
        row(pid="a"),
        row(pid="b", cagr=0.1),
        row("test", pid="a", cagr=-0.5),
        row("test", pid="b", cagr=10),
        row("full", pid="b", cagr=50),
    ]
    result = report(rows, config)
    assert result["selected"]["parameter_id"] == "a"
    assert result["status"] == "unconfirmed"
    rows[2]["cagr"] = 3
    rows[3]["cagr"] = -5
    assert report(rows, config)["selected"]["parameter_id"] == "a"
    assert report(rows, config)["status"] == "supported"


def test_risk_adjustment_and_cap_bounds(config):
    rows = [
        row(pid="risky", cagr=0.5, max_drawdown=-0.6),
        row(pid="stable", cagr=0.2, max_drawdown=-0.05),
    ]
    result = report(rows, config)
    assert result["selected"]["parameter_id"] == "stable"
    assert result["selected"]["market_cap_range"] == "100億円以上〜500億円未満"


@pytest.mark.parametrize(
    "metrics",
    [
        {"num_trades": 1},
        {"metrics_valid": False},
        {"cagr": float("nan")},
        {"num_trades": 0},
        {"cagr": 0},
    ],
)
def test_insufficient_or_invalid_cannot_be_recommended(config, metrics):
    x = row()
    x.update(metrics)
    result = report([x], config)
    assert result["selected"] is None
    assert result["status"] == "insufficient"
    assert "推奨を確定できません" in result["conclusion"]


def test_missing_test_and_disabled_breakout_are_explained(config):
    x = row(sid="kenmo_breakout")
    x["parameters"] = json.dumps(
        {"mode": "price_only", "high_enabled": False, "volume_enabled": False}
    )
    result = report([x], config)
    assert result["status"] == "unconfirmed"
    assert any("定期的な買い" in text for text in result["risks"])
    assert any("売買コスト" in text for text in result["risks"]) is (
        not any(config["cost"].values())
    )


def test_event_study_uses_confidence_not_portfolio_metrics(config):
    def event(period, dd, mean, lower):
        return dict(
            period_type=period,
            market_cap_group="micro",
            market_segment="ALL",
            drawdown_threshold=dd,
            volume_ratio_threshold=2,
            holding_period=20,
            mean_return=mean,
            median_return=0.02,
            ci95_lower=lower,
            ci95_upper=0.2,
            num_trades=100,
            num_tickers=20,
        )

    rows = [
        event("train", 0.2, 0.2, -0.01),
        event("train", 0.3, 0.1, 0.02),
        event("test", 0.3, 0.15, 0.01),
    ]
    result = build_report(rows, config, {}, "legacy")
    assert result["selected"]["parameters"]["drawdown_threshold"] == 0.3
    assert result["status"] == "supported"
    assert result["selected"]["train"]["cagr"] is None
    assert all("CAGR" not in text for text in result["reasons"])


def test_scope_rows_are_not_pooled(config):
    rows = [row(cap="ALL", num_trades=60), row(cap="small", num_trades=60)]
    result = report(rows, config)
    assert result["selected"] is None
    assert result["reference"]["train"]["num_trades"] == 60
    assert result["reference"]["market_cap_group"] == "small"


def test_unknown_cap_is_not_recommended(config):
    assert report([row(cap="missing")], config)["selected"] is None


def test_no_key_does_not_use_network(config, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network")

    monkeypatch.setattr(httpx.Client, "post", forbidden)
    r = report([row()], config)
    assert (
        add_ai_commentary(r, Settings(openai_api_key=""), {"provider": "statistical"})[
            "generation"
        ]["provider"]
        == "statistical"
    )


def test_ai_output_is_bounded_and_does_not_change_selection(config, monkeypatch):
    captured = {}

    def post(self, url, **kwargs):
        captured.update(kwargs["json"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "interpretation": ["理由"],
                                        "caveats": ["制約"],
                                        "next_steps": ["次の検証"],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx.Client, "post", post)
    r = report([row()], config)
    selected = deepcopy(r["selected"])
    add_ai_commentary(
        r,
        Settings(openai_api_key="test-secret"),
        {"provider": "openai", "model": "test-model"},
    )
    assert r["selected"] == selected
    assert r["generation"]["provider"] == "openai"
    assert captured["store"] is False
    assert "test-secret" not in captured["input"]
    assert captured["text"]["format"]["strict"] is True


@pytest.mark.parametrize("mode", ["failure", "refusal", "truncated", "invalid"])
def test_ai_failures_fall_back_without_secrets(config, monkeypatch, mode):
    def post(self, url, **kwargs):
        if mode == "failure":
            raise httpx.ReadTimeout("test-secret")
        body = {
            "status": "incomplete" if mode == "truncated" else "completed",
            "output": [],
        }
        if mode == "invalid":
            body["output"] = [
                {"type": "message", "content": [{"type": "output_text", "text": "[]"}]}
            ]
        return httpx.Response(200, request=httpx.Request("POST", url), json=body)

    monkeypatch.setattr(httpx.Client, "post", post)
    r = add_ai_commentary(
        report([row()], config),
        Settings(openai_api_key="test-secret"),
        {"provider": "openai", "model": "test-model"},
    )
    assert r["generation"]["provider"] == "statistical"
    assert "test-secret" not in json.dumps(r)


def test_zero_trade_strategy_has_no_arbitrary_cap_recommendation(config):
    result = report(
        [row(cap="small", num_trades=0), row(cap="ALL", num_trades=0)], config
    )
    assert result["selected"] is None and result["reference"] is None
    assert result["strategy_comparison"][0]["market_cap_group"] == "ALL"
    assert any("優劣を判断できません" in x for x in result["reasons"])


def test_alternatives_and_open_positions_are_explained(config):
    result = report(
        [row(open_positions=3), row(sid="kenmo_breakout", cagr=-0.2)], config
    )
    assert any("評価損益" in x for x in result["reasons"])
    assert any(
        "Kenmo Breakout" in x and "採用条件を満たしません" in x
        for x in result["reasons"]
    )
