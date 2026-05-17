from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, Field, ValidationError


class SchemaValidationError(ValueError):
    """Raised when a payload does not satisfy its API/storage contract."""

    def __init__(self, storage_path: str, missing_fields: list[str], errors: list[dict[str, Any]]):
        self.storage_path = storage_path
        self.missing_fields = missing_fields
        self.errors = errors
        super().__init__(f"payload validation failed for {storage_path}: {', '.join(missing_fields)}")


class ContractModel(BaseModel):
    class Config:
        extra = "allow"


class Meta(ContractModel):
    version: str
    source: str
    as_of: str
    trade_date: str
    timezone: str
    market_session: str
    run_id: str
    storage_path: str | None = None


class ApiPayload(ContractModel):
    meta: Meta


class DashboardOverviewData(ContractModel):
    account: dict[str, Any]
    market: dict[str, Any]
    decision: dict[str, Any]
    sentiment_gauge: dict[str, Any]
    heatmap: dict[str, Any]
    top_etfs: list[Any]
    sectors: list[Any]
    strategy_status: list[Any]
    alerts: list[Any]


class DashboardOverviewPayload(ApiPayload):
    data: DashboardOverviewData


class WatchlistGroup(ContractModel):
    name: str
    items: list[dict[str, Any]]


class WatchlistData(ContractModel):
    groups: list[WatchlistGroup]


class WatchlistPayload(ApiPayload):
    data: WatchlistData


class StrategyPickFactor(ContractModel):
    name: str
    value: float | int | str | None = None
    weight: float | int | None = None


class StrategyPickItem(ContractModel):
    symbol: str
    name: str
    score: float | int
    confidence: float | int | None = None
    factors: list[StrategyPickFactor] = Field(default_factory=list)
    tags: list[Any] = Field(default_factory=list)


class StrategyPicksData(ContractModel):
    strategy: str
    strategy_label: str
    trade_date: str
    status: str
    strategies: list[Any]
    items: list[StrategyPickItem]


class StrategyPicksPayload(ApiPayload):
    data: StrategyPicksData


class PortfolioHoldingsData(ContractModel):
    summary: dict[str, Any]
    holdings: list[dict[str, Any]]
    allocation: list[dict[str, Any]]
    quant_holdings: list[dict[str, Any]] = Field(default_factory=list)
    personal_holdings: list[dict[str, Any]] = Field(default_factory=list)
    quant_by_strategy: list[dict[str, Any]] = Field(default_factory=list)
    strategy_outputs: dict[str, Any] = Field(default_factory=dict)


class PortfolioHoldingsPayload(ApiPayload):
    data: PortfolioHoldingsData


class PerformanceData(ContractModel):
    strategy: str
    strategy_label: str
    benchmark: str | None = None
    benchmark_id: str | None = None
    strategies: list[Any]
    benchmarks: list[Any]
    equity_curve: list[dict[str, Any]]
    benchmark_curve: list[dict[str, Any]] = Field(default_factory=list)
    drawdowns: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    monthly_returns: list[dict[str, Any]] = Field(default_factory=list)
    annotations: list[Any] = Field(default_factory=list)


class PerformancePayload(ApiPayload):
    data: PerformanceData


class MarketHeatmapCell(ContractModel):
    symbol: str
    name: str
    sector: str
    price: float | int | None = None
    change_pct: float | int | None = None
    volume: float | int | None = None
    market_cap: float | int | str | None = None
    weight: float | int | None = None


class MarketHeatmapData(ContractModel):
    timeframe: str
    group_by: str
    updated_at: str
    cells: list[MarketHeatmapCell]


class MarketHeatmapPayload(ApiPayload):
    data: MarketHeatmapData


class BreadthData(ContractModel):
    summary: dict[str, Any]
    metrics: list[Any]
    industry_width: list[Any]
    heatmap_history: dict[str, Any]
    style: list[Any]
    distribution: list[Any]


class BreadthPayload(ApiPayload):
    data: BreadthData


class SentimentData(ContractModel):
    summary: dict[str, Any]
    latest_snapshot: dict[str, Any]
    brilliant_volatility: dict[str, Any]
    sentiment_trend: list[Any]
    brilliant_series: list[Any]
    surge_events: list[Any]
    gauges: list[Any]
    topics: list[Any]
    flows: list[Any]
    warnings: list[Any]


class SentimentPayload(ApiPayload):
    data: SentimentData


class MacroData(ContractModel):
    summary: dict[str, Any]
    rates: list[Any]
    fx: list[Any]
    risk_assets: list[Any]
    calendar: list[Any]
    observations: list[Any]


class MacroPayload(ApiPayload):
    data: MacroData


class JoinQuantEtfStrategyData(ContractModel):
    strategy: dict[str, Any]
    summary: dict[str, Any]
    recommendations: list[Any]
    holdings: list[Any]
    regime: dict[str, Any]
    events: list[Any]
    logs: list[Any] = Field(default_factory=list)


class JoinQuantEtfStrategyPayload(ApiPayload):
    data: JoinQuantEtfStrategyData


class SmallCapStrategyData(ContractModel):
    strategy: dict[str, Any]
    summary: dict[str, Any]
    signals: list[Any]
    holdings: list[Any]
    themes: list[Any]
    risk: dict[str, Any]
    events: list[Any] = Field(default_factory=list)
    logs: list[Any] = Field(default_factory=list)


class SmallCapStrategyPayload(ApiPayload):
    data: SmallCapStrategyData


class CryptoFundingStrategyData(ContractModel):
    strategy: dict[str, Any]
    summary: dict[str, Any]
    heartbeat: dict[str, Any]
    positions: list[Any] = Field(default_factory=list)
    pending_events: list[Any] = Field(default_factory=list)
    signals: list[Any] = Field(default_factory=list)
    trades: list[Any] = Field(default_factory=list)
    events: list[Any] = Field(default_factory=list)
    logs: list[Any] = Field(default_factory=list)


class CryptoFundingStrategyPayload(ApiPayload):
    data: CryptoFundingStrategyData


PayloadModel = TypeVar("PayloadModel", bound=BaseModel)


PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "/api/v1/dashboard/overview": DashboardOverviewPayload,
    "/api/v1/overview": DashboardOverviewPayload,
    "/api/v1/watchlist": WatchlistPayload,
    "/api/v1/strategies/picks": StrategyPicksPayload,
    "/api/v1/portfolio/holdings": PortfolioHoldingsPayload,
    "/api/v1/performance": PerformancePayload,
    "/api/v1/market/heatmap": MarketHeatmapPayload,
    "/api/v1/market/breadth": BreadthPayload,
    "/api/v1/market/sentiment": SentimentPayload,
    "/api/v1/macro": MacroPayload,
    "/api/v1/strategies/etf": JoinQuantEtfStrategyPayload,
    "/api/v1/strategies/small-cap": SmallCapStrategyPayload,
    "/api/v1/strategies/crypto-funding": CryptoFundingStrategyPayload,
}

LIVE_PAYLOAD_SCHEMAS: dict[str, type[BaseModel]] = {
    "overview": DashboardOverviewPayload,
    "watchlist": WatchlistPayload,
    "heatmap": MarketHeatmapPayload,
    "breadth": BreadthPayload,
    "sentiment": SentimentPayload,
    "macro": MacroPayload,
}


def _validate_model(model: type[PayloadModel], payload: dict[str, Any]) -> PayloadModel:
    if hasattr(model, "model_validate"):
        return model.model_validate(payload)  # type: ignore[attr-defined,no-any-return]
    return model.parse_obj(payload)  # type: ignore[attr-defined,no-any-return]


def _schema_for_model(model: type[BaseModel]) -> dict[str, Any]:
    if hasattr(model, "model_json_schema"):
        return model.model_json_schema()  # type: ignore[attr-defined,no-any-return]
    return model.schema()  # type: ignore[attr-defined,no-any-return]


def missing_fields_from_validation_error(exc: ValidationError) -> list[str]:
    fields: list[str] = []
    for error in exc.errors():
        error_type = str(error.get("type") or "")
        if error_type not in {"value_error.missing", "missing"}:
            continue
        loc = error.get("loc") or ()
        if isinstance(loc, (list, tuple)):
            fields.append(".".join(str(part) for part in loc))
        else:
            fields.append(str(loc))
    return fields


def validate_payload(model: type[PayloadModel], payload: dict[str, Any], storage_path: str) -> PayloadModel:
    try:
        return _validate_model(model, payload)
    except ValidationError as exc:
        missing_fields = missing_fields_from_validation_error(exc)
        if not missing_fields:
            missing_fields = ["<none>"]
        raise SchemaValidationError(storage_path, missing_fields, exc.errors()) from exc


def json_schema_bundle() -> dict[str, Any]:
    return {
        "title": "Quant Dashboard API payload schemas",
        "version": "1.0",
        "schemas": {
            name: _schema_for_model(model)
            for name, model in {
                "DashboardOverviewPayload": DashboardOverviewPayload,
                "WatchlistPayload": WatchlistPayload,
                "StrategyPicksPayload": StrategyPicksPayload,
                "PortfolioHoldingsPayload": PortfolioHoldingsPayload,
                "PerformancePayload": PerformancePayload,
                "MarketHeatmapPayload": MarketHeatmapPayload,
                "BreadthPayload": BreadthPayload,
                "SentimentPayload": SentimentPayload,
                "MacroPayload": MacroPayload,
                "JoinQuantEtfStrategyPayload": JoinQuantEtfStrategyPayload,
                "SmallCapStrategyPayload": SmallCapStrategyPayload,
                "CryptoFundingStrategyPayload": CryptoFundingStrategyPayload,
            }.items()
        },
    }
