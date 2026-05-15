from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]

META_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["version", "source", "as_of", "trade_date", "timezone", "market_session", "run_id"],
    "properties": {
        "version": {"type": "string"},
        "source": {"type": "string"},
        "as_of": {"type": "string"},
        "trade_date": {"type": "string"},
        "timezone": {"type": "string"},
        "market_session": {"type": "string"},
        "run_id": {"type": "string"},
        "stale_seconds": {"type": ["integer", "number"]},
        "source_quality": {"type": "string"},
    },
    "additionalProperties": True,
}

BASE_PAYLOAD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["meta", "data"],
    "properties": {
        "meta": META_SCHEMA,
        "data": {"type": "object"},
    },
    "additionalProperties": False,
}

DATA_FIELD_TYPES: dict[str, dict[str, str]] = {
    "dashboard/overview.json": {
        "health": "object",
        "account": "object",
        "market": "object",
        "strategy_status": "array",
        "alerts": "array",
        "timeline": "array",
        "decision": "object",
        "sentiment_gauge": "object",
        "heatmap": "object",
        "top_etfs": "array",
        "sectors": "array",
    },
    "overview.json": {
        "health": "object",
        "account": "object",
        "market": "object",
        "strategy_status": "array",
        "alerts": "array",
        "timeline": "array",
        "decision": "object",
        "sentiment_gauge": "object",
        "heatmap": "object",
        "top_etfs": "array",
        "sectors": "array",
    },
    "watchlist/list.json": {"groups": "array"},
    "watchlist.json": {"groups": "array"},
    "strategies/picks.json": {
        "strategy": "string",
        "strategy_label": "string",
        "trade_date": "string",
        "status": "string",
        "count": "integer",
        "strategies": "array",
        "items": "array",
    },
    "strategies/etf.json": {
        "strategy": "object",
        "summary": "object",
        "recommendations": "array",
        "holdings": "array",
        "regime": "object",
        "events": "array",
        "logs": "array",
        "raw": "object",
    },
    "strategies/small-cap.json": {
        "strategy": "object",
        "summary": "object",
        "signals": "array",
        "holdings": "array",
        "themes": "array",
        "risk": "object",
        "events": "array",
        "logs": "array",
    },
    "portfolio/holdings.json": {"summary": "object", "holdings": "array", "allocation": "array"},
    "performance/net-values.json": {
        "default_strategy": "string",
        "default_benchmark": "string",
        "strategies": "object",
        "benchmarks": "object",
    },
    "performance/benchmarks-live.json": {"benchmarks": "object"},
    "performance/overview.json": {
        "strategy": "string",
        "strategy_label": "string",
        "benchmark": "string",
        "equity_curve": "array",
        "benchmark_curve": "array",
        "drawdowns": "array",
        "metrics": "object",
        "monthly_returns": "array",
        "annotations": "array",
    },
    "market/heatmap.json": {"timeframe": "string", "group_by": "string", "updated_at": "string", "cells": "array"},
    "heatmap.json": {"timeframe": "string", "group_by": "string", "updated_at": "string", "cells": "array"},
    "market/sectors.json": {"sectors": "array"},
    "sectors.json": {"sectors": "array"},
    "market/etf-rankings.json": {"period": "string", "items": "array"},
    "etf-rankings.json": {"period": "string", "items": "array"},
    "market/breadth.json": {
        "source_algorithm": "object",
        "summary": "object",
        "metrics": "array",
        "industry_width": "array",
        "heatmap_history": "object",
        "style": "array",
        "distribution": "array",
    },
    "breadth.json": {
        "source_algorithm": "object",
        "summary": "object",
        "metrics": "array",
        "industry_width": "array",
        "heatmap_history": "object",
        "style": "array",
        "distribution": "array",
    },
    "market/sentiment.json": {
        "source_algorithm": "object",
        "summary": "object",
        "latest_snapshot": "object",
        "brilliant_volatility": "object",
        "sentiment_trend": "array",
        "brilliant_series": "array",
        "surge_events": "array",
        "gauges": "array",
        "topics": "array",
        "flows": "array",
        "warnings": "array",
    },
    "sentiment.json": {
        "source_algorithm": "object",
        "summary": "object",
        "latest_snapshot": "object",
        "brilliant_volatility": "object",
        "sentiment_trend": "array",
        "brilliant_series": "array",
        "surge_events": "array",
        "gauges": "array",
        "topics": "array",
        "flows": "array",
        "warnings": "array",
    },
    "macro.json": {
        "summary": "object",
        "rates": "array",
        "fx": "array",
        "risk_assets": "array",
        "calendar": "array",
        "observations": "array",
    },
}


def data_schema_for(path: Path) -> dict[str, Any]:
    rel = path.relative_to(ROOT).as_posix()
    key = rel.removeprefix("data/backend/").removeprefix("data/live/")
    field_types = DATA_FIELD_TYPES[key]
    return {
        "type": "object",
        "required": list(field_types),
        "properties": {name: {"type": json_type} for name, json_type in field_types.items()},
        "additionalProperties": True,
    }


def iter_contract_files() -> list[Path]:
    files = [*ROOT.glob("data/backend/**/*.json"), *ROOT.glob("data/live/*.json")]
    return sorted(files)


@pytest.mark.parametrize("path", iter_contract_files(), ids=lambda path: path.relative_to(ROOT).as_posix())
def test_data_file_matches_contract(path: Path) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator(BASE_PAYLOAD_SCHEMA).validate(payload)
    Draft202012Validator(data_schema_for(path)).validate(payload["data"])
