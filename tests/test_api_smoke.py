from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
        ("post", "/api/v1/strategies/etf/signals/600519/confirm", {"action": "confirm"}),
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
