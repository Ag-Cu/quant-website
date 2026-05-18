from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import backend.main as backend_main
import scripts.generate_khan_picks as generate_khan_picks
import scripts.update_live_data as update_live_data
from backend.main import ENDPOINTS, app


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "QUANT_AUTH_ENABLED",
        "QUANT_AUTH_USERNAME",
        "QUANT_AUTH_PASSWORD_HASH",
        "QUANT_AUTH_USERS_JSON",
        "QUANT_AUTH_SECRET",
        "QUANT_AUTH_COOKIE_SECURE",
        "QUANT_ACTION_TOKEN",
        "QUANT_REQUIRE_ACTION_TOKEN",
        "JOINQUANT_WEBHOOK_TOKEN",
        "CRYPTO_WEBHOOK_TOKEN",
        "QUANT_WEBHOOK_OWNER",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def assert_api_payload(payload: dict) -> None:
    assert isinstance(payload.get("meta"), dict)
    assert isinstance(payload.get("data"), dict)


def enable_auth(monkeypatch: pytest.MonkeyPatch, username: str = "owner", password: str = "correct-password") -> None:
    monkeypatch.setenv("QUANT_AUTH_ENABLED", "true")
    monkeypatch.setenv("QUANT_AUTH_USERNAME", username)
    monkeypatch.setenv("QUANT_AUTH_PASSWORD_HASH", backend_main.pbkdf2_hash_password(password, salt=b"0123456789abcdef", iterations=10_000))
    monkeypatch.setenv("QUANT_AUTH_SECRET", "test-auth-secret")
    monkeypatch.setenv("QUANT_AUTH_COOKIE_SECURE", "false")


def login(client: TestClient, username: str = "owner", password: str = "correct-password") -> None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


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


def test_watchlist_page_is_not_user_visible(client: TestClient) -> None:
    response = client.get("/watchlist.html")

    assert response.status_code == 404


def test_auth_blocks_private_pages_api_and_data(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    enable_auth(monkeypatch)

    page_response = client.get("/holdings.html", follow_redirects=False)
    assert page_response.status_code == 303
    assert page_response.headers["location"].startswith("/login.html")

    api_response = client.get("/api/v1/portfolio/holdings")
    assert api_response.status_code == 401

    data_response = client.get("/data/backend/portfolio/holdings.json")
    assert data_response.status_code == 401


def test_auth_login_grants_session(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    enable_auth(monkeypatch)
    bad = client.post("/api/v1/auth/login", json={"username": "owner", "password": "wrong"})
    assert bad.status_code == 401

    login(client)
    page_response = client.get("/holdings.html")
    assert page_response.status_code == 200
    api_response = client.get("/api/v1/health")
    assert api_response.status_code == 200, api_response.text
    session_response = client.get("/api/v1/auth/session")
    assert session_response.json()["data"]["user"]["username"] == "owner"


def test_auth_uses_user_scoped_data(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    owner_path = tmp_path / "data/backend/users/owner/portfolio/holdings.json"
    root_path = tmp_path / "data/backend/portfolio/holdings.json"
    owner_path.parent.mkdir(parents=True)
    root_path.parent.mkdir(parents=True)
    root_path.write_text(
        json.dumps({"meta": {"source": "root"}, "data": {"summary": {}, "holdings": [{"symbol": "ROOT", "portfolio_type": "personal"}], "allocation": []}}),
        encoding="utf-8",
    )
    owner_path.write_text(
        json.dumps({"meta": {"source": "owner"}, "data": {"summary": {}, "holdings": [{"symbol": "600519", "name": "贵州茅台", "market_value": 1, "portfolio_type": "personal"}], "allocation": []}}),
        encoding="utf-8",
    )

    login(client)
    response = client.get("/api/v1/portfolio/holdings?type=personal")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["storage_path"] == "data/backend/users/owner/portfolio/holdings.json"
    assert [row["symbol"] for row in payload["data"]["personal_holdings"]] == ["600519"]


def test_authenticated_user_can_delete_own_watchlist_without_action_token(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setenv("QUANT_ACTION_TOKEN", "test-action-token")
    monkeypatch.setenv("QUANT_REQUIRE_ACTION_TOKEN", "true")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(backend_main, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(backend_main, "WATCHLIST_CONFIG_PATH", tmp_path / "data/config/watchlist.json")
    monkeypatch.setattr(backend_main, "run_live_data_refresh", lambda *args, **kwargs: (False, "offline in test"))
    user_config = tmp_path / "data/backend/users/owner/config/watchlist.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        json.dumps(
            {
                "items": [
                    {"symbol": "600519", "name": "贵州茅台", "sector": "消费", "market_region": "cn", "market": "SH"},
                    {"symbol": "NVDA", "name": "NVIDIA", "sector": "科技", "market_region": "us", "provider_symbol": "NVDA"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    login(client)

    response = client.delete("/api/v1/watchlist/600519?market=cn")

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["meta"]["config_status"] == "deleted"
    assert payload["data"]["items"] == [
        {
            "symbol": "NVDA",
            "name": "NVIDIA",
            "logo": "N",
            "sector": "科技",
            "provider": "yahoo",
            "market_region": "us",
            "provider_symbol": "NVDA",
        }
    ]
    saved = json.loads(user_config.read_text(encoding="utf-8"))
    assert [item["symbol"] for item in saved["items"]] == ["NVDA"]


def test_watchlist_add_returns_config_before_live_refresh(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setenv("QUANT_ACTION_TOKEN", "test-action-token")
    monkeypatch.setenv("QUANT_REQUIRE_ACTION_TOKEN", "true")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(backend_main, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(backend_main, "WATCHLIST_CONFIG_PATH", tmp_path / "data/config/watchlist.json")
    calls: list[tuple[int, str]] = []

    def fake_refresh(timeout: int = 120, user_id: str = "") -> tuple[bool, str]:
        calls.append((timeout, user_id))
        return False, "offline in test"

    monkeypatch.setattr(backend_main, "run_live_data_refresh", fake_refresh)
    user_config = tmp_path / "data/backend/users/owner/config/watchlist.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(json.dumps({"items": []}, ensure_ascii=False), encoding="utf-8")
    login(client)

    response = client.post(
        "/api/v1/watchlist",
        json={"symbol": "510050", "name": "上证50ETF", "sector": "ETF", "market_region": "cn"},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["meta"]["config_status"] == "saved"
    assert payload["meta"]["refresh_status"] == "scheduled"
    assert [item["symbol"] for item in payload["data"]["items"]] == ["510050"]
    assert calls == [(120, "owner")]


def test_watchlist_refresh_failure_keeps_existing_user_live_cache(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setenv("QUANT_ACTION_TOKEN", "test-action-token")
    monkeypatch.setenv("QUANT_REQUIRE_ACTION_TOKEN", "true")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(backend_main, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(backend_main, "WATCHLIST_CONFIG_PATH", tmp_path / "data/config/watchlist.json")
    monkeypatch.setattr(backend_main, "run_live_data_refresh", lambda *args, **kwargs: (False, "offline in test"))
    user_config = tmp_path / "data/backend/users/owner/config/watchlist.json"
    user_config.parent.mkdir(parents=True)
    user_config.write_text(
        json.dumps(
            {
                "items": [
                    {"symbol": "600519", "name": "贵州茅台", "sector": "消费", "market_region": "cn", "market": "SH"},
                    {"symbol": "NVDA", "name": "NVIDIA", "sector": "科技", "market_region": "us", "provider_symbol": "NVDA"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    live_dir = tmp_path / "data/backend/users/owner/live"
    live_dir.mkdir(parents=True)
    for name in ("watchlist.json", "overview.json"):
        if name == "overview.json":
            data = {
                "health": {},
                "account": {},
                "market": {},
                "strategy_status": [],
                "alerts": [],
                "timeline": [],
                "decision": {},
                "sentiment_gauge": {},
                "heatmap": {},
                "top_etfs": [],
                "sectors": [],
            }
        else:
            data = {"groups": [{"name": "existing", "items": [{"symbol": "600519"}]}]}
        (live_dir / name).write_text(
            json.dumps(
                {
                    "meta": {
                        "version": "1.0",
                        "source": "live",
                        "as_of": "2026-05-17T20:30:00+08:00",
                        "trade_date": "2026-05-17",
                        "timezone": "Asia/Hong_Kong",
                        "market_session": "closed",
                        "run_id": f"existing-{name}",
                        "source_quality": "real",
                    },
                    "data": data,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    login(client)

    response = client.delete("/api/v1/watchlist/600519?market=cn")

    assert response.status_code == 202, response.text
    assert (live_dir / "watchlist.json").exists()
    assert (live_dir / "overview.json").exists()
    assert client.get("/api/v1/watchlist").status_code == 200
    assert client.get("/api/v1/dashboard/overview").status_code == 200


def test_authenticated_user_gets_user_scoped_live_market_payloads(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "LIVE_DIR", tmp_path / "data/live")
    now_meta = {
        "version": "1.0",
        "source": "live",
        "as_of": "2026-05-17T20:30:00+08:00",
        "trade_date": "2026-05-17",
        "timezone": "Asia/Hong_Kong",
        "market_session": "closed",
        "run_id": "test-live",
        "source_quality": "real",
    }
    root_breadth = tmp_path / "data/live/breadth.json"
    owner_breadth = tmp_path / "data/backend/users/owner/live/breadth.json"
    root_breadth.parent.mkdir(parents=True)
    owner_breadth.parent.mkdir(parents=True)
    root_breadth.write_text(
        json.dumps(
            {
                "meta": {**now_meta, "run_id": "root-proxy", "source_quality": "proxy"},
                "data": {"source_algorithm": {"name": "proxy", "source_quality": "proxy"}, "summary": {"industry_count": 2}, "metrics": [], "industry_width": [], "heatmap_history": {}, "style": [], "distribution": []},
            }
        ),
        encoding="utf-8",
    )
    owner_breadth.write_text(
        json.dumps(
            {
                "meta": {**now_meta, "run_id": "owner-real", "source_quality": "real"},
                "data": {"source_algorithm": {"name": "market_width.zip", "source_quality": "real"}, "summary": {"industry_count": 31}, "metrics": [], "industry_width": [], "heatmap_history": {}, "style": [], "distribution": []},
            }
        ),
        encoding="utf-8",
    )
    login(client)

    response = client.get("/api/v1/market/breadth")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["storage_path"] == "data/backend/users/owner/live/breadth.json"
    assert payload["meta"]["source_quality"] == "real"
    assert payload["data"]["summary"]["industry_count"] == 31


def test_authenticated_overview_sentiment_is_aligned_with_user_sentiment_live_cache(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "LIVE_DIR", tmp_path / "data/live")
    live_dir = tmp_path / "data/backend/users/owner/live"
    live_dir.mkdir(parents=True)
    meta = {
        "version": "1.0",
        "source": "live",
        "as_of": "2026-05-18T09:10:00+08:00",
        "trade_date": "2026-05-18",
        "timezone": "Asia/Hong_Kong",
        "market_session": "preopen",
        "run_id": "owner-live",
        "source_quality": "real",
    }
    (live_dir / "overview.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "data": {
                    "account": {},
                    "market": {"sentiment_score": 51},
                    "decision": {},
                    "sentiment_gauge": {"score": 50.99, "label": "低迷"},
                    "heatmap": {},
                    "top_etfs": [],
                    "sectors": [],
                    "strategy_status": [],
                    "alerts": [],
                    "watchlist": {"groups": [{"name": "old", "items": []}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (live_dir / "sentiment.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "data": {
                    "summary": {"score": 92, "label": "活跃"},
                    "latest_snapshot": {},
                    "brilliant_volatility": {},
                    "sentiment_trend": [],
                    "brilliant_series": [],
                    "surge_events": [],
                    "gauges": [],
                    "topics": [],
                    "flows": [],
                    "warnings": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    login(client)

    response = client.get("/api/v1/dashboard/overview")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["storage_path"] == "data/backend/users/owner/live/overview.json"
    assert payload["data"]["market"]["sentiment_score"] == 92
    assert payload["data"]["sentiment_gauge"]["score"] == 92
    assert payload["data"]["sentiment_gauge"]["label"] == "活跃"
    assert "watchlist" not in payload["data"]


def test_auth_keeps_joinquant_webhook_token_path_available(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setenv("JOINQUANT_WEBHOOK_TOKEN", "test-joinquant-token")

    response = client.post("/api/v1/joinquant/signals", json={"data": {}})

    assert response.status_code == 401
    assert response.json()["detail"] == "JoinQuant webhook token 不正确"


def test_auth_keeps_dynamic_strategy_ingest_path_available(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setenv("QUANT_ACTION_TOKEN", "test-action-token")
    monkeypatch.setenv("JOINQUANT_WEBHOOK_TOKEN", "test-joinquant-token")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(backend_main, "STRATEGY_CONFIG_PATH", tmp_path / "data/config/strategies.json")
    monkeypatch.setattr(backend_main, "CUSTOM_STRATEGY_DIR", tmp_path / "data/backend/strategies/custom")
    monkeypatch.setattr(backend_main, "ACTION_LOG_PATH", tmp_path / "data/backend/actions/action-log.jsonl")
    monkeypatch.setattr(backend_main, "JOINQUANT_SIGNAL_LOG_PATH", tmp_path / "data/backend/strategies/joinquant-signals.jsonl")
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl")
    login(client)
    create = client.post(
        "/api/v1/quant/strategies",
        headers={"X-Action-Token": "test-action-token"},
        json={"id": "webhook-alpha", "name": "Webhook Alpha"},
    )
    assert create.status_code == 200, create.text
    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200

    response = client.post(
        "/api/v1/quant/strategies/webhook-alpha/events",
        headers={"X-Action-Token": "test-action-token", "X-Webhook-Token": "test-joinquant-token"},
        json={"events": [{"event_type": "signal", "symbol": "600519.XSHG", "action": "buy", "trade_date": "2026-05-17"}]},
    )

    assert response.status_code == 200, response.text


def test_auth_forbids_explicit_other_user_data_paths(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    enable_auth(monkeypatch)
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    other_path = tmp_path / "data/backend/users/other/portfolio/holdings.json"
    other_path.parent.mkdir(parents=True)
    other_path.write_text("{}", encoding="utf-8")
    login(client)

    response = client.get("/data/backend/users/other/portfolio/holdings.json")

    assert response.status_code == 404


def test_strategy_id_aliases_keep_old_links_working(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    etf_path = tmp_path / "data/backend/strategies/etf.json"
    etf_path.parent.mkdir(parents=True)
    etf_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "joinquant", "as_of": "2026-05-15T10:30:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "open", "run_id": "etf-alias-test"},
                "data": {
                    "strategy": {"id": "joinquant-wufu-etf-v43", "name": "五福 ETF", "status": "running"},
                    "summary": {},
                    "recommendations": [{"symbol": "159915.XSHE", "name": "创业板ETF", "action": "buy"}],
                    "holdings": [],
                    "regime": {},
                    "events": [],
                    "logs": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "ETF_STRATEGY_PATH", etf_path)

    response = client.get("/api/v1/quant/strategies/etf-rotation")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["strategy"]["id"] == "joinquant-wufu-etf-v43"
    assert payload["data"]["registry"]["id"] == "joinquant-wufu-etf-v43"
    assert payload["data"]["holdings_url"].endswith("strategy_id=joinquant-wufu-etf-v43")


@pytest.mark.parametrize("path", sorted(ENDPOINTS))
def test_endpoints_return_meta_and_data(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert_api_payload(response.json())


def test_strategy_picks_can_filter_khan_strategy(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    picks_path = tmp_path / "data/backend/strategies/picks.json"
    picks_path.parent.mkdir(parents=True)
    picks_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "tushare+khan-quant-data", "as_of": "2026-05-17T18:20:57+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "khan-picks-test"},
                "data": {
                    "strategy": "khan-macd-volume",
                    "strategy_label": "Khan MA 量价选股",
                    "trade_date": "2026-05-15",
                    "status": "ready",
                    "count": 1,
                    "strategies": [{"id": "khan-macd-volume", "label": "Khan MA 量价选股"}],
                    "items": [
                        {
                            "symbol": "002889",
                            "name": "东方嘉盛",
                            "strategy": "khan-macd-volume",
                            "strategy_id": "khan-macd-volume",
                            "strategy_label": "Khan MA 量价选股",
                            "trade_date": "2026-05-15",
                            "score": 94,
                            "confidence": 0.94,
                            "factors": [],
                            "entry_price": 13.62,
                            "stop_loss": 12.53,
                            "take_profit": 17.71,
                            "explanation": "复刻 khan-quant-data macd.py 入池逻辑",
                            "invalidation": "跌破入池价 8%",
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")

    response = client.get("/api/v1/strategies/picks?strategy=khan-macd-volume&date=2026-05-15")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["strategy"] == "khan-macd-volume"
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["symbol"] == "002889"
    assert payload["data"]["items"][0]["entry_price"] == 13.62
    assert "tags" not in payload["data"]["items"][0]


def test_strategy_picks_uses_owner_khan_data_when_auth_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path, client: TestClient) -> None:
    root_picks_path = tmp_path / "data/backend/strategies/picks.json"
    owner_picks_path = tmp_path / "data/backend/users/owner/strategies/picks.json"
    root_picks_path.parent.mkdir(parents=True)
    owner_picks_path.parent.mkdir(parents=True)
    root_picks_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "seed", "as_of": "2026-05-12T10:00:00+08:00", "trade_date": "2026-05-12", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "old-picks"},
                "data": {
                    "strategy": "momentum",
                    "strategy_label": "动量策略",
                    "trade_date": "2026-05-12",
                    "status": "ready",
                    "strategies": ["动量策略"],
                    "items": [{"symbol": "300476", "name": "胜宏科技", "score": 80, "tags": ["旧标签"]}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    owner_picks_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "tushare+khan-quant-data", "as_of": "2026-05-17T18:20:57+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "khan-picks-test"},
                "data": {
                    "strategy": "khan-macd-volume",
                    "strategy_label": "Khan MA 量价选股",
                    "trade_date": "2026-05-15",
                    "status": "ready",
                    "strategies": [{"id": "khan-macd-volume", "label": "Khan MA 量价选股"}],
                    "source": {"method_summary": "Khan 选股核心方法"},
                    "items": [{"symbol": "002889", "name": "东方嘉盛", "score": 94, "strategy_id": "khan-macd-volume"}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")

    response = client.get("/api/v1/strategies/picks")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["meta"]["storage_path"] == "data/backend/users/owner/strategies/picks.json"
    assert payload["data"]["strategy"] == "khan-macd-volume"
    assert payload["data"]["source"]["method_summary"] == "Khan 选股核心方法"
    assert [item["symbol"] for item in payload["data"]["items"]] == ["002889"]


def test_khan_pick_generator_overwrites_old_pick_strategies(tmp_path) -> None:
    output = generate_khan_picks.output_path(tmp_path, "owner")
    output.parent.mkdir(parents=True)
    output.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "old", "as_of": "2026-05-12T10:00:00+08:00", "trade_date": "2026-05-12", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "old-picks"},
                "data": {
                    "strategy": "old",
                    "strategy_label": "旧选股",
                    "trade_date": "2026-05-12",
                    "status": "ready",
                    "count": 1,
                    "strategies": [{"id": "old", "label": "旧选股"}],
                    "items": [{"symbol": "300476", "name": "胜宏科技", "strategy": "old", "tags": ["旧标签"]}],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    payload = {
        "meta": {"version": "1.0", "source": "tushare+khan-quant-data", "as_of": "2026-05-17T18:20:57+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "khan-picks-test"},
        "data": {
            "strategy": "khan-macd-volume",
            "strategy_label": "Khan MA 量价选股",
            "trade_date": "2026-05-15",
            "status": "ready",
            "count": 1,
            "strategies": [{"id": "khan-macd-volume", "label": "Khan MA 量价选股"}],
            "items": [{"symbol": "002889", "name": "东方嘉盛", "strategy_id": "khan-macd-volume"}],
        },
    }

    generate_khan_picks.atomic_write_json(output, payload)

    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["data"]["count"] == 1
    assert saved["data"]["strategies"] == [{"id": "khan-macd-volume", "label": "Khan MA 量价选股"}]
    assert [item["symbol"] for item in saved["data"]["items"]] == ["002889"]
    assert all(item.get("strategy_id") == "khan-macd-volume" for item in saved["data"]["items"])
    assert all("tags" not in item for item in saved["data"]["items"])


def test_retail_sentiment_uses_real_minute_volume_diff(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    rows = []
    base_volume = 1_000
    for index in range(12):
        minute = 32 + index
        rows.append(
            {
                "time": f"2026-05-15 09:{minute:02d}:00",
                "close": 10 + index * 0.03,
                "volume": base_volume + index * 100 + (3_000 if index == 5 else 0),
            }
        )
    path = tmp_path / "minutes.json"
    path.write_text(json.dumps({"symbol": "159915.XSHE", "name": "创业板ETF", "rows": rows}), encoding="utf-8")
    monkeypatch.setattr(update_live_data, "ROOT", tmp_path)
    monkeypatch.setattr(update_live_data, "CONFIG_DIR", tmp_path)
    monkeypatch.setenv("RETAIL_SENTIMENT_MINUTE_PATH", str(path))

    signal = update_live_data.build_real_sentiment_signal()

    assert signal is not None
    assert signal.source_quality == "real"
    assert signal.data_source == "configured retail sentiment minute file"
    assert "volume.diff()" in signal.surge_rule
    assert signal.surge_count >= 1
    assert signal.surge_events
    assert signal.surge_events[0]["volume_increase"] > 100


def test_user_live_generation_templates_fallback_to_root(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root_backend = tmp_path / "data/backend"
    for rel, data in {
        "watchlist/list.json": {"groups": [{"name": "root", "items": []}]},
        "market/heatmap.json": {"timeframe": "1D", "group_by": "sector", "updated_at": "old", "cells": []},
        "market/etf-rankings.json": {"period": "1D", "items": []},
        "market/sectors.json": {"period": "1D", "updated_at": "old", "sectors": []},
    }.items():
        path = root_backend / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"meta": {"version": "1.0", "source": "seed", "as_of": "2026-05-15T00:00:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": rel}, "data": data}), encoding="utf-8")
    monkeypatch.setattr(update_live_data, "ROOT", tmp_path)
    monkeypatch.setattr(update_live_data, "ROOT_BACKEND_DIR", root_backend)
    monkeypatch.setattr(update_live_data, "BACKEND_DIR", root_backend / "users/owner")
    monkeypatch.setattr(update_live_data, "LIVE_DIR", root_backend / "users/owner/live")
    monkeypatch.setattr(update_live_data, "CONFIG_DIR", root_backend / "users/owner/config")

    watchlist = update_live_data.build_watchlist_payload({}, [])
    heatmap = update_live_data.build_heatmap_payload({})
    etfs = update_live_data.build_etf_rankings_payload({})
    sectors = update_live_data.build_sectors_payload([])

    assert watchlist["data"]["groups"] == []
    assert heatmap["data"]["cells"] == []
    assert etfs["data"]["items"] == []
    assert sectors["data"]["sectors"] == []


def test_breadth_payload_rebuilds_heatmap_when_source_history_is_stale(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(update_live_data, "ROOT", tmp_path)
    monkeypatch.setattr(update_live_data, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(update_live_data, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(update_live_data, "now_hk", lambda: update_live_data.datetime(2026, 5, 18, 9, 40, tzinfo=update_live_data.HK_TZ))
    seed = tmp_path / "data/live/breadth.json"
    seed.parent.mkdir(parents=True)
    seed.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "live", "as_of": "2026-05-17T21:17:07+08:00", "trade_date": "2026-05-17", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "old-breadth"},
                "data": {
                    "summary": {},
                    "metrics": [],
                    "industry_width": [],
                    "heatmap_history": {"columns": ["全市场", "银行I"], "rows": [{"date": "04-07", "values": [51, 88]}]},
                    "style": [],
                    "distribution": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    source = update_live_data.BreadthSource(
        records=[
            update_live_data.BoardRecord(code="801780", name="银行I", change_pct=1.2, up_count=8, down_count=2, flat_count=0),
            update_live_data.BoardRecord(code="801750", name="计算机I", change_pct=-0.5, up_count=3, down_count=7, flat_count=0),
        ],
        name="stale source",
        quality="real",
        universe="test",
        industry_standard="test",
        notes=[],
        heatmap_columns=["全市场", "银行I", "计算机I", "合计"],
        heatmap_rows=[{"date": "04-07", "values": [51, 88, 22, 10]}],
    )

    payload = update_live_data.build_breadth_payload(source)
    rows = payload["data"]["heatmap_history"]["rows"]

    assert rows[0]["date"] == "05-18"
    assert rows[0]["values"] == [55, 80, 30]
    assert rows[1]["date"] == "04-07"
    assert payload["data"]["summary"]["market_width_pct"] == 55


def test_tushare_trade_days_handles_descending_calendar() -> None:
    class FakePro:
        def query(self, name: str, **kwargs):
            import pandas as pd

            assert name == "trade_cal"
            return pd.DataFrame(
                [
                    {"cal_date": "20260518", "is_open": 1},
                    {"cal_date": "20260517", "is_open": 0},
                    {"cal_date": "20260515", "is_open": 1},
                    {"cal_date": "20260514", "is_open": 1},
                    {"cal_date": "20260513", "is_open": 1},
                    {"cal_date": "20260512", "is_open": 1},
                ]
            )

    assert update_live_data.tushare_trade_days(FakePro(), "20260518", 3) == ["20260514", "20260515", "20260518"]


def test_tushare_token_loads_from_env_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    env_file = tmp_path / "quant.env"
    env_file.write_text("OTHER=value\nTUSHARE_TOKEN=from-file\n", encoding="utf-8")
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    monkeypatch.delenv("TUSHARE_PRO_TOKEN", raising=False)
    monkeypatch.delenv("TS_TOKEN", raising=False)
    monkeypatch.setenv("QUANT_WEBSITE_ENV_FILE", str(env_file))

    assert update_live_data.tushare_token() == "from-file"


def test_macro_payload_does_not_keep_sample_rows_when_sources_are_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    macro_path = tmp_path / "data/backend/macro.json"
    macro_path.parent.mkdir(parents=True)
    macro_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "seed", "as_of": "2026-05-12T00:00:00+08:00", "trade_date": "2026-05-12", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "macro-seed"},
                "data": {
                    "summary": {"risk_preference_score": 66, "equity_bond_spread_pct": 3.84},
                    "rates": [],
                    "fx": [{"name": "美元指数", "value": 104.3, "data_source": "macro sample"}],
                    "risk_assets": [{"name": "旧指数", "value": 1, "data_source": "macro sample"}],
                    "calendar": [],
                    "observations": [],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_live_data, "ROOT", tmp_path)
    monkeypatch.setattr(update_live_data, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(update_live_data, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(update_live_data, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(update_live_data, "fetch_wscn_realtime", lambda code: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(update_live_data, "fetch_sina_fx_usdcnh", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(update_live_data, "fetch_chinabond_treasury_curve", lambda: {})
    monkeypatch.setattr(update_live_data, "fetch_eastmoney_index_metrics", lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(update_live_data, "fetch_sina_index_metrics", lambda: {})

    payload = update_live_data.build_macro_payload()
    text = json.dumps(payload, ensure_ascii=False)

    assert "macro sample" not in text
    assert payload["data"]["fx"] == [{"name": "USD/CNH", "value": None, "change_pct": None, "data_source": "unavailable", "as_of": payload["data"]["fx"][0]["as_of"]}]
    assert payload["data"]["risk_assets"] == []
    assert payload["data"]["summary"]["risk_preference_score"] is None
    assert payload["data"]["indicators"] == []


def test_macro_payload_exposes_common_real_indicator_set(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    macro_path = tmp_path / "data/backend/macro.json"
    macro_path.parent.mkdir(parents=True)
    macro_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "seed", "as_of": "2026-05-12T00:00:00+08:00", "trade_date": "2026-05-12", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "macro-seed"},
                "data": {"summary": {}, "rates": [], "fx": [], "risk_assets": [], "calendar": [], "observations": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_live_data, "ROOT", tmp_path)
    monkeypatch.setattr(update_live_data, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(update_live_data, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(update_live_data, "CONFIG_DIR", tmp_path / "data/config")
    monkeypatch.setattr(update_live_data, "fetch_wscn_realtime", lambda code: {"value": 7.22 if code == "USDCNH.OTC" else 4.5, "change_pct": -0.12 if code == "USDCNH.OTC" else 0.02, "data_source": "stub", "as_of": "2026-05-15T15:00:00+08:00"})
    monkeypatch.setattr(update_live_data, "fetch_chinabond_treasury_curve", lambda: {
        "10年": {"value": 2.1, "change_bp": -1.2, "data_source": "chinabond", "as_of": "2026-05-15"},
        "1年": {"value": 1.5, "change_bp": 0.2, "data_source": "chinabond", "as_of": "2026-05-15"},
    })
    monkeypatch.setattr(update_live_data, "fetch_eastmoney_index_metrics", lambda: {
        "CSI300": {"name": "沪深300", "value": 3900, "change_pct": 1.0, "pe_ttm": 12.0, "data_source": "eastmoney", "as_of": "2026-05-15T15:00:00+08:00"},
        "CSI1000": {"name": "中证1000", "value": 6200, "change_pct": 0.5, "data_source": "eastmoney", "as_of": "2026-05-15T15:00:00+08:00"},
        "CHINEXT": {"name": "创业板指", "value": 2100, "change_pct": -0.2, "data_source": "eastmoney", "as_of": "2026-05-15T15:00:00+08:00"},
    })

    payload = update_live_data.build_macro_payload()
    names = {row["name"] for row in payload["data"]["indicators"]}

    assert {"中国 10Y 国债", "中国期限利差 10Y-1Y", "中美 10Y 利差", "USD/CNH", "沪深300 PE(TTM)", "沪深300股债利差", "沪深300涨跌", "中证1000涨跌", "创业板指涨跌"} <= names
    assert payload["data"]["summary"]["china_term_spread_bp"] == 60.0
    assert payload["data"]["summary"]["china_us_spread_bp"] == -240.0


def test_overview_sentiment_gauge_matches_sentiment_summary(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    dashboard_path = tmp_path / "data/backend/dashboard/overview.json"
    dashboard_path.parent.mkdir(parents=True)
    dashboard_path.write_text(
        json.dumps(
            {
                "meta": {"version": "1.0", "source": "seed", "as_of": "2026-05-15T00:00:00+08:00", "trade_date": "2026-05-15", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "overview-seed"},
                "data": {"market": {}, "sentiment_gauge": {"score": 88, "previous_day_score": 70}, "top_etfs": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(update_live_data, "ROOT", tmp_path)
    monkeypatch.setattr(update_live_data, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(update_live_data, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(update_live_data, "build_six_month_sentiment_trend", lambda series: ([{"date": "2026-05-14", "value": 11}, {"date": "2026-05-15", "value": 12}], "test-trend", "test note"))
    monkeypatch.setattr(update_live_data, "build_account_from_holdings", lambda: {})
    monkeypatch.setattr(update_live_data, "build_strategy_status_from_artifacts", lambda: ([], "test"))
    monkeypatch.setattr(update_live_data, "build_timeline_from_strategy_artifacts", lambda: ([], "test"))
    monkeypatch.setattr(update_live_data, "load_scheduler_status", lambda: {})

    payload = update_live_data.build_overview_payload(
        {"data": {"summary": {"score": 55}}},
        {"data": {"summary": {"score": 37, "label": "低迷"}, "sentiment_trend": [{"date": "2026-05-15", "value": 12}]}},
        {"data": {"summary": {"risk_preference_score": 50}}},
    )

    assert payload["data"]["market"]["sentiment_score"] == 37
    assert payload["data"]["sentiment_gauge"]["score"] == 37
    assert payload["data"]["sentiment_gauge"]["previous_day_score"] == 11


def test_live_overview_ignores_non_real_strategy_artifacts(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    root_backend = tmp_path / "data/backend"
    etf_path = root_backend / "strategies/etf.json"
    small_cap_path = root_backend / "strategies/small-cap.json"
    etf_path.parent.mkdir(parents=True)
    synthetic_payload = {
        "meta": {
            "version": "1.0",
            "source": "joinquant",
            "as_of": "2026-05-14T13:10:00+08:00",
            "trade_date": "2026-05-14",
            "timezone": "Asia/Hong_Kong",
            "market_session": "closed",
            "run_id": "domain-log-test-20260514-1311",
        },
        "data": {
            "strategy": {"id": "joinquant-wufu-etf-v43", "name": "五福闹新春 v4.3", "status": "running"},
            "summary": {"buy_count": 1, "target_exposure_pct": 100},
            "recommendations": [{"symbol": "159915", "reason": "日志联调测试"}],
            "holdings": [{"symbol": "159915"}],
            "events": [{"time": "13:10", "label": "日志联调", "detail": "完整日志同步测试"}],
            "logs": [{"message": "示例风控日志：成交量过滤通过但需观察"}],
        },
    }
    small_cap_seed = {
        "meta": {
            "version": "1.0",
            "source": "live",
            "as_of": "2026-05-12T14:56:00+08:00",
            "trade_date": "2026-05-12",
            "timezone": "Asia/Hong_Kong",
            "market_session": "open",
            "run_id": "backend-small-20260512-1456",
        },
        "data": {
            "strategy": {"id": "small-cap-momentum", "name": "小盘股动量", "status": "running"},
            "summary": {"buy_count": 2, "target_exposure_pct": 55},
            "signals": [{"symbol": "300476", "name": "胜宏科技"}],
            "holdings": [{"symbol": "002463"}],
            "events": [],
            "logs": [],
        },
    }
    etf_path.write_text(json.dumps(synthetic_payload, ensure_ascii=False), encoding="utf-8")
    small_cap_path.write_text(json.dumps(small_cap_seed, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(update_live_data, "ROOT", tmp_path)
    monkeypatch.setattr(update_live_data, "ROOT_BACKEND_DIR", root_backend)
    monkeypatch.setattr(update_live_data, "BACKEND_DIR", root_backend)
    monkeypatch.setattr(update_live_data, "LIVE_DIR", tmp_path / "data/live")
    monkeypatch.setattr(update_live_data, "CONFIG_DIR", tmp_path / "data/config")

    status, status_source = update_live_data.build_strategy_status_from_artifacts()
    timeline, timeline_source = update_live_data.build_timeline_from_strategy_artifacts()

    assert status == []
    assert status_source == "unavailable"
    assert timeline == []
    assert timeline_source == "unavailable"


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


def test_binance_listing_webhook_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    monkeypatch.setenv("CRYPTO_WEBHOOK_TOKEN", "test-crypto-token")
    strategy_dir = tmp_path / "data/backend/strategies"
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "BINANCE_LISTING_STRATEGY_PATH", strategy_dir / "binance-listing-onchain.json")
    monkeypatch.setattr(backend_main, "BINANCE_LISTING_HEARTBEAT_LOG_PATH", strategy_dir / "binance-listing-heartbeats.jsonl")
    monkeypatch.setattr(backend_main, "BINANCE_LISTING_SIGNAL_LOG_PATH", strategy_dir / "binance-listing-signals.jsonl")
    monkeypatch.setattr(backend_main, "BINANCE_LISTING_TRADE_LOG_PATH", strategy_dir / "binance-listing-trades.jsonl")
    monkeypatch.setattr(backend_main, "BINANCE_LISTING_EVENT_LOG_PATH", strategy_dir / "binance-listing-events.jsonl")
    monkeypatch.setattr(backend_main, "BINANCE_LISTING_LOG_PATH", strategy_dir / "binance-listing-logs.jsonl")

    headers = {"X-Crypto-Webhook-Token": "test-crypto-token"}
    heartbeat = client.post(
        "/api/v1/crypto/binance-listing/heartbeat",
        headers=headers,
        json={
            "heartbeat": {
                "mode": "DRY_RUN",
                "run_id": "listing-test-run",
                "host": "jp_vps",
                "catalog_id": 48,
                "seen_article_count": 12,
                "stats": {"validated": 1, "orders": 1, "errors": 0},
                "risk": {"stake_usd": 100, "stop_loss_pct": 0.08, "take_profit_1_pct": 0.10, "take_profit_2_pct": 1.0},
            },
            "positions": [
                {
                    "symbol": "TEST",
                    "chain": "base",
                    "token_address": "0x0000000000000000000000000000000000000001",
                    "entry_cost_usd": 100,
                    "remaining_amount_raw": "1000000000000000000",
                    "listing_time_utc": "2026-05-17T12:00:00Z",
                }
            ],
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text

    signal = client.post(
        "/api/v1/crypto/binance-listing/signals",
        headers=headers,
        json={
            "signals": [
                {
                    "symbol": "TEST",
                    "status": "valid",
                    "title": "Binance Will List TEST",
                    "listing_time_utc": "2026-05-17T12:00:00Z",
                    "binance_spot_pairs": ["TEST/USDT"],
                    "contract": {"chain": "base", "address": "0x0000000000000000000000000000000000000001"},
                }
            ]
        },
    )
    assert signal.status_code == 200, signal.text

    trade = client.post(
        "/api/v1/crypto/binance-listing/trades",
        headers=headers,
        json={
            "trades": [
                {
                    "symbol": "TEST",
                    "side": "buy",
                    "status": "dry_run_filled",
                    "chain": "base",
                    "quote_token": "USDC",
                    "order": {"amount_in_usd": 100},
                }
            ]
        },
    )
    assert trade.status_code == 200, trade.text

    response = client.get("/api/v1/strategies/binance-listing-onchain")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["strategy"]["id"] == "binance-listing-onchain"
    assert payload["data"]["summary"]["signal_count"] == 1
    assert payload["data"]["summary"]["open_position_count"] == 1
    assert payload["data"]["signals"][0]["symbol"] == "TEST"
    assert payload["data"]["trades"][0]["side"] == "buy"
    assert payload["data"]["logs"]


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
    monkeypatch.setattr(backend_main, "PERFORMANCE_EVENTS_PATH", tmp_path / "data/backend/performance/strategy-events.jsonl")
    monkeypatch.setattr(backend_main, "SMALL_CAP_STRATEGY_PATH", small_cap_path)
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", full_log_path)

    response = client.get("/api/v1/strategies/small-cap")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["source"] == "joinquant-pending"
    assert payload["meta"]["source_quality"] == "pending"
    assert payload["data"]["signals"] == []
    assert payload["data"]["holdings"] == []
    assert payload["data"]["ignored_seed_signal_count"] == 4


def test_etf_endpoint_hides_synthetic_joinquant_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    etf_path = tmp_path / "data/backend/strategies/etf.json"
    etf_path.parent.mkdir(parents=True)
    etf_path.write_text(
        """
        {
          "meta": {"version": "1.0", "source": "joinquant", "as_of": "2026-05-14T13:10:00+08:00", "trade_date": "2026-05-14", "timezone": "Asia/Hong_Kong", "market_session": "closed", "run_id": "domain-log-test-20260514-1311"},
          "data": {
            "strategy": {"id": "joinquant-wufu-etf-v43", "name": "五福闹新春 v4.3", "status": "running"},
            "summary": {"buy_count": 1, "target_exposure_pct": 100},
            "recommendations": [{"symbol": "159915", "name": "创业板ETF易方达", "action": "buy", "reason": "日志联调测试"}],
            "holdings": [{"symbol": "159915", "name": "创业板ETF易方达"}],
            "regime": {},
            "events": [{"time": "13:10", "label": "日志联调", "detail": "完整日志同步测试"}],
            "logs": [{"message": "示例风控日志：成交量过滤通过但需观察"}]
          }
        }
        """,
        encoding="utf-8",
    )
    full_log_path = tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl"
    full_log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "ETF_STRATEGY_PATH", etf_path)
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", full_log_path)

    response = client.get("/api/v1/strategies/etf")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["source"] == "joinquant-pending"
    assert payload["meta"]["source_quality"] == "pending"
    assert payload["data"]["recommendations"] == []
    assert payload["data"]["holdings"] == []
    assert payload["data"]["ignored_seed_signal_count"] == 1


def test_etf_endpoint_returns_pending_when_snapshot_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    etf_path = tmp_path / "data/backend/strategies/etf.json"
    full_log_path = tmp_path / "data/backend/strategies/joinquant-full-logs.jsonl"
    full_log_path.parent.mkdir(parents=True)
    full_log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(backend_main, "ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "BACKEND_DIR", tmp_path / "data/backend")
    monkeypatch.setattr(backend_main, "ETF_STRATEGY_PATH", etf_path)
    monkeypatch.setattr(backend_main, "JOINQUANT_FULL_LOG_PATH", full_log_path)

    response = client.get("/api/v1/strategies/etf")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"]["source"] == "joinquant-pending"
    assert payload["meta"]["source_quality"] == "pending"
    assert payload["data"]["recommendations"] == []
    assert payload["data"]["holdings"] == []


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
    monkeypatch.setattr(backend_main, "PERFORMANCE_EVENTS_PATH", tmp_path / "data/backend/performance/strategy-events.jsonl")
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
    monkeypatch.setattr(backend_main, "run_live_data_refresh", lambda *args, **kwargs: (False, "offline in test"))

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


def test_static_hidden_performance_strategy_is_not_exposed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    client: TestClient,
) -> None:
    paths = patch_joinquant_paths(monkeypatch, tmp_path)
    write_live_benchmark_cache(paths["benchmarks"])
    write_static_performance_nav(paths["performance_nav"])

    response = client.get("/api/v1/performance?strategy=momentum&benchmark=none&from=2026-05-14&to=2026-05-15")

    assert response.status_code == 404
    assert "策略净值不存在" in response.text


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


def test_performance_hides_static_small_cap_and_personal_curves(
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

    assert response.status_code == 404
    assert "策略净值不存在" in response.text

    post_performance_snapshot(client, "jq-new-alpha-run-1", "2026-05-15T10:30:00+08:00", 100000)
    response = client.get("/api/v1/performance?strategy=jq-new-alpha&benchmark=none&from=2026-05-15&to=2026-05-15")

    assert response.status_code == 200, response.text
    payload = response.json()
    strategy_ids = {item["id"] for item in payload["data"]["strategies"]}
    assert "jq-new-alpha" in strategy_ids
    assert {"momentum", "small-cap-momentum", "personal-portfolio"}.isdisjoint(strategy_ids)
