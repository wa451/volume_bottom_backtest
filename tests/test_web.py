from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import shutil
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from src.utils import init_dirs
from src.data_loader import exchange_sessions
from backend.app.settings import Settings
from backend.app.main import create_app
from backend.app.models import Job, Config, Result, TradeArtifact
from backend.app.jobs import claim, touch, LeaseLost
from backend.app.db import utcnow
from backend.worker.main import Worker
from backend.app.market import backup_market, restore_market
from backend.app.storage import Storage


@pytest.fixture
def web(tmp_path, config, monkeypatch):
    init_dirs(tmp_path)
    config["data"].update(start_date="2023-06-01", end_date="2023-07-31")
    config["train"] = {"start": "2023-06-01", "end": "2023-06-30"}
    config["test"] = {"start": "2023-07-01", "end": "2023-07-31"}
    config["strategy"].update(
        rolling_high_days=3,
        volume_average_days=3,
        drawdown_thresholds=[0.2, 0.3],
        volume_ratio_thresholds=[2.0, 3.0],
        holding_periods=[2, 5],
        signal_cooldown_days=2,
    )
    config["validation"]["minimum_trades"] = 1
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config))
    universe = pd.DataFrame(
        [
            {
                "code": code,
                "company_name": name,
                "market_segment": market,
                "sector": "Test",
            }
            for code, name, market in [
                ("7203", "Test Toyota", "Prime"),
                ("6758", "Test Sony", "Prime"),
                ("4477", "Test Growth", "Growth"),
            ]
        ]
    )
    universe.to_csv(tmp_path / "data/universe/universe.csv", index=False)
    idx = exchange_sessions("2023-05-01", "2023-08-31")
    for code in universe.code:
        prices = pd.DataFrame(
            {
                "Open": 100.0,
                "High": 110.0,
                "Low": 90.0,
                "Close": 100.0,
                "Adj Close": 100.0,
                "Volume": 100.0,
                "Dividends": 0.0,
                "Stock Splits": 0.0,
            },
            index=idx,
        )
        for day in ["2023-06-08", "2023-06-29", "2023-07-06"]:
            prices.loc[day, ["Close", "Adj Close"]] = 60.0
            prices.loc[day, "Volume"] = 1000.0
        prices.to_parquet(tmp_path / f"data/market/{code}.T.parquet")
        pd.Series(
            [2e8], index=pd.to_datetime(["2023-05-01"]), name="historical_shares"
        ).to_frame().to_parquet(tmp_path / f"data/shares/{code}.T.parquet")
    c = Settings(
        data_root=tmp_path,
        database_url=f"sqlite:///{tmp_path}/web.sqlite3",
        storage_dir=tmp_path / "objects",
        cache_dir=tmp_path / "artifact-cache",
        config_path=config_path,
        api_token="",
        environment="development",
        storage_backend="local",
    )
    app = create_app(c)
    body = {
        "start_date": "2023-06-01",
        "end_date": "2023-07-31",
        "train_start": "2023-06-01",
        "train_end": "2023-06-30",
        "test_start": "2023-07-01",
        "test_end": "2023-07-31",
        "drawdown_thresholds": [0.2, 0.3],
        "volume_ratio_thresholds": [2, 3],
        "holding_periods": [2, 5],
        "cooldown": 2,
        "markets": ["Prime", "Growth"],
    }

    def no_network(*args, **kwargs):
        raise AssertionError("Backtest attempted network access")

    monkeypatch.setattr("src.downloader.Downloader._request", no_network)
    monkeypatch.setattr("src.universe.fetch", no_network)
    monkeypatch.setattr("src.downloader.yf.Ticker", no_network)
    with TestClient(app) as client:
        yield client, app.state.db, c, body


def test_enqueue_is_immediate_idempotent_and_validated(web):
    client, db, c, body = web
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda _: client.post(
                    "/api/backtests", json=body, headers={"Idempotency-Key": "same"}
                ),
                range(2),
            )
        )
    assert all(r.status_code == 202 for r in responses)
    assert responses[0].json() == responses[1].json()
    job_id = responses[0].json()["job_id"]
    assert client.get("/api/jobs/" + job_id).json()["status"] == "queued"
    assert client.get("/api/backtests/" + job_id + "/results").status_code == 409
    assert (
        client.post(
            "/api/backtests",
            json={**body, "cooldown": 4},
            headers={"Idempotency-Key": "same"},
        ).status_code
        == 409
    )
    for changed in [
        {"drawdown_thresholds": []},
        {"markets": ["Other"]},
        {"train_end": "2023-07-01"},
        {"holding_periods": [0]},
        {"end_date": "2099-01-01"},
        {"market_cap_groups": ["fake"]},
        {"tickers": ["../foo"]},
    ]:
        assert (
            client.post("/api/backtests", json={**body, **changed}).status_code == 422
        )
    assert client.get("/api/backtests").json()["total"] == 1


def test_worker_core_results_csv_pagination_and_rerun_offline(web):
    client, db, c, body = web
    jid = client.post("/api/backtests", json=body).json()["job_id"]
    worker = Worker(c, db)
    worker.import_cache()
    assert client.get("/api/market-data/status").json()["price_success_count"] == 3
    assert worker.run_once()
    job = client.get("/api/jobs/" + jid).json()
    assert job["status"] == "completed", job["error_message"]
    assert job["summary"]["quality"]["boundary_purged"] > 0
    assert job["summary"]["quality"]["market_cap_signal_coverage"] == 1
    assert all(x["period_type"] == "train" for x in job["summary"]["candidates"])
    endpoint = "/api/backtests/" + jid
    train = client.get(endpoint + "/results?holding_period=2").json()
    test = client.get(endpoint + "/results?holding_period=2&period_type=test").json()
    full = client.get(endpoint + "/results?holding_period=2&period_type=full").json()
    assert train["total"] == 4
    assert sum(r["num_trades"] for r in full["items"]) == sum(
        r["num_trades"] for r in train["items"] + test["items"]
    )
    crossed = client.get(
        endpoint + "/results?market_cap_group=small&market_segment=Prime"
    ).json()
    assert crossed["total"] == 8
    page = client.get(endpoint + "/trades?holding_period=2&limit=2").json()
    assert len(page["items"]) == 2 and page["total"] > 2
    assert page["items"][0]["signal_price"] == 60
    assert (
        client.get(endpoint + "/trades?holding_period=2&limit=2&offset=2").json()[
            "items"
        ]
        != page["items"]
    )
    selected = client.get(
        endpoint
        + "/trades?search=Toyota&market_segment=Prime&market_cap_group=small&signal_end=2023-06-10"
    ).json()
    assert selected["total"] == 8
    assert all(x["ticker"] == "7203.T" for x in selected["items"])
    assert (
        client.get(endpoint + "/trades?trade_status=boundary_purged").json()["total"]
        > 0
    )
    assert (
        client.get(endpoint + "/distribution?holding_period=2").json()["count"]
        == page["total"]
    )
    export = client.get(endpoint + "/trades.csv?search=Toyota")
    assert (
        export.status_code == 200
        and "attachment" in export.headers["content-disposition"]
    )
    assert "signal_price" in export.text and "Test Sony" not in export.text
    for name in (
        "parameter_results.csv",
        "market_cap_comparison.csv",
        "data_quality_report.md",
    ):
        assert client.get(endpoint + "/files/" + name).status_code == 200
    assert client.get(endpoint + "/files/config.yaml").status_code == 404
    rerun = client.post(
        endpoint + "/rerun", headers={"Idempotency-Key": "rerun"}
    ).json()["job_id"]
    assert rerun != jid
    with db.session() as s:
        assert s.get(Config, rerun).engine_config == s.get(Config, jid).engine_config
        assert s.get(TradeArtifact, jid).num_rows > 0
    assert worker.run_once()
    assert client.get("/api/jobs/" + rerun).json()["status"] == "completed"
    assert client.get(endpoint + "/results?holding_period=2").json() == train
    assert not worker.run_once()


def test_claim_concurrency_recovery_and_fencing(web):
    client, db, c, body = web
    jid = client.post("/api/backtests", json=body).json()["job_id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: claim(db, 120), range(2)))
    winners = [x for x in claims if x]
    assert len(winners) == 1
    old_owner = winners[0][1]
    with db.session.begin() as s:
        s.get(Job, jid).lease_until = utcnow() - timedelta(seconds=1)
    claimed = claim(db)
    assert claimed[0] == jid and claimed[1] != old_owner
    with pytest.raises(LeaseLost):
        touch(db, jid, old_owner, status="completed")
    touch(db, jid, claimed[1], status="backtesting", processed_items=1, total_items=3)
    assert client.get("/api/jobs/" + jid).json()["attempts"] == 2


def test_failures_and_empty_cache_do_not_trigger_yahoo(web):
    client, db, c, body = web
    shutil.rmtree(c.data_root / "data/market")
    jid = client.post("/api/backtests", json=body).json()["job_id"]
    assert Worker(c, db).run_once()
    job = client.get("/api/jobs/" + jid).json()
    assert job["status"] == "completed", job["error_message"]
    assert job["summary"]["quality"]["price_failure_or_missing_count"] == 3
    assert client.get("/api/backtests/" + jid + "/trades").json()["total"] == 0
    assert client.get("/api/backtests/" + jid + "/distribution").json()["bins"] == []
    assert all(
        x["mean_return"] is None
        for x in client.get("/api/backtests/" + jid + "/results").json()["items"]
    )
    (c.data_root / "data/universe/universe.csv").unlink()
    failed = client.post("/api/backtests", json=body).json()["job_id"]
    assert Worker(c, db).run_once()
    j = client.get("/api/jobs/" + failed).json()
    assert j["status"] == "failed" and "先にデータ更新" in j["error_message"]


def test_auth_production_and_storage_boundary(web):
    client, db, c, body = web
    c.api_token = "test-only-token"
    app = create_app(c)
    with TestClient(app) as protected:
        assert protected.get("/api/backtests").status_code == 401
        assert (
            protected.get(
                "/api/backtests", headers={"Authorization": "Bearer test-only-token"}
            ).status_code
            == 200
        )
    c.environment = "production"
    with pytest.raises(ValueError, match="PostgreSQL"):
        c.validate()
    storage = Storage(c)
    with pytest.raises(ValueError):
        storage.get("../config.yaml")


def test_market_snapshot_and_restore(web):
    client, db, c, body = web
    storage = Storage(c)
    backup_market(c, db, storage)
    price = c.data_root / "data/market/7203.T.parquet"
    original = price.read_bytes()
    price.unlink()
    restore_market(c, db, storage)
    assert price.read_bytes() == original


def test_interrupted_market_restore_can_be_retried(web, monkeypatch):
    client, db, c, body = web
    storage = Storage(c)
    backup_market(c, db, storage)
    price = c.data_root / "data/market/7203.T.parquet"
    original = price.read_bytes()
    price.unlink()
    def interrupted_copy(source, target):
        Path(target).write_bytes(b"partial")
        raise OSError("interrupted copy")
    with monkeypatch.context() as m:
        m.setattr("backend.app.market.shutil.copyfile", interrupted_copy)
        with pytest.raises(OSError, match="interrupted copy"):
            restore_market(c, db, storage)
    assert not price.exists()
    assert not list(price.parent.glob(price.name + ".*.tmp"))
    restore_market(c, db, storage)
    assert price.read_bytes() == original


def test_short_market_restore_is_rejected_and_can_be_retried(web, monkeypatch):
    client, db, c, body = web
    storage = Storage(c)
    backup_market(c, db, storage)
    price = c.data_root / "data/market/7203.T.parquet"
    original = price.read_bytes()
    price.unlink()
    with monkeypatch.context() as m:
        m.setattr("backend.app.market.shutil.copyfile", lambda source, target: Path(target).write_bytes(b"partial"))
        with pytest.raises(ValueError, match="size mismatch"):
            restore_market(c, db, storage)
    assert not price.exists()
    assert not list(price.parent.glob(price.name + ".*.tmp"))
    restore_market(c, db, storage)
    assert price.read_bytes() == original


@pytest.mark.parametrize("bad_shares", ["wrong_columns", "corrupt_parquet"])
def test_bad_shares_preserve_all_results_and_quality_report(web, bad_shares):
    from src.backtest import prepare_features
    from src.utils import load_config

    client, db, c, body = web
    worker = Worker(c, db)
    baseline_id = client.post("/api/backtests", json=body).json()["job_id"]
    assert worker.run_once()
    baseline = client.get("/api/backtests/" + baseline_id + "/trades?search=Toyota").json()
    assert baseline["total"] > 0
    path = c.data_root / "data/shares/7203.T.parquet"
    original = path.read_bytes()
    if bad_shares == "wrong_columns":
        pd.DataFrame({"wrong_column": [2e8]}, index=pd.to_datetime(["2023-05-01"])).to_parquet(path)
    else:
        path.write_bytes(b"broken parquet")
    engine = load_config(c.config_path)
    fresh = prepare_features(c.data_root, "7203.T", engine)
    cached = prepare_features(c.data_root, "7203.T", engine)
    assert fresh.attrs["shares_cache_error"]
    assert cached.attrs["shares_cache_error"] == fresh.attrs["shares_cache_error"]
    jid = client.post("/api/backtests", json=body).json()["job_id"]
    assert worker.run_once()
    job = client.get("/api/jobs/" + jid).json()
    assert job["status"] == "completed", job["error_message"]
    quality = job["summary"]["quality"]
    assert quality["price_success_count"] == 3
    assert quality["shares_success_count"] == 2
    assert quality["shares_cache_error_count"] == 1
    endpoint = "/api/backtests/" + jid
    trades = client.get(endpoint + "/trades?search=Toyota").json()
    assert trades["total"] == baseline["total"]
    assert [x["return"] for x in trades["items"]] == [x["return"] for x in baseline["items"]]
    assert all(x["market_cap"] is None and x["market_cap_missing_reason"] == "invalid_shares_cache" for x in trades["items"])
    assert client.get(endpoint + "/trades?search=Toyota&market_cap_group=small").json()["total"] == 0
    report = client.get(endpoint + "/files/data_quality_report.md")
    assert report.status_code == 200 and "invalid_shares_cache" in report.text
    path.write_bytes(original)
    repaired = prepare_features(c.data_root, "7203.T", engine)
    assert repaired.attrs["shares_cache_error"] == ""
    assert repaired.market_cap.notna().any()


def test_update_is_separate_and_retry_uses_persistent_failures(web, monkeypatch):
    client, db, c, body = web
    calls = []

    def run(self, universe, update=True, retry_failed=False):
        calls.append((universe.ticker.tolist(), retry_failed, sorted(self.failures)))
        self.outcome("7203.T", "price", "failed", "simulated timeout")
        self.outcome("6758.T", "price", "cached")
        return self.status

    monkeypatch.setattr("src.downloader.Downloader.run", run)
    jid = client.post(
        "/api/market-data/update",
        json={"tickers": ["7203", "6758"], "refresh_universe": False},
    ).json()["job_id"]
    assert calls == []
    worker = Worker(c, db)
    assert worker.run_once()
    assert client.get("/api/jobs/" + jid).json()["summary"]["failed"] == 1
    retry = client.post(
        "/api/market-data/update",
        json={"retry_failed": True, "refresh_universe": False},
    ).json()["job_id"]
    assert worker.run_once()
    assert calls[1][1] and ("7203.T", "price") in calls[1][2]
    assert client.get("/api/jobs/" + retry).json()["status"] == "completed"


def test_market_cap_selection_and_infinity_json_are_explicit(web):
    from backend.app.serialization import clean

    client, db, c, body = web
    jid = client.post(
        "/api/backtests", json={**body, "market_cap_groups": ["micro"]}
    ).json()["job_id"]
    assert Worker(c, db).run_once()
    assert (
        client.get("/api/jobs/" + jid).json()["summary"]["quality"][
            "unique_signal_count"
        ]
        == 0
    )
    with db.session.begin() as s:
        s.add(
            Result(
                job_id=jid,
                period_type="train",
                market_cap_group="ALL",
                market_segment="ALL",
                holding_period=20,
                drawdown_threshold=0.4,
                volume_ratio_threshold=5,
                metrics=clean(
                    {
                        "profit_factor": float("inf"),
                        "mean_return": float("nan"),
                        "num_trades": 3,
                    }
                ),
            )
        )
    reply = client.get("/api/backtests/" + jid + "/results?sort=profit_factor")
    assert reply.status_code == 200
    item = reply.json()["items"][0]
    assert item["profit_factor"] is None and item["profit_factor_infinite"] is True
    assert item["mean_return"] is None


def test_supabase_storage_roundtrip_uses_private_server_credentials(web, monkeypatch):
    import httpx
    from contextlib import contextmanager

    client, db, c, body = web
    c.storage_backend = "supabase"
    monkeypatch.setenv("SUPABASE_URL", "https://storage.example.test")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-secret-server-only")
    monkeypatch.setenv("STORAGE_BUCKET", "private-research")
    captured = []

    def upload(request):
        captured.append(request)
        assert request.headers["authorization"] == "Bearer test-secret-server-only"
        assert "/private-research/runs/job/data.parquet" in str(request.url)
        assert request.read() == b"parquet-example"
        return httpx.Response(200, json={"Key": "saved"})

    real_client = httpx.Client
    monkeypatch.setattr(
        "backend.app.storage.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(upload), **kwargs),
    )

    @contextmanager
    def download(method, url, **kwargs):
        assert method == "GET" and "/private-research/" in url
        assert kwargs["headers"]["Authorization"] == "Bearer test-secret-server-only"
        yield httpx.Response(
            200, content=b"parquet-example", request=httpx.Request(method, url)
        )

    monkeypatch.setattr("backend.app.storage.httpx.stream", download)
    storage = Storage(c)
    path = c.data_root / "source.parquet"
    path.write_bytes(b"parquet-example")
    key = storage.put(path, "runs/job/data.parquet")
    assert storage.get(key).read_bytes() == path.read_bytes()
    assert len(captured) == 1
    assert storage.get(key).read_bytes() == path.read_bytes()  # Read the API cache.


def test_s3_storage_adapter_roundtrip(web, monkeypatch):
    client, db, c, body = web
    c.storage_backend = "s3"
    objects = {}

    class FakeS3:
        def upload_file(self, filename, bucket, key):
            objects[(bucket, key)] = Path(filename).read_bytes()

        def download_file(self, bucket, key, filename):
            Path(filename).write_bytes(objects[(bucket, key)])

    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: FakeS3())
    storage = Storage(c)
    source = c.data_root / "source.csv"
    source.write_text("example")
    key = storage.put(source, "runs/job/example.csv")
    assert storage.get(key).read_text() == "example"


def test_existing_result_labels_use_frozen_market_cap_bins(web):
    client, db, c, body = web
    old_id = client.post("/api/backtests", json=body).json()["job_id"]
    saved_bins = client.get("/api/jobs/" + old_id).json()["market_cap_bins"]
    assert saved_bins[0]["max"] == 10000000000
    current = yaml.safe_load(c.config_path.read_text())
    current["market_cap_bins"][0]["max"] = 20000000000
    current["market_cap_bins"][1]["min"] = 20000000000
    c.config_path.write_text(yaml.safe_dump(current))
    with TestClient(create_app(c)) as updated:
        assert (
            updated.get("/api/defaults").json()["market_cap_bins"][0]["max"]
            == 20000000000
        )
        assert (
            updated.get("/api/backtests/" + old_id).json()["market_cap_bins"]
            == saved_bins
        )
        new_id = updated.post("/api/backtests", json=body).json()["job_id"]
        assert (
            updated.get("/api/jobs/" + new_id).json()["market_cap_bins"][0]["max"]
            == 20000000000
        )
        rerun = updated.post("/api/backtests/" + old_id + "/rerun").json()["job_id"]
        assert updated.get("/api/jobs/" + rerun).json()["market_cap_bins"] == saved_bins


def test_kenmo_worker_immutable_artifacts_api_and_comparison(web):
    client, db, settings, body = web
    body.update(strategy_ids=['bottom_volume', 'kenmo_breakout', 'kenmo_growth', 'kenmo_earnings'],
                strategy_params={'kenmo_breakout': {'high_enabled': False, 'volume_enabled': False, 'holding_period': [2]}, 'kenmo_growth': {'cap_min': 5e9, 'cap_max': 3e10, 'holding_period': [2]}})
    response = client.post('/api/backtests', json=body)
    assert response.status_code == 202, response.text
    jid = response.json()['job_id']
    assert client.get(f'/api/backtests/{jid}/strategy-results').status_code == 409
    assert Worker(settings, db).run_once()
    job = client.get('/api/jobs/' + jid).json()
    assert job['status'] == 'completed', job['error_message']
    assert job['summary']['analysis_mode'] == 'portfolio'
    assert job['summary']['parameter_combinations'] == 11
    assert not job['summary']['benchmark_available']
    rows = client.get(f'/api/backtests/{jid}/strategy-results?period_type=train').json()['items']
    assert len(rows) == 11 and {row['strategy_id'] for row in rows} == set(body['strategy_ids'])
    grid = next(row for row in rows if row['strategy_id'] == 'kenmo_breakout')
    assert isinstance(grid['parameters'], dict) and grid['num_trades'] > 0
    query = f"strategy_id={grid['strategy_id']}&parameter_id={grid['parameter_id']}"
    curves = client.get(f'/api/backtests/{jid}/strategy-curves?' + query).json()
    assert curves['total'] > 0 and curves['items'][0]['equity'] > 0
    trades = client.get(f'/api/backtests/{jid}/strategy-trades?' + query).json()
    assert trades['items'] and trades['items'][0]['entry_reason'] and trades['items'][0]['exit_reason']
    assert client.get(f'/api/backtests/{jid}/strategy-trades.csv?' + query).status_code == 200
    assert client.get(f'/api/backtests/{jid}/files/strategy_results.csv').status_code == 200
    assert client.get(f'/api/backtests/{jid}/strategy-results?sort=bad').status_code == 422
    assert client.get(f'/api/backtests/{jid}/strategy-curves').status_code == 422
    assert client.get(f'/api/backtests/{jid}/results').status_code == 409
    assert client.get(f'/api/backtests/{jid}/trades').status_code == 409
    assert client.get(f'/api/backtests/{jid}/strategy-results?period_type=bad').status_code == 422
    # Minimum trade requirement: empty financial coverage cannot become a candidate.
    earnings = [row for row in rows if row['strategy_id'] == 'kenmo_earnings']
    assert earnings[0]['num_trades'] == 0 and not earnings[0]['train_selected']
    with db.session() as session:
        frozen = session.get(Config, jid).engine_config
        assert frozen['strategy_ids'] == body['strategy_ids']
        assert session.get(TradeArtifact, jid).num_rows > 0
    rerun = client.post('/api/backtests/' + jid + '/rerun').json()['job_id']
    with db.session() as session:
        assert session.get(Config, rerun).engine_config == frozen


def test_kenmo_request_validation_and_financial_defaults(web):
    client, db, settings, body = web
    body.update(strategy_ids=['kenmo_earnings'])
    response = client.post('/api/backtests', json=body)
    assert response.status_code == 202
    with db.session() as session:
        from src.strategy_config import parameter_grid
        grid = parameter_grid(session.get(Config, response.json()['job_id']).engine_config)
        assert grid[0]['parameters']['volume_ratio'] == 2
    body['strategy_ids'] = ['bad']
    assert client.post('/api/backtests', json=body).status_code == 422
    body['strategy_ids'] = ['kenmo_breakout']
    body['strategy_params'] = {'kenmo_breakout': {'mode': 'fundamentals', 'high_period': [120, 180, 252], 'volume_ratio': [1, 1.5, 2], 'revenue_growth': [.05, .1, .2], 'earnings_growth': [.1, .2, .3], 'roe': [.08, .1, .15], 'stop_loss': [.05, .08, .1, .15]}}
    assert client.post('/api/backtests', json=body).status_code == 422


def test_kenmo_train_selection_does_not_change_when_test_prices_change(web):
    client, db, settings, body = web
    body.update(strategy_ids=['kenmo_breakout'], strategy_params={'kenmo_breakout': {'high_enabled': False, 'volume_enabled': False, 'holding_period': [2, 5]}}, tickers=['7203'])
    first = client.post('/api/backtests', json=body).json()['job_id']
    assert Worker(settings, db).run_once()
    original = client.get(f'/api/backtests/{first}/strategy-results?period_type=train').json()['items']
    path = settings.data_root / 'data/market/7203.T.parquet'
    prices = pd.read_parquet(path)
    after_boundary = prices.index >= pd.Timestamp('2023-07-01')
    for col in ['Open', 'High', 'Low', 'Close', 'Adj Close']:
        prices.loc[after_boundary, col] *= 3
    # Even a future missing monitoring bar cannot invalidate an earlier Train.
    prices.loc['2023-07-07', 'Low'] = float('nan')
    prices.to_parquet(path)
    second = client.post('/api/backtests', json=body).json()['job_id']
    assert Worker(settings, db).run_once()
    revised = client.get(f'/api/backtests/{second}/strategy-results?period_type=train').json()['items']
    assert original == revised
