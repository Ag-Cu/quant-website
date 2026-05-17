from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
from backend.main import ENDPOINTS, app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def assert_api_payload(payload: dict) -> None:
    assert isinstance(payload.get("meta"), dict)
    assert isinstance(payload.get("data"), dict)


def test_health_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert_api_payload(payload)
    endpoints = payload["data"].get("endpoints")
    assert isinstance(endpoints, list)
    assert {item["path"] for item in endpoints} >= {
        path for path in ENDPOINTS if path != "/api/v1/overview"
    }


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/index.html",
        "/etf.html",
        "/crypto.html",
        "/small-cap.html",
        "/breadth.html",
        "/sentiment.html",
        "/macro.html",
        "/watchlist.html",
        "/picks.html",
        "/holdings.html",
        "/performance.html",
        "/strategy.html",
        "/styles.css",
        "/src/app.js",
    ],
)
def test_static_pages_and_assets_are_served(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("path", sorted(ENDPOINTS))
def test_endpoints_return_meta_and_data(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert_api_payload(response.json())


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("post", "/api/v1/watchlist", {"symbol": "600519", "market_region": "cn"}),
        ("delete", "/api/v1/watchlist/600519?market=cn", None),
        ("post", "/api/v1/portfolio/holdings/600519/mark", {"mark": "reviewed"}),
        ("post", "/api/v1/portfolio/personal-holdings", {"symbol": "600519", "market_value": 10000}),
        ("post", "/api/v1/strategies/etf/signals/600519/confirm", {"action": "confirm"}),
        ("post", "/api/v1/quant/strategies", {"id": "new-alpha", "name": "新策略 Alpha"}),
        ("post", "/api/v1/quant/strategies/new-alpha/snapshot", {"strategy_id": "new-alpha"}),
        ("post", "/api/v1/quant/strategies/joinquant-wufu-etf-v43/events", {"events": []}),
        ("post", "/api/v1/strategies/picks/export", {}),
        ("post", "/api/v1/portfolio/rebalance-records", {"symbol": "600519"}),
    ],
)
def test_action_endpoints_reject_missing_token(
    monkeypatch: pytest.MonkeyPatch,
    client: TestClient,
    method: str,
    path: str,
    json_body: dict | None,
) -> None:
    monkeypatch.setenv("QUANT_ACTION_TOKEN", "test-action-token")
    request = getattr(client, method)
    response = request(path, json=json_body) if json_body is not None else request(path)
    assert response.status_code == 403


def test_joinquant_webhook_rejects_missing_token(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("JOINQUANT_WEBHOOK_TOKEN", "test-joinquant-token")
    response = client.post("/api/v1/joinquant/signals", json={"data": {}})
    assert response.status_code == 401


def test_joinquant_webhook_routes_small_cap_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    monkeypatch.setenv("JOINQUANT_WEBHOOK_TOKEN", "test-joinquant-token")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    storage_path = tmp_path / "data/backend/strategies/small-cap.json"
    signal_log_path = tmp_path / "data/backend/strategies/joinquant-signals.jsonl"
    full_log_path = tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl"
    monkeypatch.setattr(backend_main, "SMALL_CAP_STRATEGY_PATH", storage_path)
    monkeypatch.setattr(backend_main, "JOINQUANT_SIGNAL_LOG_PATH", signal_log_path)
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", full_log_path)

    response = client.post(
        "/api/v1/joinquant/signals",
        headers={"X-Webhook-Token": "test-joinquant-token"},
        json={
            "strategy_id": "small-cap-momentum",
            "strategy_name": "涨停基因小市值轮动V2.2",
            "trade_date": "2026-05-15",
            "run_id": "jq-small-cap-test",
            "signals": [{"symbol": "300476.XSHE", "name": "胜宏科技", "signal": "buy", "score": 90}],
            "logs": [{"time": "2026-05-15 10:30:00", "stage": "weekly_buy", "message": "买入执行完成"}],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["storage_path"] == "data/backend/strategies/small-cap.json"
    assert payload["data"]["strategy"]["id"] == "small-cap-momentum"
    assert payload["data"]["signals"][0]["symbol"] == "300476"
    assert payload["data"]["logs"][0]["strategy_id"] == "small-cap-momentum"
    assert storage_path.exists()
    assert signal_log_path.exists()
    assert full_log_path.exists()


def test_small_cap_endpoint_hides_seed_signals_until_joinquant_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    small_cap_path = tmp_path / "data/backend/strategies/small-cap.json"
    small_cap_path.parent.mkdir(parents=True)
    small_cap_path.write_text(
        """
        {
          "meta": {"version": "1.0", "source": "live", "as_of": "2026-05-12T14:56:00+08:00", "trade_date": "2026-05-12", "timezone": "Asia/Hong_Kong", "market_session": "open", "run_id": "backend-small-20260512-1456"},
          "data": {
            "strategy": {"id": "small-cap-momentum", "name": "小盘股动量", "status": "running"},
            "summary": {"signal_count": 4, "buy_count": 2, "hold_count": 4},
            "signals": [{"symbol": "300476", "name": "胜宏科技", "signal": "buy"}, {"symbol": "002281", "name": "光迅科技", "signal": "buy"}, {"symbol": "688256", "name": "寒武纪-U", "signal": "watch"}, {"symbol": "603893", "name": "瑞芯微", "signal": "reduce"}],
            "holdings": [{"symbol": "002463", "name": "沪电股份"}],
            "themes": [],
            "risk": {},
            "events": [],
            "logs": []
          }
        }
        """,
        encoding="utf-8",
    )
    full_log_path = tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl"
    full_log_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "SMALL_CAP_STRATEGY_PATH", small_cap_path)
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", full_log_path)

    response = client.get("/api/v1/strategies/small-cap")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["source"] == "joinquant-pending"
    assert payload["data"]["signals"] == []
    assert payload["data"]["holdings"] == []
    assert payload["data"]["ignored_seed_signal_count"] == 4


def test_quant_strategy_can_be_created_and_receive_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    monkeypatch.setenv("QUANT_ACTION_TOKEN", "test-action-token")
    monkeypatch.setenv("JOINQUANT_WEBHOOK_TOKEN", "test-joinquant-token")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "CUSTOM_STRATEGY_DIR", tmp_path / "data/backend/strategies/custom")
    monkeypatch.setattr(backend_main, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(backend_main, "STRATEGY_CONFIG_PATH", tmp_path / "data/config/strategies.json")
    monkeypatch.setattr(backend_main, "ACTION_LOG_PATH", tmp_path / "data/backend/actions/action-log.jsonl")
    monkeypatch.setattr(backend_main, "JOINQUANT_SIGNAL_LOG_PATH", tmp_path / "data/backend/strategies/joinquant-signals.jsonl")
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl")
    monkeypatch.setattr(backend_main, "PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH", tmp_path / "data/backend/performance/joinquant-snapshots.jsonl")
    monkeypatch.setattr(backend_main, "PERFORMANCE_JOINQUANT_NAV_PATH", tmp_path / "data/backend/performance/joinquant-nav.jsonl")

    response = client.post(
        "/api/v1/quant/strategies",
        headers={"X-Action-Token": "test-action-token"},
        json={"id": "new-alpha", "name": "新策略 Alpha", "category": "stock", "description": "网页创建"},
    )

    assert response.status_code == 200, response.text
    created = response.json()["data"]["strategy"]
    assert created["id"] == "new-alpha"
    assert (tmp_path / "data/config/strategies.json").exists()
    assert (tmp_path / "data/backend/strategies/custom/new-alpha.json").exists()

    response = client.post(
        "/api/v1/quant/strategies/new-alpha/snapshot",
        headers={"X-Action-Token": "test-action-token", "X-Webhook-Token": "test-joinquant-token"},
        json={
            "trade_date": "2026-05-16",
            "as_of": "2026-05-16T10:30:00+08:00",
            "run_id": "jq-new-alpha-20260516-103000",
            "portfolio": {"total_value": 100000, "cash": 30000},
            "signals": [{"symbol": "300476.XSHE", "name": "胜宏科技", "signal": "buy", "score": 88}],
            "holdings": [{"symbol": "300476.XSHE", "name": "胜宏科技", "quantity": 1000, "last_price": 42, "market_value": 42000, "weight_pct": 42}],
            "logs": [{"time": "2026-05-16 10:30:00", "stage": "snapshot", "message": "策略快照"}],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["strategy"]["id"] == "new-alpha"
    assert payload["data"]["signals"][0]["symbol"] == "300476"

    response = client.get("/api/v1/quant/strategies/new-alpha")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["data"]["registry"]["holding_count"] == 1
    assert detail["data"]["holdings_url"].endswith("strategy_id=new-alpha")

    response = client.get("/api/v1/performance?strategy=new-alpha&benchmark=none")
    assert response.status_code == 200, response.text
    performance_payload = response.json()
    performance_ids = {item["id"] for item in performance_payload["data"]["strategies"]}
    assert "new-alpha" in performance_ids
    assert performance_payload["data"]["strategy"] == "new-alpha"
    assert performance_payload["data"]["strategy_label"] == "新策略 Alpha"

    response = client.post(
        "/api/v1/joinquant/signals",
        headers={"X-Action-Token": "test-action-token", "X-Webhook-Token": "test-joinquant-token"},
        json={
            "strategy_id": "new-alpha",
            "strategy_name": "新策略 Alpha",
            "trade_date": "2026-05-16",
            "run_id": "jq-new-alpha-legacy",
            "holdings": [{"symbol": "300476.XSHE", "name": "胜宏科技", "market_value": 43000}],
        },
    )

    assert response.status_code == 200, response.text
    legacy_payload = response.json()
    assert legacy_payload["data"]["strategy"]["id"] == "new-alpha"
    assert legacy_payload["data"]["holdings"][0]["market_value"] == 43000


def test_portfolio_holdings_include_joinquant_strategy_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    holdings_path = tmp_path / "data/backend/portfolio/holdings.json"
    small_cap_path = tmp_path / "data/backend/strategies/small-cap.json"
    etf_path = tmp_path / "data/backend/strategies/etf.json"
    full_log_path = tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl"
    holdings_path.parent.mkdir(parents=True)
    small_cap_path.parent.mkdir(parents=True)
    holdings_path.write_text(
        """
        {
          "meta": {"version": "1.0", "source": "test", "as_of": "2026-05-15T10:31:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "open", "run_id": "holdings-test"},
          "data": {
            "summary": {"total_market_value": 100000, "position_count": 1},
            "holdings": [{"symbol": "000001", "name": "静态假持仓", "strategy_id": "manual", "avg_cost": 10.0, "last_price": 10.0, "quantity": 1000, "market_value": 10000, "pnl_amount": 0, "pnl_pct": 0, "weight_pct": 10, "holding_days": 3}],
            "allocation": []
          }
        }
        """,
        encoding="utf-8",
    )
    small_cap_path.write_text(
        """
        {
          "meta": {"version": "1.0", "source": "joinquant", "as_of": "2026-05-15T10:30:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "open", "run_id": "small-cap-test"},
          "data": {
            "strategy": {"id": "small-cap-momentum", "name": "涨停基因小市值轮动", "status": "running"},
            "summary": {},
            "signals": [{"symbol": "300476.XSHE", "name": "胜宏科技", "signal": "sell", "signal_label": "卖出", "score": 80, "suggested_range": "开板卖出"}],
            "holdings": [{"symbol": "300476.XSHE", "name": "胜宏科技", "cost": 42.0, "last_price": 43.0, "quantity": 1000, "market_value": 43000, "pnl_amount": 1000, "pnl_pct": 2.38, "weight_pct": 43, "holding_days": 3}],
            "themes": [],
            "risk": {},
            "events": [],
            "logs": [{"time": "2026-05-15 10:29:00", "level": "warning", "message": "胜宏科技 300476.XSHE 涨停打开，卖出"}]
          }
        }
        """,
        encoding="utf-8",
    )
    etf_path.write_text(
        """
        {
          "meta": {"version": "1.0", "source": "joinquant", "as_of": "2026-05-15T10:30:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "open", "run_id": "etf-test"},
          "data": {"strategy": {"id": "joinquant-wufu-etf-v43", "name": "五福 ETF"}, "summary": {}, "recommendations": [{"symbol": "159915.XSHE", "name": "创业板ETF", "action": "buy"}], "holdings": [], "regime": {}, "events": [], "logs": []}
        }
        """,
        encoding="utf-8",
    )
    full_log_path.write_text("", encoding="utf-8")

    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "SMALL_CAP_STRATEGY_PATH", small_cap_path)
    monkeypatch.setattr(backend_main, "ETF_STRATEGY_PATH", etf_path)
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", full_log_path)

    response = client.get("/api/v1/portfolio/holdings")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert [row["symbol"] for row in payload["data"]["holdings"]] == ["000001"]
    assert [row["symbol"] for row in payload["data"]["personal_holdings"]] == ["000001"]
    assert "strategy_id" not in payload["data"]["personal_holdings"][0]
    assert payload["data"]["personal_holdings"][0]["portfolio_type"] == "personal"
    assert payload["data"]["quant_holdings"] == []
    assert payload["data"]["source"] == "joinquant-pending"
    assert payload["data"]["static_holdings_ignored_count"] == 1
    assert payload["data"]["summary"]["position_count"] == 1
    assert payload["data"]["quant_summary"]["position_count"] == 0

    small_cap_path.write_text(small_cap_path.read_text(encoding="utf-8").replace("small-cap-test", "jq-small-cap-20260515-103000"), encoding="utf-8")
    etf_path.write_text(etf_path.read_text(encoding="utf-8").replace("etf-test", "jq-wufu-20260515-103000"), encoding="utf-8")

    response = client.get("/api/v1/portfolio/holdings")

    assert response.status_code == 200, response.text
    payload = response.json()
    holding = next(row for row in payload["data"]["quant_holdings"] if row["symbol"] == "300476")
    assert {item["symbol"] for item in payload["data"]["quant_holdings"]} == {"300476", "159915"}
    assert [item["symbol"] for item in payload["data"]["personal_holdings"]] == ["000001"]
    assert payload["data"]["source"] == "joinquant"
    assert payload["data"]["quant_summary"]["position_count"] == 2
    assert payload["data"]["quant_summary"]["total_market_value"] == 43000
    grouped = {item["strategy_id"]: item for item in payload["data"]["quant_by_strategy"]}
    assert set(grouped) == {"small-cap-momentum", "joinquant-wufu-etf-v43"}
    assert grouped["small-cap-momentum"]["holding_count"] == 1
    assert grouped["small-cap-momentum"]["signal_count"] == 1
    assert grouped["joinquant-wufu-etf-v43"]["holding_count"] == 1
    assert holding["strategy_signals"][0]["strategy_id"] == "small-cap-momentum"
    assert holding["strategy_signals"][0]["action"] == "sell"
    assert holding["quantity"] == 1000
    assert holding["exit_alerts"]
    etf_target = next(row for row in payload["data"]["quant_holdings"] if row["symbol"] == "159915")
    assert etf_target["portfolio_state"] == "target"
    assert etf_target["strategy_id"] == "joinquant-wufu-etf-v43"
    assert etf_target["target_weight_pct"] == 0
    assert payload["data"]["strategy_outputs"]["signals"][0]["symbol"] in {"300476", "159915"}
    assert any(alert["symbol"] == "300476" for alert in payload["data"]["strategy_outputs"]["sell_alerts"])

    response = client.get("/api/v1/portfolio/holdings?type=quant&strategy_id=small-cap-momentum")

    assert response.status_code == 200, response.text
    filtered = response.json()["data"]
    assert [item["strategy_id"] for item in filtered["quant_by_strategy"]] == ["small-cap-momentum"]
    assert {item["symbol"] for item in filtered["quant_holdings"]} == {"300476"}


def test_watchlist_can_create_personal_holding(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    monkeypatch.setenv("QUANT_ACTION_TOKEN", "test-action-token")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(backend_main, "WATCHLIST_CONFIG_PATH", tmp_path / "data/config/watchlist.json")
    monkeypatch.setattr(backend_main, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(backend_main, "ACTION_LOG_PATH", tmp_path / "data/backend/actions/action-log.jsonl")
    monkeypatch.setattr(backend_main, "run_live_data_refresh", lambda: (False, "offline in test"))

    response = client.post(
        "/api/v1/watchlist",
        headers={"X-Action-Token": "test-action-token"},
        json={
            "symbol": "600519",
            "market_region": "cn",
            "name": "贵州茅台",
            "sector": "消费",
            "is_personal_holding": True,
            "personal_amount": 12345,
            "quantity": 10,
        },
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["data"]["personal_holding"]["symbol"] == "600519"
    holdings_path = tmp_path / "data/backend/portfolio/holdings.json"
    saved = json.loads(holdings_path.read_text(encoding="utf-8"))
    assert saved["data"]["holdings"][0]["portfolio_type"] == "personal"
    assert saved["data"]["holdings"][0]["market_value"] == 12345
    assert "strategy_id" not in saved["data"]["holdings"][0]


def patch_joinquant_paths(monkeypatch: pytest.MonkeyPatch, tmp_path) -> dict[str, object]:
    paths = {
        "small_cap": tmp_path / "data/backend/strategies/small-cap.json",
        "etf": tmp_path / "data/backend/strategies/etf.json",
        "performance_nav": tmp_path / "data/backend/performance/net-values.json",
        "signal_log": tmp_path / "data/backend/strategies/joinquant-signals.jsonl",
        "full_log": tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl",
        "snapshots": tmp_path / "data/backend/performance/joinquant-snapshots.jsonl",
        "ledger": tmp_path / "data/backend/performance/joinquant-nav.jsonl",
        "benchmarks": tmp_path / "data/backend/performance/benchmarks-live.json",
        "events": tmp_path / "data/backend/performance/strategy-events.jsonl",
        "prices": tmp_path / "data/backend/performance/price-cache.json",
        "actions": tmp_path / "data/backend/actions/action-log.jsonl",
    }
    monkeypatch.setenv("JOINQUANT_WEBHOOK_TOKEN", "test-joinquant-token")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "SMALL_CAP_STRATEGY_PATH", paths["small_cap"])
    monkeypatch.setattr(backend_main, "ETF_STRATEGY_PATH", paths["etf"])
    monkeypatch.setattr(backend_main, "JOINQUANT_SIGNAL_LOG_PATH", paths["signal_log"])
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", paths["full_log"])
    monkeypatch.setattr(backend_main, "PERFORMANCE_NAV_PATH", paths["performance_nav"])
    monkeypatch.setattr(backend_main, "PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH", paths["snapshots"])
    monkeypatch.setattr(backend_main, "PERFORMANCE_JOINQUANT_NAV_PATH", paths["ledger"])
    monkeypatch.setattr(backend_main, "PERFORMANCE_BENCHMARK_NAV_PATH", paths["benchmarks"])
    monkeypatch.setattr(backend_main, "PERFORMANCE_EVENTS_PATH", paths["events"])
    monkeypatch.setattr(backend_main, "PERFORMANCE_PRICE_CACHE_PATH", paths["prices"])
    monkeypatch.setattr(backend_main, "ACTION_LOG_PATH", paths["actions"])
    monkeypatch.setattr(backend_main, "PERFORMANCE_STALE_SECONDS", 10_000_000)
    monkeypatch.setattr(backend_main, "BENCHMARK_CACHE_SECONDS", 10_000_000)
    paths["full_log"].parent.mkdir(parents=True, exist_ok=True)
    paths["full_log"].write_text("", encoding="utf-8")
    return paths


def write_live_benchmark_cache(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "eastmoney", "as_of": "2026-05-15T10:30:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "open", "run_id": "benchmark-test"},
                "data": {
                    "benchmarks": {
                        "CSI300": {"id": "CSI300", "label": "沪深300", "source": "eastmoney", "source_name": "东方财富行情中心", "as_of": "2026-05-15T10:30:00+08:00", "trade_date": "2026-05-15", "stale_seconds": 10, "status": "live", "nav": [{"date": "2026-05-14", "value": 1000}, {"date": "2026-05-15", "value": 1006}]},
                        "CSI1000": {"id": "CSI1000", "label": "中证1000", "source": "eastmoney", "source_name": "东方财富行情中心", "as_of": "2026-05-15T10:30:00+08:00", "trade_date": "2026-05-15", "stale_seconds": 10, "status": "live", "nav": [{"date": "2026-05-14", "value": 1000}, {"date": "2026-05-15", "value": 1010}]},
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def write_static_performance_nav(path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "static", "as_of": "2026-05-15T15:00:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "static-nav-test"},
                "data": {
                    "default_strategy": "momentum",
                    "strategies": {
                        "momentum": {
                            "label": "动量策略",
                            "engine": "static",
                            "nav": [{"date": "2026-05-14", "net_value": 1.0}, {"date": "2026-05-15", "net_value": 1.02}],
                        }
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def post_performance_snapshot(client: TestClient, run_id: str, as_of: str, total_value: float) -> None:
    response = client.post(
        "/api/v1/joinquant/signals",
        headers={"X-Webhook-Token": "test-joinquant-token"},
        json={
            "strategy_id": "jq-new-alpha",
            "strategy_name": "新策略 Alpha",
            "trade_date": as_of[:10],
            "as_of": as_of,
            "run_id": run_id,
            "portfolio": {"total_value": total_value, "cash": 20000, "available_cash": 20000},
            "holdings": [
                {"symbol": "300476.XSHE", "name": "胜宏科技", "quantity": 1000, "last_price": 41.2, "market_value": 41200},
                {"symbol": "002463.XSHE", "name": "沪电股份", "quantity": 800, "last_price": 48.5, "market_value": 38800},
            ],
            "trades": [{"trade_id": f"{run_id}-1", "symbol": "300476.XSHE", "action": "buy", "quantity": 1000, "price": 41.2}],
            "signals": [{"symbol": "300476.XSHE", "name": "胜宏科技", "signal": "buy"}],
            "logs": [{"time": as_of, "stage": "trade", "message": "调仓完成"}],
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["performance_snapshot"]["total_value"] == total_value


def post_performance_nav_snapshot(client: TestClient) -> None:
    response = client.post(
        "/api/v1/joinquant/signals",
        headers={"X-Webhook-Token": "test-joinquant-token"},
        json={
            "strategy_id": "jq-new-alpha",
            "strategy_name": "新策略 Alpha",
            "trade_date": "2026-05-16",
            "as_of": "2026-05-16T15:00:00+08:00",
            "run_id": "jq-new-alpha-daily-nav",
            "portfolio": {"total_value": 103500, "cash": 20000, "available_cash": 20000},
            "nav": [
                {"date": "2026-05-14", "net_value": 1.0},
                {"date": "2026-05-15", "net_value": 1.012},
                {"date": "2026-05-16", "net_value": 1.035},
            ],
            "holdings": [
                {"symbol": "300476.XSHE", "name": "胜宏科技", "quantity": 1000, "last_price": 41.2, "market_value": 41200}
            ],
        },
    )
    assert response.status_code == 200, response.text


def test_joinquant_webhook_persists_performance_nav_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])

    post_performance_snapshot(client, "jq-new-alpha-run-1", "2026-05-14T10:30:00+08:00", 100000)
    post_performance_snapshot(client, "jq-new-alpha-run-2", "2026-05-15T10:30:00+08:00", 101200)
    post_performance_snapshot(client, "jq-new-alpha-run-2", "2026-05-15T10:30:00+08:00", 101200)

    response = client.get("/api/v1/performance?strategy=jq-new-alpha&benchmark=none&from=2026-05-14&to=2026-05-15")

    assert response.status_code == 200, response.text
    payload = response.json()
    curve = payload["data"]["equity_curve"]
    assert payload["meta"]["source"] == "joinquant"
    assert payload["data"]["strategy"] == "jq-new-alpha"
    assert any(item["id"] == "jq-new-alpha" and item["label"] == "新策略 Alpha" for item in payload["data"]["strategies"])
    assert len(curve) == 2
    assert curve[-1]["value"] == 1.012
    assert curve[-1]["return_pct"] == 1.2
    assert curve[-1]["total_value"] == 101200
    assert curve[-1]["cash"] == 20000
    assert curve[-1]["positions_market_value"] == 80000
    assert curve[-1]["reconciliation_diff"] == 1200
    assert curve[-1]["run_id"] == "jq-new-alpha-run-2"
    assert curve[-1]["as_of"] == "2026-05-15T10:30:00+08:00"
    assert curve[-1]["trace"]["raw_webhook_log"].endswith("joinquant-signals.jsonl")
    ledger_rows = [json.loads(line) for line in paths["ledger"].read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len([row for row in ledger_rows if row["snapshot_id"].endswith("jq-new-alpha-run-2|2026-05-15T10:30:00+08:00")]) == 1


def test_joinquant_webhook_accepts_daily_nav_curve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])

    post_performance_nav_snapshot(client)

    response = client.get("/api/v1/performance?strategy=jq-new-alpha&benchmark=none&from=2026-05-14&to=2026-05-16")

    assert response.status_code == 200, response.text
    payload = response.json()
    curve = payload["data"]["equity_curve"]
    assert len(curve) == 3
    assert [row["date"] for row in curve] == ["2026-05-14", "2026-05-15", "2026-05-16"]
    assert curve[-1]["return_pct"] == 3.5
    assert payload["data"]["data_quality"]["frequency"] == "daily"
    assert payload["data"]["data_quality"]["synthetic"] is False
    assert payload["data"]["nav_source"]["frequency_label"] == "日频"


def test_strategy_events_build_local_daily_performance_curve(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])

    def fake_prices(symbol: str, start_day, end_day) -> dict[str, float]:
        assert symbol == "300476"
        return {"2026-05-14": 10.0, "2026-05-15": 11.0}

    monkeypatch.setattr(backend_main, "fetch_strategy_daily_prices", fake_prices)

    response = client.post(
        "/api/v1/quant/strategies/joinquant-wufu-etf-v43/events",
        headers={"X-Action-Token": "test-action-token", "X-Webhook-Token": "test-joinquant-token"},
        json={
            "strategy_name": "五福 ETF",
            "run_id": "event-ledger-test",
            "events": [
                {
                    "event_id": "buy-300476-20260514",
                    "event_type": "trade",
                    "trade_date": "2026-05-14",
                    "time": "2026-05-14T10:00:00+08:00",
                    "symbol": "300476.XSHE",
                    "name": "胜宏科技",
                    "side": "buy",
                    "quantity": 100,
                    "price": 10,
                    "initial_cash": 10000,
                    "reason": "动量突破",
                }
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["trade_count"] == 1
    assert paths["events"].exists()
    holdings_path = tmp_path / "data/backend/portfolio/holdings.json"
    holdings_path.parent.mkdir(parents=True, exist_ok=True)
    holdings_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "manual", "as_of": "2026-05-15T15:00:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "holdings-empty-test"},
                "data": {"summary": {}, "holdings": [], "allocation": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/api/v1/performance?strategy=joinquant-wufu-etf-v43&benchmark=none&from=2026-05-14&to=2026-05-15")

    assert response.status_code == 200, response.text
    payload = response.json()
    curve = payload["data"]["equity_curve"]
    assert payload["meta"]["source"] == "local-ledger"
    assert payload["data"]["data_quality"]["frequency"] == "daily"
    assert payload["data"]["nav_source"]["source"] == "local-ledger"
    assert [row["date"] for row in curve] == ["2026-05-14", "2026-05-15"]
    assert curve[0]["total_value"] == 10000
    assert curve[0]["cash"] == 9000
    assert curve[-1]["value"] == 1.01
    assert curve[-1]["return_pct"] == 1.0
    assert curve[-1]["positions_market_value"] == 1100
    assert payload["data"]["reconciliation"]["formula"].startswith("cash + positions")

    response = client.get("/api/v1/portfolio/holdings?type=quant&strategy_id=joinquant-wufu-etf-v43")

    assert response.status_code == 200, response.text
    holdings_payload = response.json()
    holding = holdings_payload["data"]["holdings"][0]
    assert holding["symbol"] == "300476"
    assert holding["portfolio_type"] == "quant"
    assert holding["source"] == "local-ledger"
    assert holding["quantity"] == 100
    assert holding["pnl_pct"] == 10.0


def test_static_monthly_nav_is_expanded_to_daily_proxy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])
    write_static_performance_nav(paths["performance_nav"])

    response = client.get("/api/v1/performance?strategy=momentum&benchmark=none&from=2026-05-14&to=2026-05-15")

    assert response.status_code == 200, response.text
    payload = response.json()
    curve = payload["data"]["equity_curve"]
    assert len(curve) == 2
    assert payload["data"]["data_quality"]["frequency"] == "daily-proxy"
    assert payload["data"]["data_quality"]["synthetic"] is True
    assert payload["data"]["nav_source"]["frequency_label"] == "日频代理"


def test_performance_strategy_switch_does_not_fallback_to_static_seed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])
    post_performance_snapshot(client, "jq-new-alpha-run-1", "2026-05-15T10:30:00+08:00", 100000)

    response = client.get("/api/v1/performance?strategy=missing-strategy")

    assert response.status_code == 404
    assert "策略净值不存在" in response.text


def test_performance_uses_live_benchmark_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])
    post_performance_snapshot(client, "jq-new-alpha-run-1", "2026-05-15T10:30:00+08:00", 100000)

    response = client.get("/api/v1/performance?strategy=jq-new-alpha&benchmark=CSI1000")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["benchmark_id"] == "CSI1000"
    assert payload["data"]["benchmark_status"]["source"] == "eastmoney"
    assert payload["data"]["benchmark_status"]["trade_date"] == "2026-05-15"
    assert payload["data"]["benchmark_status"]["stale_seconds"] is not None
    assert payload["data"]["benchmark_curve"][-1]["return_pct"] == 1.0


def test_performance_lists_static_quant_and_personal_curves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])
    write_static_performance_nav(paths["performance_nav"])
    holdings_path = tmp_path / "data/backend/portfolio/holdings.json"
    holdings_path.parent.mkdir(parents=True, exist_ok=True)
    holdings_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "manual", "as_of": "2026-05-15T15:00:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "manual-holdings-test"},
                "data": {
                    "summary": {},
                    "holdings": [
                        {
                            "symbol": "600519",
                            "name": "贵州茅台",
                            "portfolio_type": "personal",
                            "market_value": 110000,
                            "pnl_amount": 10000,
                            "entry_date": "2026-05-14",
                        }
                    ],
                    "allocation": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/api/v1/performance?strategy=personal-portfolio&benchmark=none&from=2026-05-14&to=2026-05-15")

    assert response.status_code == 200, response.text
    payload = response.json()
    strategy_ids = {item["id"] for item in payload["data"]["strategies"]}
    assert {"momentum", "personal-portfolio"} <= strategy_ids
    assert payload["data"]["strategy"] == "personal-portfolio"
    assert payload["data"]["strategy_label"] == "个人持仓"
    assert payload["data"]["equity_curve"][-1]["return_pct"] == 10.0
    assert payload["data"]["nav_source"]["source"] == "manual"
