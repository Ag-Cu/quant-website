from __future__ import annotations

import csv
import json
import hmac
import io
import math
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.schemas import PAYLOAD_SCHEMAS, SchemaValidationError, validate_payload


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BACKEND_DIR = DATA_DIR / "backend"
LIVE_DIR = DATA_DIR / "live"
CONFIG_DIR = DATA_DIR / "config"
WATCHLIST_CONFIG_PATH = CONFIG_DIR / "watchlist.json"
ACTION_LOG_PATH = BACKEND_DIR / "actions" / "action-log.jsonl"
EXPORT_DIR = BACKEND_DIR / "exports"
ETF_STRATEGY_PATH = BACKEND_DIR / "strategies" / "etf.json"
SMALL_CAP_STRATEGY_PATH = BACKEND_DIR / "strategies" / "small-cap.json"
JOINQUANT_SIGNAL_LOG_PATH = BACKEND_DIR / "strategies" / "joinquant-signals.jsonl"
JOINQUANT_FULL_LOG_PATH = BACKEND_DIR / "strategies" / "joinquant-full-logs.jsonl"
PERFORMANCE_NAV_PATH = BACKEND_DIR / "performance" / "net-values.json"
PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH = BACKEND_DIR / "performance" / "joinquant-snapshots.jsonl"
PERFORMANCE_JOINQUANT_NAV_PATH = BACKEND_DIR / "performance" / "joinquant-nav.jsonl"
PERFORMANCE_BENCHMARK_NAV_PATH = BACKEND_DIR / "performance" / "benchmarks-live.json"
STRATEGY_PICKS_PARTITION_DIR = BACKEND_DIR / "strategies" / "picks"
MAX_STRATEGY_LOG_LINES = 1000
ETF_INLINE_LOG_LINES = 1000
PERFORMANCE_STALE_SECONDS = 900
BENCHMARK_CACHE_SECONDS = 3_600
REAL_BENCHMARKS = {
    "CSI300": {"label": "沪深300", "secid": "1.000300", "sina_symbol": "sh000300", "source_name": "东方财富行情中心/新浪财经"},
    "CSI1000": {"label": "中证1000", "secid": "1.000852", "sina_symbol": "sh000852", "source_name": "东方财富行情中心/新浪财经"},
    "CHINEXT": {"label": "创业板指", "secid": "0.399006", "sina_symbol": "sz399006", "source_name": "东方财富行情中心/新浪财经"},
}
STATIC_PAGES = {
    "/": "index.html",
    "/index.html": "index.html",
    "/watchlist.html": "watchlist.html",
    "/picks.html": "picks.html",
    "/holdings.html": "holdings.html",
    "/performance.html": "performance.html",
    "/etf.html": "etf.html",
    "/small-cap.html": "small-cap.html",
    "/breadth.html": "breadth.html",
    "/sentiment.html": "sentiment.html",
    "/macro.html": "macro.html",
}
STATIC_FILES = {"app.js", "styles.css"}
HK_TZ = ZoneInfo("Asia/Hong_Kong")
SourceKind = Literal["realtime", "daily", "strategy", "portfolio", "performance"]


@dataclass(frozen=True)
class EndpointSpec:
    path: str
    storage_key: str
    refresh_policy: SourceKind
    refresh_seconds: int
    description: str
    live_key: str | None = None

    @property
    def backend_path(self) -> Path:
        return BACKEND_DIR / f"{self.storage_key}.json"

    @property
    def live_path(self) -> Path | None:
        if not self.live_key:
            return None
        return LIVE_DIR / f"{self.live_key}.json"


ENDPOINTS: dict[str, EndpointSpec] = {
    "/api/v1/dashboard/overview": EndpointSpec(
        "/api/v1/dashboard/overview",
        "dashboard/overview",
        "realtime",
        30,
        "首页聚合数据，盘中需要实时刷新。",
        live_key="overview",
    ),
    "/api/v1/watchlist": EndpointSpec(
        "/api/v1/watchlist",
        "watchlist/list",
        "realtime",
        15,
        "自选股行情和右侧明细，盘中实时刷新。",
        live_key="watchlist",
    ),
    "/api/v1/strategies/picks": EndpointSpec(
        "/api/v1/strategies/picks",
        "strategies/picks",
        "daily",
        86_400,
        "每日选股结果，收盘后或策略任务完成后更新。",
    ),
    "/api/v1/portfolio/holdings": EndpointSpec(
        "/api/v1/portfolio/holdings",
        "portfolio/holdings",
        "portfolio",
        30,
        "持仓价格和盈亏盘中刷新，交易记录由账户同步任务写入。",
    ),
    "/api/v1/performance": EndpointSpec(
        "/api/v1/performance",
        "performance/net-values",
        "daily",
        30,
        "历史绩效曲线，由聚宽 webhook 实盘账户快照实时更新。",
    ),
    "/api/v1/market/heatmap": EndpointSpec(
        "/api/v1/market/heatmap",
        "market/heatmap",
        "realtime",
        30,
        "市场热力图，盘中实时刷新。",
        live_key="heatmap",
    ),
    "/api/v1/market/sectors": EndpointSpec(
        "/api/v1/market/sectors",
        "market/sectors",
        "realtime",
        60,
        "板块表现，盘中实时刷新。",
        live_key="sectors",
    ),
    "/api/v1/market/etf-rankings": EndpointSpec(
        "/api/v1/market/etf-rankings",
        "market/etf-rankings",
        "realtime",
        60,
        "ETF 排名，盘中实时刷新。",
        live_key="etf-rankings",
    ),
    "/api/v1/strategies/etf": EndpointSpec(
        "/api/v1/strategies/etf",
        "strategies/etf",
        "strategy",
        300,
        "ETF 策略运行状态和信号，策略任务刷新。",
    ),
    "/api/v1/strategies/small-cap": EndpointSpec(
        "/api/v1/strategies/small-cap",
        "strategies/small-cap",
        "strategy",
        300,
        "小盘股策略运行状态和信号，策略任务刷新。",
    ),
    "/api/v1/market/breadth": EndpointSpec(
        "/api/v1/market/breadth",
        "market/breadth",
        "realtime",
        60,
        "市场宽度，盘中实时或分钟级刷新。",
        live_key="breadth",
    ),
    "/api/v1/market/sentiment": EndpointSpec(
        "/api/v1/market/sentiment",
        "market/sentiment",
        "realtime",
        60,
        "散户情绪和耀眼波动，盘中实时或分钟级刷新。",
        live_key="sentiment",
    ),
    "/api/v1/macro": EndpointSpec(
        "/api/v1/macro",
        "macro",
        "daily",
        3_600,
        "宏观指标，小时级或日频刷新。",
        live_key="macro",
    ),
    "/api/v1/overview": EndpointSpec(
        "/api/v1/overview",
        "dashboard/overview",
        "realtime",
        30,
        "旧首页兼容接口。",
        live_key="overview",
    ),
}


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_csv(name: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


app = FastAPI(title="Quant Dashboard API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=env_csv("QUANT_ALLOWED_ORIGINS"),
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


def now_hk() -> datetime:
    return datetime.now(HK_TZ).replace(microsecond=0)


def market_session(now: datetime | None = None) -> str:
    current = now or now_hk()
    minutes = current.hour * 60 + current.minute
    if current.weekday() >= 5:
        return "closed"
    if 9 * 60 + 30 <= minutes <= 11 * 60 + 30 or 13 * 60 <= minutes <= 15 * 60:
        return "open"
    if 11 * 60 + 30 < minutes < 13 * 60:
        return "lunch"
    if minutes < 9 * 60 + 30:
        return "preopen"
    return "closed"


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except FileNotFoundError as exc:
        storage_path = str(path.relative_to(ROOT))
        raise HTTPException(
            status_code=503,
            detail={"message": "数据文件不存在", "storage_path": storage_path, "missing_fields": []},
        ) from exc
    except json.JSONDecodeError as exc:
        storage_path = str(path.relative_to(ROOT))
        raise HTTPException(
            status_code=500,
            detail={"message": "数据文件格式错误", "storage_path": storage_path, "missing_fields": []},
        ) from exc
    if not isinstance(payload, dict):
        storage_path = str(path.relative_to(ROOT))
        raise HTTPException(
            status_code=500,
            detail={"message": "数据文件根节点必须是对象", "storage_path": storage_path, "missing_fields": []},
        )
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
        tmp_name = file.name
    os.replace(tmp_name, path)


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        file.write("\n")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_jsonl_atomic(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            file.write("\n")
        tmp_name = file.name
    os.replace(tmp_name, path)


def read_jsonl_tail(path: Path, limit: int = 100) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        lines = file.readlines()[-max(0, limit):]
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def normalize_log_level(value: Any) -> str:
    level = str(value or "info").strip().lower()
    if level in {"warning", "warn", "error", "debug", "info"}:
        return "warning" if level == "warn" else level
    return "info"


def normalize_strategy_logs(
    payload: dict[str, Any],
    received_at: str,
    run_id: str,
    trade_date: str,
    strategy_id: str | None = None,
) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    raw_logs = data.get("logs") or data.get("log_lines") or data.get("full_logs") or []
    if isinstance(raw_logs, str):
        raw_logs = raw_logs.splitlines()
    if not isinstance(raw_logs, list):
        return []

    strategy = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    log_strategy_id = str(strategy_id or data.get("strategy_id") or strategy.get("id") or "").strip()

    rows: list[dict[str, Any]] = []
    for index, item in enumerate(raw_logs[-MAX_STRATEGY_LOG_LINES:]):
        if isinstance(item, dict):
            message = str(item.get("message") or item.get("text") or item.get("line") or "")
            timestamp = str(item.get("time") or item.get("timestamp") or item.get("at") or received_at)
            stage = str(item.get("stage") or item.get("label") or "")
            level = normalize_log_level(item.get("level"))
        else:
            message = str(item)
            timestamp = received_at
            stage = ""
            level = "info"
        if not message.strip():
            continue
        rows.append(
            {
                "received_at": received_at,
                "run_id": run_id,
                "trade_date": trade_date,
                "strategy_id": log_strategy_id,
                "sequence": index + 1,
                "time": timestamp,
                "stage": stage,
                "level": level,
                "message": message,
            }
        )
    return rows


def append_strategy_logs(
    payload: dict[str, Any],
    received_at: str,
    run_id: str,
    trade_date: str,
    strategy_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = normalize_strategy_logs(payload, received_at, run_id, trade_date, strategy_id)
    for row in rows:
        append_jsonl(JOINQUANT_FULL_LOG_PATH, row)
    return rows


def get_recent_strategy_logs(
    limit: int = 80,
    trade_date: str | None = None,
    run_id: str | None = None,
    strategy_id: str | None = None,
) -> list[dict[str, Any]]:
    rows = read_jsonl_tail(JOINQUANT_FULL_LOG_PATH, max(limit * 4, limit))
    if trade_date:
        rows = [row for row in rows if row.get("trade_date") == trade_date]
    if run_id:
        rows = [row for row in rows if row.get("run_id") == run_id]
    if strategy_id:
        rows = [
            row
            for row in rows
            if row.get("strategy_id") == strategy_id
            or (strategy_id == "joinquant-wufu-etf-v43" and not row.get("strategy_id"))
        ]
    return rows[-limit:]


def redact_secret_fields(payload: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in {"token", "secret", "password", "authorization"}:
            redacted[key] = "***"
        elif isinstance(value, dict):
            redacted[key] = redact_secret_fields(value)
        elif isinstance(value, list):
            redacted[key] = [redact_secret_fields(item) if isinstance(item, dict) else item for item in value]
        else:
            redacted[key] = value
    return redacted


def get_joinquant_webhook_token() -> str:
    token = os.getenv("JOINQUANT_WEBHOOK_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="服务端未配置 JOINQUANT_WEBHOOK_TOKEN")
    return token


def verify_joinquant_token(request: Request, payload: dict[str, Any]) -> None:
    expected = get_joinquant_webhook_token()
    provided = (
        request.headers.get("x-webhook-token")
        or request.headers.get("x-joinquant-token")
        or str(payload.get("token") or "")
    ).strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="JoinQuant webhook token 不正确")


def to_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number:
        return default
    return number


def to_int(value: Any, default: int = 0) -> int:
    number = to_float(value)
    if number is None:
        return default
    return int(number)


def parse_hk_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        text = text.replace("Z", "+00:00")
        parsed = None
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.fromisoformat(text) if fmt.startswith("%Y-%m-%dT") else datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=HK_TZ)
    return parsed.astimezone(HK_TZ).replace(microsecond=0)


def iso_hk(value: Any, fallback: datetime | None = None) -> str:
    parsed = parse_hk_datetime(value) or fallback or now_hk()
    return parsed.astimezone(HK_TZ).replace(microsecond=0).isoformat()


def seconds_since(value: Any, now: datetime | None = None) -> int | None:
    parsed = parse_hk_datetime(value)
    if parsed is None:
        return None
    return max(0, int(((now or now_hk()) - parsed).total_seconds()))


def stable_json_hash(payload: dict[str, Any]) -> str:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def cn_code_parts(raw_symbol: Any) -> tuple[str, str]:
    raw = str(raw_symbol or "").strip().upper()
    if not raw:
        return "", ""
    if "." in raw:
        code, suffix = raw.split(".", 1)
        market = {"XSHG": "SH", "XSHE": "SZ", "SS": "SH", "SH": "SH", "SZ": "SZ"}.get(suffix, suffix)
        return code, market
    if raw.startswith(("SH", "SZ")) and raw[2:].isdigit():
        return raw[2:], raw[:2]
    market = infer_cn_market(raw) if raw.isdigit() else ""
    return raw, market


def normalize_action(action: Any) -> tuple[str, str]:
    raw = str(action or "watch").strip().lower()
    mapping = {
        "buy": ("buy", "买入"),
        "add": ("add", "加仓"),
        "hold": ("hold", "持有"),
        "watch": ("watch", "观察"),
        "reduce": ("reduce", "减仓"),
        "trim": ("trim", "减仓"),
        "sell": ("sell", "卖出"),
        "stop": ("stop", "止损"),
        "defensive": ("hold", "防御"),
        "cash": ("watch", "空仓"),
        "买入": ("buy", "买入"),
        "加仓": ("add", "加仓"),
        "持有": ("hold", "持有"),
        "观察": ("watch", "观察"),
        "减仓": ("reduce", "减仓"),
        "卖出": ("sell", "卖出"),
        "止损": ("stop", "止损"),
        "防御": ("hold", "防御"),
        "空仓": ("watch", "空仓"),
    }
    return mapping.get(raw, (raw or "watch", str(action or "观察")))


def normalize_joinquant_signal(item: dict[str, Any], rank: int) -> dict[str, Any]:
    symbol, market = cn_code_parts(item.get("symbol") or item.get("code") or item.get("etf"))
    action, label = normalize_action(item.get("action") or item.get("signal"))
    score = to_float(item.get("score") or item.get("momentum_score"))
    if score is None:
        score = 0
    if abs(score) <= 10:
        score = score * 20
    return {
        "symbol": symbol,
        "name": str(item.get("name") or item.get("etf_name") or symbol or "--"),
        "market": market,
        "action": action,
        "action_label": str(item.get("action_label") or label),
        "rank": to_int(item.get("rank"), rank),
        "score": round(max(0, min(100, score))),
        "suggested_weight_pct": to_float(
            item.get("suggested_weight_pct")
            or item.get("target_weight_pct")
            or item.get("weight_pct"),
            0,
        ),
        "current_weight_pct": to_float(item.get("current_weight_pct"), 0),
        "last_price": to_float(item.get("last_price") or item.get("current_price")),
        "change_pct": to_float(item.get("change_pct") or item.get("day_change_pct"), 0),
        "volume_ratio": to_float(item.get("volume_ratio")),
        "trend": item.get("trend") if isinstance(item.get("trend"), list) else [],
        "reason": str(item.get("reason") or item.get("detail") or item.get("explanation") or ""),
    }


def normalize_joinquant_holding(item: dict[str, Any], total_value: float | None) -> dict[str, Any]:
    symbol, _market = cn_code_parts(item.get("symbol") or item.get("code") or item.get("etf"))
    market_value = to_float(item.get("market_value") or item.get("value"))
    quantity = to_float(item.get("quantity") or item.get("amount") or item.get("total_amount") or item.get("shares"))
    weight_pct = to_float(item.get("weight_pct"))
    last_price = to_float(item.get("last_price") or item.get("price"))
    if market_value is None and quantity is not None and last_price is not None:
        market_value = quantity * last_price
    if weight_pct is None and market_value is not None and total_value:
        weight_pct = market_value / total_value * 100
    cost = to_float(item.get("cost") or item.get("avg_cost"))
    pnl_pct = to_float(item.get("pnl_pct"))
    if pnl_pct is None and cost and last_price:
        pnl_pct = (last_price / cost - 1) * 100
    pnl_amount = to_float(item.get("pnl_amount") or item.get("profit_loss"))
    if pnl_amount is None and cost is not None and last_price is not None and quantity is not None:
        pnl_amount = (last_price - cost) * quantity
    return {
        "symbol": symbol,
        "name": str(item.get("name") or item.get("etf_name") or symbol or "--"),
        "weight_pct": weight_pct or 0,
        "cost": cost,
        "avg_cost": cost,
        "last_price": last_price,
        "quantity": quantity,
        "market_value": market_value,
        "pnl_amount": pnl_amount,
        "day_change_pct": to_float(item.get("day_change_pct") or item.get("change_pct"), 0),
        "pnl_pct": pnl_pct or 0,
    }


def normalize_joinquant_event(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "time": str(item.get("time") or item.get("at") or now_hk().strftime("%H:%M")),
        "label": str(item.get("label") or item.get("event") or item.get("message") or "策略更新"),
        "detail": str(item.get("detail") or ""),
        "status": str(item.get("status") or "done"),
    }


def build_etf_strategy_payload_from_joinquant(payload: dict[str, Any]) -> dict[str, Any]:
    now = now_hk()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    strategy_input = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    summary_input = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    regime_input = data.get("regime") if isinstance(data.get("regime"), dict) else {}
    portfolio_input = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else {}

    raw_signals = data.get("recommendations") or data.get("signals") or data.get("targets") or []
    if not isinstance(raw_signals, list):
        raw_signals = []
    recommendations = [
        normalize_joinquant_signal(item, index + 1)
        for index, item in enumerate(raw_signals)
        if isinstance(item, dict)
    ]

    raw_holdings = data.get("holdings") or data.get("positions") or []
    if not isinstance(raw_holdings, list):
        raw_holdings = []
    total_value = to_float(portfolio_input.get("total_value") or data.get("total_value"))
    holdings = [
        normalize_joinquant_holding(item, total_value)
        for item in raw_holdings
        if isinstance(item, dict)
    ]

    raw_events = data.get("events") or []
    if not isinstance(raw_events, list):
        raw_events = []
    events = [
        normalize_joinquant_event(item)
        for item in raw_events
        if isinstance(item, dict)
    ]
    if not events:
        events = [{"time": now.strftime("%H:%M"), "label": "收到聚宽策略信号", "detail": "", "status": "done"}]

    buy_count = sum(1 for row in recommendations if row.get("action") in {"buy", "add"})
    watch_count = sum(1 for row in recommendations if row.get("action") == "watch")
    current_exposure_pct = to_float(summary_input.get("current_exposure_pct") or portfolio_input.get("current_exposure_pct"))
    if current_exposure_pct is None:
        current_exposure_pct = sum(to_float(item.get("weight_pct"), 0) or 0 for item in holdings)
    target_exposure_pct = to_float(summary_input.get("target_exposure_pct"))
    if target_exposure_pct is None:
        target_exposure_pct = sum(to_float(item.get("suggested_weight_pct"), 0) or 0 for item in recommendations)

    risk_state = str(
        strategy_input.get("risk_state")
        or data.get("risk_state")
        or regime_input.get("label")
        or ""
    )
    filter_name = str(strategy_input.get("current_filter") or data.get("current_filter") or "")
    drawdown_guard = str(strategy_input.get("drawdown_guard") or ("震荡期" if "震荡" in risk_state else "未触发"))
    if filter_name:
        drawdown_guard = f"{drawdown_guard} / {filter_name}"

    regime_factors = regime_input.get("factors") if isinstance(regime_input.get("factors"), list) else []
    normalized_factors = []
    for item in regime_factors:
        if isinstance(item, dict):
            normalized_factors.append(
                {
                    "name": str(item.get("name") or "--"),
                    "value": to_float(item.get("value"), 0),
                    "detail": str(item.get("detail") or ""),
                }
            )
    if not normalized_factors:
        normalized_factors = [
            {"name": "信号数量", "value": min(100, len(recommendations) * 20), "detail": f"{len(recommendations)} 个候选"},
            {"name": "目标仓位", "value": target_exposure_pct or 0, "detail": "聚宽策略输出"},
            {"name": "当前仓位", "value": current_exposure_pct or 0, "detail": "聚宽账户状态"},
        ]

    status = str(strategy_input.get("status") or data.get("status") or "running")
    trade_date = str(data.get("trade_date") or now.strftime("%Y-%m-%d"))
    as_of = str(data.get("as_of") or now.isoformat())
    run_id = str(data.get("run_id") or f"joinquant-etf-{now.strftime('%Y%m%d-%H%M%S')}")
    latest_logs = normalize_strategy_logs(payload, now.isoformat(), run_id, trade_date, "joinquant-wufu-etf-v43")[-ETF_INLINE_LOG_LINES:]

    return {
        "meta": {
            "version": "1.0",
            "source": "joinquant",
            "as_of": as_of,
            "trade_date": trade_date,
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(now),
            "run_id": run_id,
        },
        "data": {
            "strategy": {
                "id": str(strategy_input.get("id") or data.get("strategy_id") or "joinquant-etf-rotation"),
                "name": str(strategy_input.get("name") or data.get("strategy_name") or "聚宽 ETF 轮动"),
                "status": status,
                "rebalance_time": str(strategy_input.get("rebalance_time") or data.get("rebalance_time") or now.strftime("%H:%M")),
                "risk_budget_pct": to_float(strategy_input.get("risk_budget_pct"), target_exposure_pct or 0),
                "cash_weight_pct": to_float(strategy_input.get("cash_weight_pct"), max(0, 100 - (target_exposure_pct or 0))),
                "drawdown_guard": drawdown_guard,
                "decision_title": str(strategy_input.get("decision_title") or data.get("decision_title") or "聚宽策略已更新"),
                "decision_detail": str(
                    strategy_input.get("decision_detail")
                    or data.get("decision_detail")
                    or f"收到 {len(recommendations)} 个目标信号，当前模式 {risk_state or filter_name or '正常'}。"
                ),
                "decision_tone": str(strategy_input.get("decision_tone") or data.get("decision_tone") or ("warning" if "震荡" in risk_state else "blue")),
            },
            "summary": {
                "buy_count": to_int(summary_input.get("buy_count"), buy_count),
                "watch_count": to_int(summary_input.get("watch_count"), watch_count),
                "target_exposure_pct": target_exposure_pct or 0,
                "current_exposure_pct": current_exposure_pct or 0,
                "day_pnl_pct": to_float(summary_input.get("day_pnl_pct") or portfolio_input.get("day_pnl_pct"), 0),
                "week_pnl_pct": to_float(summary_input.get("week_pnl_pct"), 0),
                "month_pnl_pct": to_float(summary_input.get("month_pnl_pct"), 0),
                "max_drawdown_pct": to_float(summary_input.get("max_drawdown_pct") or data.get("max_drawdown_pct"), 0),
            },
            "recommendations": recommendations,
            "holdings": holdings,
            "regime": {
                "label": str(regime_input.get("label") or risk_state or filter_name or "策略状态"),
                "score": to_float(regime_input.get("score"), 66 if "正常" in (risk_state + filter_name) else 50),
                "factors": normalized_factors,
            },
            "events": events,
            "logs": latest_logs,
            "raw": {
                "provider": "joinquant",
                "received_at": now.isoformat(),
            },
        },
    }


def normalize_small_cap_signal(item: dict[str, Any], rank: int, default_weight_pct: float) -> dict[str, Any]:
    symbol, _market = cn_code_parts(item.get("symbol") or item.get("code") or item.get("stock"))
    action, label = normalize_action(item.get("signal") or item.get("action"))
    score = to_float(item.get("score") or item.get("rank_score"), max(0, 100 - (rank - 1) * 6))
    if score is None:
        score = 0
    if abs(score) <= 10:
        score = score * 10
    last_price = to_float(item.get("last_price") or item.get("price"))
    suggested_range = str(item.get("suggested_range") or item.get("range") or "")
    if not suggested_range and last_price:
        suggested_range = f"{last_price:.2f}"
    return {
        "symbol": symbol,
        "name": str(item.get("name") or symbol or "--"),
        "theme": str(item.get("theme") or item.get("industry") or item.get("sector") or "--"),
        "signal": action,
        "signal_label": str(item.get("signal_label") or item.get("action_label") or label),
        "score": round(max(0, min(100, score))),
        "suggested_range": suggested_range or "--",
        "last_price": last_price,
        "change_pct": to_float(item.get("change_pct") or item.get("day_change_pct"), 0),
        "risk": str(item.get("risk") or "mid"),
        "liquidity": str(item.get("liquidity") or "正常"),
        "invalidation": str(item.get("invalidation") or item.get("stop_policy") or "触发止损或风控条件"),
        "suggested_weight_pct": to_float(item.get("suggested_weight_pct") or item.get("target_weight_pct"), default_weight_pct),
    }


def normalize_small_cap_holding(item: dict[str, Any], total_value: float | None, now: datetime) -> dict[str, Any]:
    symbol, _market = cn_code_parts(item.get("symbol") or item.get("code") or item.get("stock"))
    market_value = to_float(item.get("market_value") or item.get("value"))
    quantity = to_float(item.get("quantity") or item.get("amount") or item.get("total_amount") or item.get("shares"))
    weight_pct = to_float(item.get("weight_pct"))
    last_price = to_float(item.get("last_price") or item.get("price"))
    if market_value is None and quantity is not None and last_price is not None:
        market_value = quantity * last_price
    if weight_pct is None and market_value is not None and total_value:
        weight_pct = market_value / total_value * 100
    cost = to_float(item.get("cost") or item.get("avg_cost"))
    pnl_pct = to_float(item.get("pnl_pct"))
    if pnl_pct is None and cost and last_price:
        pnl_pct = (last_price / cost - 1) * 100
    pnl_amount = to_float(item.get("pnl_amount") or item.get("profit_loss"))
    if pnl_amount is None and cost is not None and last_price is not None and quantity is not None:
        pnl_amount = (last_price - cost) * quantity
    holding_days = to_int(item.get("holding_days"), 0)
    entry_date = str(item.get("entry_date") or "")
    if not holding_days and entry_date:
        try:
            holding_days = max(0, (now.date() - date.fromisoformat(entry_date[:10])).days)
        except ValueError:
            holding_days = 0
    return {
        "symbol": symbol,
        "name": str(item.get("name") or symbol or "--"),
        "theme": str(item.get("theme") or item.get("industry") or item.get("sector") or "--"),
        "weight_pct": weight_pct or 0,
        "cost": cost,
        "avg_cost": cost,
        "last_price": last_price,
        "quantity": quantity,
        "market_value": market_value,
        "pnl_amount": pnl_amount,
        "day_change_pct": to_float(item.get("day_change_pct") or item.get("change_pct"), 0),
        "pnl_pct": pnl_pct or 0,
        "holding_days": holding_days,
    }


def small_cap_theme_rows(signals: list[dict[str, Any]], holdings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exposure: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in holdings:
        theme = str(row.get("theme") or "--")
        exposure[theme] = exposure.get(theme, 0) + (to_float(row.get("weight_pct"), 0) or 0)
    for row in signals:
        theme = str(row.get("theme") or "--")
        counts[theme] = counts.get(theme, 0) + 1
        exposure.setdefault(theme, 0)
    return [
        {
            "name": theme,
            "exposure_pct": round(weight, 2),
            "breadth_pct": min(100, max(0, counts.get(theme, 0) * 12 + weight)),
        }
        for theme, weight in sorted(exposure.items(), key=lambda item: item[1], reverse=True)[:8]
    ]


def build_small_cap_strategy_payload_from_joinquant(payload: dict[str, Any]) -> dict[str, Any]:
    now = now_hk()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    strategy_input = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    summary_input = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    risk_input = data.get("risk") if isinstance(data.get("risk"), dict) else {}
    portfolio_input = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else {}
    total_value = to_float(portfolio_input.get("total_value") or data.get("total_value"))

    stock_num = max(1, to_int(strategy_input.get("stock_num") or data.get("stock_num"), 6))
    default_weight_pct = round(100 / stock_num, 2)
    raw_signals = data.get("signals") or data.get("recommendations") or data.get("targets") or []
    if not isinstance(raw_signals, list):
        raw_signals = []
    signals = [
        normalize_small_cap_signal(item, index + 1, default_weight_pct)
        for index, item in enumerate(raw_signals)
        if isinstance(item, dict)
    ]

    raw_holdings = data.get("holdings") or data.get("positions") or []
    if not isinstance(raw_holdings, list):
        raw_holdings = []
    holdings = [
        normalize_small_cap_holding(item, total_value, now)
        for item in raw_holdings
        if isinstance(item, dict)
    ]

    raw_events = data.get("events") or []
    if not isinstance(raw_events, list):
        raw_events = []
    events = [normalize_joinquant_event(item) for item in raw_events if isinstance(item, dict)]

    buy_count = sum(1 for row in signals if row.get("signal") in {"buy", "add"})
    hold_count = len(holdings)
    exposure_pct = to_float(summary_input.get("exposure_pct") or portfolio_input.get("current_exposure_pct"))
    if exposure_pct is None:
        exposure_pct = sum(to_float(item.get("weight_pct"), 0) or 0 for item in holdings)
    trade_date = str(data.get("trade_date") or now.strftime("%Y-%m-%d"))
    as_of = str(data.get("as_of") or now.isoformat())
    run_id = str(data.get("run_id") or f"joinquant-small-cap-{now.strftime('%Y%m%d-%H%M%S')}")
    latest_logs = normalize_strategy_logs(payload, now.isoformat(), run_id, trade_date, "small-cap-momentum")[-ETF_INLINE_LOG_LINES:]
    decision_title = str(strategy_input.get("decision_title") or data.get("decision_title") or "小市值策略已更新")
    decision_detail = str(
        strategy_input.get("decision_detail")
        or data.get("decision_detail")
        or f"目标 {len(signals)} 只，持仓 {hold_count} 只，仓位 {round(exposure_pct or 0, 1)}%。"
    )

    return {
        "meta": {
            "version": "1.0",
            "source": "joinquant",
            "as_of": as_of,
            "trade_date": trade_date,
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(now),
            "run_id": run_id,
        },
        "data": {
            "strategy": {
                "id": "small-cap-momentum",
                "name": str(strategy_input.get("name") or data.get("strategy_name") or "涨停基因小市值轮动"),
                "status": str(strategy_input.get("status") or data.get("status") or "running"),
                "universe_size": to_int(strategy_input.get("universe_size") or data.get("universe_size"), 0),
                "candidate_count": to_int(strategy_input.get("candidate_count") or data.get("candidate_count"), len(signals)),
                "max_position_pct": to_float(strategy_input.get("max_position_pct"), default_weight_pct),
                "stop_policy": str(
                    strategy_input.get("stop_policy")
                    or data.get("stop_policy")
                    or f"个股止损 {round((1 - to_float(data.get('stoploss_limit'), 0.91)) * 100)}% / 大盘趋势止损"
                ),
                "decision_title": decision_title,
                "decision_detail": decision_detail,
                "decision_tone": str(strategy_input.get("decision_tone") or data.get("decision_tone") or "blue"),
            },
            "summary": {
                "signal_count": to_int(summary_input.get("signal_count"), len(signals)),
                "buy_count": to_int(summary_input.get("buy_count"), buy_count),
                "hold_count": to_int(summary_input.get("hold_count"), hold_count),
                "exposure_pct": exposure_pct or 0,
                "day_pnl_pct": to_float(summary_input.get("day_pnl_pct") or portfolio_input.get("day_pnl_pct"), 0),
                "floating_pnl_pct": to_float(summary_input.get("floating_pnl_pct") or portfolio_input.get("floating_pnl_pct"), 0),
                "turnover_pct": to_float(summary_input.get("turnover_pct"), 0),
            },
            "signals": signals,
            "holdings": holdings,
            "themes": data.get("themes") if isinstance(data.get("themes"), list) else small_cap_theme_rows(signals, holdings),
            "risk": {
                "liquidity_pass_pct": to_float(risk_input.get("liquidity_pass_pct"), 100),
                "concentration_pct": to_float(risk_input.get("concentration_pct"), max((to_float(row.get("weight_pct"), 0) or 0 for row in holdings), default=0)),
                "stop_watch_count": to_int(risk_input.get("stop_watch_count"), 0),
                "volatility_score": to_float(risk_input.get("volatility_score"), 50),
            },
            "events": events or [{"time": now.strftime("%H:%M"), "label": decision_title, "detail": decision_detail, "status": "done"}],
            "logs": latest_logs,
        },
    }


def joinquant_strategy_target(payload: dict[str, Any]) -> tuple[str, str, Path, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    strategy = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    raw_id = str(data.get("strategy_id") or strategy.get("id") or "").strip()
    raw_name = str(data.get("strategy_name") or strategy.get("name") or "").strip()
    text = f"{raw_id} {raw_name}".lower()
    if raw_id == "small-cap-momentum" or "small-cap" in text or "小市值" in text or "涨停基因" in text:
        return "/api/v1/strategies/small-cap", "small-cap-momentum", SMALL_CAP_STRATEGY_PATH, "small_cap"
    return "/api/v1/strategies/etf", raw_id or "joinquant-wufu-etf-v43", ETF_STRATEGY_PATH, "etf"


STRATEGY_DEFINITIONS = [
    {
        "endpoint": "/api/v1/strategies/etf",
        "path_name": "ETF_STRATEGY_PATH",
        "default_id": "joinquant-wufu-etf-v43",
        "default_name": "ETF 策略",
        "page": "etf.html",
        "signal_key": "recommendations",
        "action_key": "action",
        "label_key": "action_label",
    },
    {
        "endpoint": "/api/v1/strategies/small-cap",
        "path_name": "SMALL_CAP_STRATEGY_PATH",
        "default_id": "small-cap-momentum",
        "default_name": "小市值策略",
        "page": "small-cap.html",
        "signal_key": "signals",
        "action_key": "signal",
        "label_key": "signal_label",
    },
]
SELL_SIGNAL_ACTIONS = {"sell", "stop", "reduce", "trim"}
SELL_LOG_KEYWORDS = ("卖出", "止损", "开板", "放量", "换手", "清仓", "全部清仓", "sell", "stop", "reduce", "trim")
GLOBAL_SELL_KEYWORDS = ("大盘止损", "全部清仓", "清仓")
CN_SYMBOL_PATTERN = re.compile(r"(?<!\d)(?:[013568]\d{5}|[45]\d{5})(?:\.(?:XSHG|XSHE|SH|SZ))?(?!\d)", re.I)


def portfolio_symbol_key(value: Any) -> str:
    symbol, _market = cn_code_parts(value)
    return symbol.strip().upper()


def strategy_path_from_definition(definition: dict[str, Any]) -> Path:
    path_name = str(definition.get("path_name") or "")
    path = globals().get(path_name)
    return path if isinstance(path, Path) else BACKEND_DIR / "strategies" / f"{definition['default_id']}.json"


def load_strategy_payload_for_holdings(definition: dict[str, Any]) -> dict[str, Any] | None:
    path = strategy_path_from_definition(definition)
    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except HTTPException:
        return None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    spec = ENDPOINTS[str(definition["endpoint"])]
    return normalize_payload(payload, spec, str(meta.get("source") or "backend"), path)


def is_real_joinquant_snapshot(payload: dict[str, Any]) -> bool:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    if str(meta.get("source") or "").strip().lower() != "joinquant":
        return False
    run_id = str(meta.get("run_id") or "").strip().lower()
    return not any(marker in run_id for marker in ("test", "smoke", "fixture", "demo", "联调"))


def strategy_context_from_payload(definition: dict[str, Any], payload: dict[str, Any]) -> dict[str, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    strategy = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    strategy_id = str(strategy.get("id") or definition.get("default_id") or "").strip()
    return {
        "strategy_id": strategy_id,
        "strategy_name": str(strategy.get("name") or definition.get("default_name") or strategy_id),
        "strategy_page": str(definition.get("page") or ""),
    }


def strategy_output_row(
    item: dict[str, Any],
    definition: dict[str, Any],
    payload: dict[str, Any],
    context: dict[str, str],
    index: int,
    source: str,
) -> dict[str, Any] | None:
    symbol = portfolio_symbol_key(item.get("symbol") or item.get("code") or item.get("stock") or item.get("etf"))
    if not symbol:
        return None
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    action_key = str(definition.get("action_key") or "action")
    label_key = str(definition.get("label_key") or "action_label")
    raw_action = item.get(action_key) or item.get("action") or item.get("signal") or ("hold" if source == "holding" else "watch")
    action, default_label = normalize_action(raw_action)
    if source == "holding" and action == "watch":
        action, default_label = "hold", "策略持有"
    weight_pct = to_float(item.get("suggested_weight_pct") or item.get("target_weight_pct") or item.get("weight_pct"))
    reason = str(
        item.get("reason")
        or item.get("suggested_range")
        or item.get("invalidation")
        or item.get("theme")
        or item.get("sector")
        or ""
    )
    if source == "holding" and not reason and weight_pct is not None:
        reason = f"策略仓位 {round(weight_pct, 2)}%"
    label = str(item.get(label_key) or item.get("action_label") or item.get("signal_label") or default_label)
    return {
        "strategy_id": context["strategy_id"],
        "strategy_name": context["strategy_name"],
        "strategy_page": context["strategy_page"],
        "source": source,
        "symbol": symbol,
        "name": str(item.get("name") or item.get("etf_name") or symbol),
        "action": action,
        "action_label": label,
        "rank": to_int(item.get("rank"), index + 1),
        "score": to_float(item.get("score")),
        "suggested_weight_pct": weight_pct,
        "last_price": to_float(item.get("last_price") or item.get("price")),
        "reason": reason,
        "updated_at": str(meta.get("as_of") or ""),
        "trade_date": str(meta.get("trade_date") or ""),
        "run_id": str(meta.get("run_id") or ""),
    }


def strategy_portfolio_holding_row(
    item: dict[str, Any],
    payload: dict[str, Any],
    context: dict[str, str],
    index: int,
) -> dict[str, Any]:
    symbol = portfolio_symbol_key(item.get("symbol") or item.get("code") or item.get("stock") or item.get("etf"))
    avg_cost = to_float(item.get("avg_cost") or item.get("cost"))
    last_price = to_float(item.get("last_price") or item.get("price"))
    quantity = to_float(item.get("quantity") or item.get("amount") or item.get("total_amount") or item.get("shares"))
    market_value = to_float(item.get("market_value") or item.get("value"))
    if market_value is None and quantity is not None and last_price is not None:
        market_value = quantity * last_price
    pnl_amount = to_float(item.get("pnl_amount") or item.get("profit_loss"))
    if pnl_amount is None and avg_cost is not None and last_price is not None and quantity is not None:
        pnl_amount = (last_price - avg_cost) * quantity
    pnl_pct = to_float(item.get("pnl_pct"))
    if pnl_pct is None and avg_cost and last_price is not None:
        pnl_pct = (last_price / avg_cost - 1) * 100
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    sector = str(item.get("sector") or item.get("theme") or item.get("industry") or ("ETF" if context["strategy_id"] == "joinquant-wufu-etf-v43" else "--"))
    return {
        "symbol": symbol,
        "raw_symbol": str(item.get("symbol") or item.get("code") or item.get("stock") or item.get("etf") or symbol),
        "name": str(item.get("name") or item.get("etf_name") or symbol or "--"),
        "strategy_id": context["strategy_id"],
        "strategy_name": context["strategy_name"],
        "strategy_page": context["strategy_page"],
        "source": "joinquant",
        "sector": sector,
        "avg_cost": avg_cost,
        "cost": avg_cost,
        "last_price": last_price,
        "quantity": quantity,
        "market_value": market_value,
        "pnl_amount": pnl_amount,
        "pnl_pct": pnl_pct if pnl_pct is not None else 0,
        "weight_pct": to_float(item.get("weight_pct"), 0) or 0,
        "day_change_pct": to_float(item.get("day_change_pct") or item.get("change_pct"), 0),
        "holding_days": to_int(item.get("holding_days"), 0),
        "entry_date": str(item.get("entry_date") or ""),
        "notes": str(item.get("notes") or item.get("reason") or ""),
        "rank": index + 1,
        "strategy_updated_at": str(meta.get("as_of") or ""),
        "trade_date": str(meta.get("trade_date") or ""),
        "run_id": str(meta.get("run_id") or ""),
    }


def strategy_portfolio_summary(rows: list[dict[str, Any]], strategies: list[dict[str, Any]]) -> dict[str, Any]:
    market_values = [value for value in (to_float(row.get("market_value")) for row in rows) if value is not None]
    pnl_amounts = [value for value in (to_float(row.get("pnl_amount")) for row in rows) if value is not None]
    total_market_value = sum(market_values) if market_values else None
    day_changes = [to_float(row.get("day_change_pct"), 0) or 0 for row in rows]
    total_return_pct = None
    if total_market_value:
        total_return_pct = sum((to_float(row.get("pnl_pct"), 0) or 0) * (to_float(row.get("market_value"), 0) or 0) for row in rows) / total_market_value
    elif rows:
        total_return_pct = sum(to_float(row.get("pnl_pct"), 0) or 0 for row in rows) / len(rows)
    weights = [to_float(row.get("weight_pct"), 0) or 0 for row in rows]
    exposure_pct = sum(weights) if len(strategies) <= 1 else None
    return {
        "total_market_value": round(total_market_value, 2) if total_market_value is not None else None,
        "day_pnl_amount": None,
        "day_pnl_pct": round(sum(day_changes) / len(day_changes), 2) if day_changes else None,
        "total_return_pct": round(total_return_pct, 2) if total_return_pct is not None else None,
        "exposure_pct": round(exposure_pct, 2) if exposure_pct is not None else None,
        "position_count": len(rows),
        "sector_diversity": len({str(row.get("sector") or "--") for row in rows}),
        "source": "joinquant",
        "strategy_count": len(strategies),
    }


def strategy_portfolio_allocation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, float]] = {}
    for row in rows:
        sector = str(row.get("sector") or "--")
        bucket = grouped.setdefault(sector, {"market_value": 0, "weight_pct": 0})
        bucket["market_value"] += to_float(row.get("market_value"), 0) or 0
        bucket["weight_pct"] += to_float(row.get("weight_pct"), 0) or 0
    return [
        {
            "sector": sector,
            "weight_pct": round(values["weight_pct"], 2),
            "market_value": round(values["market_value"], 2) if values["market_value"] else None,
        }
        for sector, values in sorted(grouped.items(), key=lambda item: item[1]["market_value"] or item[1]["weight_pct"], reverse=True)
    ]


def pending_small_cap_payload(payload: dict[str, Any]) -> dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    strategy = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    strategy_name = str(strategy.get("name") or "涨停基因小市值轮动")
    return {
        **payload,
        "data": {
            "strategy": {
                **strategy,
                "id": str(strategy.get("id") or "small-cap-momentum"),
                "name": strategy_name,
                "status": "pending",
                "decision_title": "等待聚宽小市值策略上报",
                "decision_detail": "当前文件不是聚宽真实 webhook 快照，已隐藏本地种子信号，避免把样例股票当成实盘输出。",
                "decision_tone": "warning",
            },
            "summary": {
                "signal_count": 0,
                "buy_count": 0,
                "hold_count": 0,
                "exposure_pct": 0,
                "day_pnl_pct": None,
                "floating_pnl_pct": None,
                "turnover_pct": None,
            },
            "signals": [],
            "holdings": [],
            "themes": [],
            "risk": {
                "liquidity_pass_pct": None,
                "concentration_pct": 0,
                "stop_watch_count": 0,
                "volatility_score": None,
            },
            "events": [
                {
                    "time": now_hk().strftime("%H:%M"),
                    "label": "等待上报",
                    "detail": f"已忽略本地种子文件 {meta.get('storage_path') or 'small-cap.json'} 中的样例信号。",
                    "status": "pending",
                }
            ],
            "logs": [],
            "source": "joinquant-pending",
            "ignored_seed_signal_count": len(data.get("signals") if isinstance(data.get("signals"), list) else []),
            "ignored_seed_holding_count": len(data.get("holdings") if isinstance(data.get("holdings"), list) else []),
        },
    }


def text_has_sell_signal(value: Any) -> bool:
    text = str(value or "")
    lowered = text.lower()
    return any(keyword in text or keyword in lowered for keyword in SELL_LOG_KEYWORDS)


def extract_cn_symbols_from_text(value: Any) -> list[str]:
    symbols: list[str] = []
    for match in CN_SYMBOL_PATTERN.findall(str(value or "")):
        symbol = portfolio_symbol_key(match)
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols


def strategy_sell_alert_from_signal(row: dict[str, Any]) -> dict[str, Any] | None:
    if row.get("action") not in SELL_SIGNAL_ACTIONS:
        return None
    return {
        "strategy_id": row.get("strategy_id"),
        "strategy_name": row.get("strategy_name"),
        "strategy_page": row.get("strategy_page"),
        "source": "signal",
        "scope": "symbol",
        "symbol": row.get("symbol"),
        "name": row.get("name"),
        "action": row.get("action"),
        "action_label": row.get("action_label") or "卖出/风控",
        "reason": row.get("reason") or row.get("action_label") or "策略输出卖出信号",
        "time": row.get("updated_at") or row.get("trade_date") or "",
        "trade_date": row.get("trade_date") or "",
        "run_id": row.get("run_id") or "",
        "level": "warning" if row.get("action") in {"reduce", "trim"} else "error",
    }


def strategy_sell_alerts_from_logs(
    payload: dict[str, Any],
    context: dict[str, str],
    signal_names: dict[str, str],
) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    logs = data.get("logs") if isinstance(data.get("logs"), list) else []
    archive_logs = get_recent_strategy_logs(200, strategy_id=context["strategy_id"])
    rows = [row for row in [*logs, *archive_logs] if isinstance(row, dict)]
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        message = str(row.get("message") or row.get("detail") or row.get("label") or "")
        if not text_has_sell_signal(message):
            continue
        symbols = extract_cn_symbols_from_text(message)
        scope = "symbol" if symbols else "strategy"
        if not symbols:
            symbols = [""]
        for symbol in symbols:
            alert_key = f"{context['strategy_id']}|{row.get('time')}|{symbol}|{message}"
            if alert_key in seen:
                continue
            seen.add(alert_key)
            alerts.append(
                {
                    "strategy_id": context["strategy_id"],
                    "strategy_name": context["strategy_name"],
                    "strategy_page": context["strategy_page"],
                    "source": "log",
                    "scope": scope,
                    "symbol": symbol,
                    "name": signal_names.get(symbol, symbol or "策略级风控"),
                    "action": "sell",
                    "action_label": "卖出/风控",
                    "reason": message,
                    "time": str(row.get("time") or row.get("received_at") or meta.get("as_of") or ""),
                    "trade_date": str(row.get("trade_date") or meta.get("trade_date") or ""),
                    "run_id": str(row.get("run_id") or meta.get("run_id") or ""),
                    "level": str(row.get("level") or "warning"),
                }
            )
    return alerts[-40:]


def collect_strategy_outputs_for_holdings() -> dict[str, Any]:
    signal_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    portfolio_rows: list[dict[str, Any]] = []
    sell_alerts: list[dict[str, Any]] = []
    strategies: list[dict[str, Any]] = []
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    alerts_by_symbol: dict[str, list[dict[str, Any]]] = {}
    strategy_level_alerts: list[dict[str, Any]] = []

    for definition in STRATEGY_DEFINITIONS:
        payload = load_strategy_payload_for_holdings(definition)
        if not payload:
            continue
        if not is_real_joinquant_snapshot(payload):
            continue
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        context = strategy_context_from_payload(definition, payload)
        strategies.append(
            {
                **context,
                "updated_at": str(meta.get("as_of") or ""),
                "trade_date": str(meta.get("trade_date") or ""),
                "run_id": str(meta.get("run_id") or ""),
            }
        )

        raw_signals = data.get(str(definition["signal_key"])) if isinstance(data.get(str(definition["signal_key"])), list) else []
        for index, item in enumerate(raw_signals):
            if not isinstance(item, dict):
                continue
            row = strategy_output_row(item, definition, payload, context, index, "signal")
            if row:
                signal_rows.append(row)
                by_symbol.setdefault(str(row["symbol"]), []).append(row)
                alert = strategy_sell_alert_from_signal(row)
                if alert:
                    sell_alerts.append(alert)

        raw_positions = data.get("holdings") if isinstance(data.get("holdings"), list) else []
        for index, item in enumerate(raw_positions):
            if not isinstance(item, dict):
                continue
            row = strategy_output_row(item, definition, payload, context, index, "holding")
            if row:
                position_rows.append(row)
                by_symbol.setdefault(str(row["symbol"]), []).append(row)
                portfolio_rows.append(strategy_portfolio_holding_row(item, payload, context, index))

        signal_names = {str(row["symbol"]): str(row["name"]) for row in [*signal_rows, *position_rows] if row.get("symbol")}
        sell_alerts.extend(strategy_sell_alerts_from_logs(payload, context, signal_names))

    def sort_key(row: dict[str, Any]) -> str:
        return str(row.get("time") or row.get("updated_at") or row.get("trade_date") or "")

    for alert in sell_alerts:
        symbol = str(alert.get("symbol") or "")
        if symbol:
            alerts_by_symbol.setdefault(symbol, []).append(alert)
        elif alert.get("scope") == "strategy":
            strategy_level_alerts.append(alert)

    for rows in by_symbol.values():
        rows.sort(key=lambda row: (row.get("source") != "signal", str(row.get("updated_at") or "")))
    for rows in alerts_by_symbol.values():
        rows.sort(key=sort_key, reverse=True)
    strategy_level_alerts.sort(key=sort_key, reverse=True)

    return {
        "strategies": strategies,
        "signals": sorted(signal_rows, key=lambda row: str(row.get("updated_at") or row.get("trade_date") or ""), reverse=True),
        "positions": position_rows,
        "portfolio_rows": portfolio_rows,
        "sell_alerts": sorted(sell_alerts, key=sort_key, reverse=True)[:40],
        "by_symbol": by_symbol,
        "alerts_by_symbol": alerts_by_symbol,
        "strategy_level_alerts": strategy_level_alerts,
    }


def enrich_portfolio_holdings_with_strategy_outputs(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    outputs = collect_strategy_outputs_for_holdings()
    source_holdings = outputs["portfolio_rows"]
    static_holdings = data.get("holdings") if isinstance(data.get("holdings"), list) else []
    data["source"] = "joinquant" if outputs["strategies"] else "joinquant-pending"
    data["static_holdings_ignored_count"] = len(static_holdings)
    enriched_holdings: list[dict[str, Any]] = []

    for item in source_holdings:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        symbol = portfolio_symbol_key(row.get("symbol"))
        row_strategy_id = str(row.get("strategy_id") or "")
        strategy_signals = list(outputs["by_symbol"].get(symbol, []))
        direct_alerts = list(outputs["alerts_by_symbol"].get(symbol, []))
        strategy_alerts = [
            alert
            for alert in outputs["strategy_level_alerts"]
            if not row_strategy_id or str(alert.get("strategy_id") or "") == row_strategy_id
        ]
        exit_alerts = [*direct_alerts, *strategy_alerts][:4]
        row["strategy_signals"] = strategy_signals[:5]
        row["strategy_signal"] = " / ".join(
            f"{signal.get('strategy_name')}:{signal.get('action_label')}"
            for signal in strategy_signals[:3]
        )
        row["strategy_updated_at"] = next((signal.get("updated_at") for signal in strategy_signals if signal.get("updated_at")), "")
        row["exit_alerts"] = exit_alerts
        row["exit_signal"] = " / ".join(
            f"{alert.get('strategy_name')}:{alert.get('action_label')}"
            for alert in exit_alerts[:2]
        )
        enriched_holdings.append(row)

    data["holdings"] = enriched_holdings
    data["summary"] = strategy_portfolio_summary(enriched_holdings, outputs["strategies"])
    data["allocation"] = strategy_portfolio_allocation(enriched_holdings)
    data["strategy_outputs"] = {
        "updated_at": now_hk().isoformat(),
        "strategies": outputs["strategies"],
        "signals": outputs["signals"][:30],
        "positions": outputs["positions"][:30],
        "sell_alerts": outputs["sell_alerts"][:30],
        "holdings_source": data["source"],
    }
    return payload


def infer_market_region(symbol: str) -> str:
    return "cn" if symbol.isdigit() else "us"


def infer_cn_market(symbol: str) -> str:
    return "SH" if symbol.startswith(("5", "6", "9")) else "SZ"


def normalize_watchlist_item(item: dict[str, Any]) -> dict[str, Any]:
    raw_symbol = str(item.get("symbol") or "").strip().upper().replace(" ", "")
    if not raw_symbol:
        raise HTTPException(status_code=422, detail="缺少股票代码")

    market_hint = str(item.get("exchange") or item.get("market") or "").strip().upper()
    if raw_symbol.startswith(("SH", "SZ")) and raw_symbol[2:].isdigit():
        market_hint = raw_symbol[:2]
        raw_symbol = raw_symbol[2:]
    elif "." in raw_symbol:
        base, suffix = raw_symbol.split(".", 1)
        if base.isdigit() and suffix in {"SS", "SH"}:
            market_hint = "SH"
            raw_symbol = base
        elif base.isdigit() and suffix == "SZ":
            market_hint = "SZ"
            raw_symbol = base

    market_region = str(item.get("market_region") or item.get("region") or "").strip().lower()
    if market_region not in {"cn", "us"}:
        market_region = infer_market_region(raw_symbol)

    if market_region == "cn" and not raw_symbol.isdigit():
        raise HTTPException(status_code=422, detail="A股自选只支持纯数字代码，例如 600519 或 300308")

    if market_region == "us" and not re.fullmatch(r"[A-Z0-9.-]{1,18}", raw_symbol):
        raise HTTPException(status_code=422, detail="美股 ticker 格式不合法")

    name = str(item.get("name") or raw_symbol).strip()
    sector = str(item.get("sector") or ("美股自选" if market_region == "us" else "A股自选")).strip()
    normalized: dict[str, Any] = {
        "symbol": raw_symbol,
        "name": name,
        "logo": str(item.get("logo") or name[:1] or raw_symbol[:1]).strip(),
        "sector": sector,
        "provider": "yahoo" if market_region == "us" else "eastmoney",
        "market_region": market_region,
    }
    if market_region == "us":
        normalized["provider_symbol"] = str(item.get("provider_symbol") or raw_symbol).strip().upper()
    else:
        normalized["market"] = market_hint if market_hint in {"SH", "SZ"} else infer_cn_market(raw_symbol)
    return normalized


def load_watchlist_config() -> dict[str, Any]:
    if not WATCHLIST_CONFIG_PATH.exists():
        return {"items": []}
    payload = load_json(WATCHLIST_CONFIG_PATH)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    normalized_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            normalized_items.append(normalize_watchlist_item(item))
        except HTTPException:
            continue
    return {"items": normalized_items}


def save_watchlist_items(items: list[dict[str, Any]]) -> None:
    write_json_atomic(WATCHLIST_CONFIG_PATH, {"items": items})


def invalidate_watchlist_live_data() -> None:
    for path in (LIVE_DIR / "watchlist.json", LIVE_DIR / "overview.json"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def build_watchlist_config_payload(
    items: list[dict[str, Any]],
    *,
    config_status: str,
    refresh_status: str,
    refresh_error: str | None = None,
) -> dict[str, Any]:
    groups_by_name: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        groups_by_name.setdefault(str(item.get("sector") or "自选股"), []).append(item)

    meta: dict[str, Any] = {
        "version": "1.0",
        "source": "config",
        "as_of": now_hk().isoformat(),
        "trade_date": now_hk().strftime("%Y-%m-%d"),
        "timezone": "Asia/Hong_Kong",
        "market_session": market_session(),
        "run_id": f"watchlist-config-{now_hk().strftime('%Y%m%d-%H%M%S')}",
        "refresh_policy": "realtime",
        "refresh_seconds": ENDPOINTS["/api/v1/watchlist"].refresh_seconds,
        "config_status": config_status,
        "refresh_status": refresh_status,
    }
    data: dict[str, Any] = {
        "items": items,
        "groups": [{"name": name, "items": group_items} for name, group_items in groups_by_name.items()],
    }
    if refresh_error:
        warning = f"配置写入成功，行情暂未更新: {refresh_error}"
        meta["warning"] = warning
        data["refresh_error"] = warning
    return {"meta": meta, "data": data}


def watchlist_mutation_payload(
    items: list[dict[str, Any]],
    *,
    config_status: str,
    response: Response,
) -> dict[str, Any]:
    invalidate_watchlist_live_data()
    refreshed, detail = run_live_data_refresh()
    if not refreshed:
        response.status_code = 202
        return build_watchlist_config_payload(
            items,
            config_status=config_status,
            refresh_status="failed",
            refresh_error=detail or "行情刷新失败",
        )

    try:
        payload = get_payload("/api/v1/watchlist")
    except HTTPException as exc:
        response.status_code = 202
        return build_watchlist_config_payload(
            items,
            config_status=config_status,
            refresh_status="failed",
            refresh_error=str(exc.detail or "行情刷新后仍不可用"),
        )
    payload["meta"]["config_status"] = config_status
    payload["meta"]["refresh_status"] = "refreshed"
    payload.setdefault("data", {})["refresh_error"] = None
    return payload


def run_live_data_refresh(timeout: int = 45) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "update_live_data.py"), "--root", str(ROOT)],
            cwd=ROOT,
            check=True,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        return False, "行情刷新超时"
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc)).strip()
        return False, detail[-500:]
    except Exception as exc:
        return False, str(exc)
    return True, result.stdout.strip()


def unavailable_detail(message: str, path: Path) -> dict[str, Any]:
    return {"message": message, "storage_path": str(path.relative_to(ROOT)), "missing_fields": []}


def available_path(spec: EndpointSpec) -> tuple[Path, str]:
    if spec.live_path and spec.live_path.exists():
        return spec.live_path, "live"
    if spec.live_key and spec.live_path:
        raise HTTPException(status_code=503, detail=unavailable_detail(f"{spec.path} 实时数据暂不可用", spec.live_path))
    if spec.backend_path.exists():
        return spec.backend_path, "backend"
    raise HTTPException(status_code=503, detail=unavailable_detail(f"{spec.path} 暂无可用数据", spec.backend_path))


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def live_data_is_stale(path: Path, max_age_seconds: int) -> bool:
    if not path.exists():
        return True
    try:
        payload = load_json(path)
    except HTTPException:
        return True
    as_of = parse_iso_datetime((payload.get("meta") or {}).get("as_of"))
    if as_of is None:
        return True
    age = (now_hk() - as_of.astimezone(HK_TZ)).total_seconds()
    return age > max_age_seconds


def ensure_fresh_live_data(spec: EndpointSpec) -> None:
    if spec.refresh_policy != "realtime" or not spec.live_path:
        return
    max_age = max(spec.refresh_seconds * 2, 60)
    if not live_data_is_stale(spec.live_path, max_age):
        return
    refreshed, detail = run_live_data_refresh()
    if not refreshed:
        raise HTTPException(status_code=503, detail=f"{spec.path} 实时数据刷新失败: {detail}")
    if live_data_is_stale(spec.live_path, max_age):
        raise HTTPException(status_code=503, detail=f"{spec.path} 实时数据刷新后仍不可用")


def normalize_payload(payload: dict[str, Any], spec: EndpointSpec, source: str, path: Path) -> dict[str, Any]:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    as_of = meta.get("as_of") or now_hk().isoformat()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    algorithm = data.get("source_algorithm") if isinstance(data.get("source_algorithm"), dict) else {}
    normalized_meta = {
        **meta,
        "version": meta.get("version") or "1.0",
        "source": source,
        "as_of": as_of,
        "trade_date": meta.get("trade_date") or now_hk().strftime("%Y-%m-%d"),
        "timezone": meta.get("timezone") or "Asia/Hong_Kong",
        "market_session": meta.get("market_session") or market_session(),
        "run_id": meta.get("run_id") or f"{spec.refresh_policy}-{now_hk().strftime('%Y%m%d-%H%M%S')}",
        "refresh_policy": spec.refresh_policy,
        "refresh_seconds": spec.refresh_seconds,
        "storage_path": str(path.relative_to(ROOT)),
        "source_quality": meta.get("source_quality") or algorithm.get("source_quality") or "real",
    }
    return {"meta": normalized_meta, "data": data}


def schema_error_detail(exc: SchemaValidationError) -> dict[str, Any]:
    return {
        "message": "数据结构校验失败",
        "storage_path": exc.storage_path,
        "missing_fields": exc.missing_fields,
        "errors": exc.errors,
    }


def validate_response_payload(path: str, payload: dict[str, Any], storage_path: str) -> dict[str, Any]:
    model = PAYLOAD_SCHEMAS.get(path)
    if not model:
        return payload
    try:
        validate_payload(model, payload, storage_path)
    except SchemaValidationError as exc:
        raise HTTPException(status_code=500, detail=schema_error_detail(exc)) from exc
    return payload


def get_payload(path: str) -> dict[str, Any]:
    spec = ENDPOINTS[path]
    data_path, source = available_path(spec)
    payload = load_json(data_path)
    normalized = normalize_payload(payload, spec, source, data_path)
    return validate_response_payload(path, normalized, str(data_path.relative_to(ROOT)))


def verify_action_permission(request: Request) -> None:
    expected = os.getenv("QUANT_ACTION_TOKEN", "").strip()
    if not expected and env_flag("QUANT_REQUIRE_ACTION_TOKEN"):
        raise HTTPException(status_code=403, detail="权限不足：服务端未配置操作令牌")
    if not expected:
        return
    provided = (request.headers.get("x-action-token") or request.headers.get("authorization") or "").strip()
    if provided.lower().startswith("bearer "):
        provided = provided[7:].strip()
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="权限不足：缺少有效操作令牌")


def action_response(action_type: str, detail: dict[str, Any]) -> dict[str, Any]:
    now = now_hk()
    action_stamp = datetime.now(HK_TZ).strftime("%Y%m%d-%H%M%S-%f")
    record = {
        "action_id": f"{action_type}-{action_stamp}",
        "action_type": action_type,
        "created_at": now.isoformat(),
        "trade_date": now.strftime("%Y-%m-%d"),
        "status": "success",
        **detail,
    }
    append_jsonl(ACTION_LOG_PATH, record)
    return {
        "meta": {
            "version": "1.0",
            "source": "action",
            "as_of": now.isoformat(),
            "trade_date": now.strftime("%Y-%m-%d"),
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(now),
            "run_id": record["action_id"],
            "storage_path": str(ACTION_LOG_PATH.relative_to(ROOT)),
        },
        "data": record,
    }


def normalize_filter_value(value: Any) -> str:
    return re.sub(r"[\s_-]+", "", str(value or "").strip().lower())


def normalize_trade_date(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(HK_TZ).strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        return datetime.strptime(raw[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="date 必须使用 YYYY-MM-DD 格式") from exc


def strategy_aliases(data: dict[str, Any]) -> set[str]:
    aliases = {
        normalize_filter_value(data.get("strategy")),
        normalize_filter_value(data.get("strategy_id")),
        normalize_filter_value(data.get("strategy_label")),
    }
    return {item for item in aliases if item}


def strategy_matches_data(data: dict[str, Any], strategy: str | None) -> bool:
    target = normalize_filter_value(strategy)
    if not target:
        return True
    return target in strategy_aliases(data)


def pick_matches_strategy(item: dict[str, Any], strategy: str | None, fallback_data: dict[str, Any]) -> bool:
    target = normalize_filter_value(strategy)
    if not target:
        return True
    item_values = [
        item.get("strategy"),
        item.get("strategy_id"),
        item.get("strategy_label"),
        item.get("strategy_name"),
    ]
    explicit = [normalize_filter_value(value) for value in item_values if value not in {None, ""}]
    if explicit:
        return target in explicit
    return strategy_matches_data(fallback_data, strategy)


def pick_trade_date(item: dict[str, Any], fallback_date: str) -> str:
    raw = item.get("trade_date") or item.get("date") or fallback_date
    try:
        return normalize_trade_date(str(raw)) or fallback_date
    except HTTPException:
        return str(raw or fallback_date)


def pick_partition_candidates(strategy: str | None, trade_date: str | None) -> list[Path]:
    if not trade_date and not strategy:
        return []
    candidates: list[Path] = []
    strategy_key = normalize_filter_value(strategy)
    safe_strategy = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(strategy or "").strip())
    if trade_date and strategy_key:
        candidates.extend(
            [
                STRATEGY_PICKS_PARTITION_DIR / trade_date / f"{safe_strategy}.json",
                STRATEGY_PICKS_PARTITION_DIR / strategy_key / f"{trade_date}.json",
                STRATEGY_PICKS_PARTITION_DIR / f"{trade_date}_{safe_strategy}.json",
            ]
        )
    if trade_date:
        candidates.extend(
            [
                STRATEGY_PICKS_PARTITION_DIR / trade_date / "picks.json",
                STRATEGY_PICKS_PARTITION_DIR / f"{trade_date}.json",
            ]
        )
    if strategy_key:
        candidates.append(STRATEGY_PICKS_PARTITION_DIR / strategy_key / "latest.json")
    return candidates


def load_strategy_picks_base(strategy: str | None, trade_date: str | None) -> dict[str, Any]:
    spec = ENDPOINTS["/api/v1/strategies/picks"]
    for path in pick_partition_candidates(strategy, trade_date):
        if path.exists() and path.is_file():
            normalized = normalize_payload(load_json(path), spec, "backend", path)
            return validate_response_payload(
                "/api/v1/strategies/picks",
                normalized,
                str(path.relative_to(ROOT)),
            )
    return get_payload("/api/v1/strategies/picks")


def empty_picks_payload(payload: dict[str, Any], reason: str, message: str, strategy: str | None, trade_date: str | None) -> dict[str, Any]:
    data = payload.setdefault("data", {})
    data["items"] = []
    data["count"] = 0
    data["empty_reason"] = reason
    data["empty_message"] = message
    if strategy:
        data["strategy"] = strategy
        data.setdefault("strategy_label", strategy)
    if trade_date:
        data["trade_date"] = trade_date
        payload.setdefault("meta", {})["trade_date"] = trade_date
    return payload


def filtered_strategy_picks(strategy: str | None = None, date: str | None = None) -> dict[str, Any]:
    trade_date = normalize_trade_date(date)
    payload = load_strategy_picks_base(strategy, trade_date)
    data = payload.setdefault("data", {})
    items = data.get("items")
    query = {"strategy": strategy, "date": trade_date}
    payload.setdefault("meta", {})["query"] = query

    if not isinstance(items, list):
        return empty_picks_payload(payload, "api_no_data", "接口返回结构中没有可用的选股列表。", strategy, trade_date)
    if not items:
        return empty_picks_payload(payload, "api_no_data", "接口暂无选股数据。", strategy, trade_date)

    default_date = str(data.get("trade_date") or payload.get("meta", {}).get("trade_date") or "")
    date_filtered = [
        item for item in items
        if isinstance(item, dict) and (not trade_date or pick_trade_date(item, default_date) == trade_date)
    ]
    if trade_date and not date_filtered:
        return empty_picks_payload(payload, "date_no_picks", f"{trade_date} 暂无选股结果。", strategy, trade_date)

    strategy_filtered = [
        item for item in date_filtered
        if isinstance(item, dict) and pick_matches_strategy(item, strategy, data)
    ]
    if strategy and not strategy_filtered:
        return empty_picks_payload(payload, "filter_no_match", "当前策略筛选条件没有匹配的选股结果。", strategy, trade_date)

    data["items"] = strategy_filtered
    data["count"] = len(strategy_filtered)
    if strategy and strategy_matches_data(data, strategy):
        data["strategy"] = data.get("strategy") or strategy
    elif strategy:
        data["strategy"] = strategy
        data.setdefault("strategy_label", strategy)
    if trade_date:
        data["trade_date"] = trade_date
        payload["meta"]["trade_date"] = trade_date
    data.pop("empty_reason", None)
    data.pop("empty_message", None)
    return payload


def strategy_picks_csv(payload: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["trade_date", "strategy", "symbol", "name", "score", "confidence", "entry_price", "stop_loss", "take_profit", "tags", "explanation", "invalidation"])
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for item in data.get("items") or []:
        if not isinstance(item, dict):
            continue
        writer.writerow([
            data.get("trade_date") or payload.get("meta", {}).get("trade_date") or "",
            item.get("strategy") or item.get("strategy_label") or data.get("strategy") or data.get("strategy_label") or "",
            item.get("symbol") or "",
            item.get("name") or "",
            item.get("score") or "",
            item.get("confidence") or "",
            item.get("entry_price") or item.get("entry") or "",
            item.get("stop_loss") or item.get("stop") or "",
            item.get("take_profit") or item.get("target") or "",
            ";".join(str(tag) for tag in item.get("tags") or []),
            item.get("explanation") or "",
            item.get("invalidation") or "",
        ])
    return buffer.getvalue()


@app.get("/api/v1/actions")
def action_log(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
    rows = read_jsonl_tail(ACTION_LOG_PATH, limit)
    return {
        "meta": {
            "version": "1.0",
            "source": "action",
            "as_of": now_hk().isoformat(),
            "trade_date": now_hk().strftime("%Y-%m-%d"),
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(),
            "run_id": f"actions-{now_hk().strftime('%Y%m%d-%H%M%S')}",
            "storage_path": str(ACTION_LOG_PATH.relative_to(ROOT)),
        },
        "data": {"count": len(rows), "items": rows},
    }


@app.post("/api/v1/portfolio/holdings/{symbol}/mark")
def mark_holding(symbol: str, request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    verify_action_permission(request)
    payload = payload or {}
    mark = str(payload.get("mark") or "reviewed").strip()
    note = str(payload.get("note") or "").strip()
    return action_response("holding_mark", {"symbol": symbol.upper(), "mark": mark, "note": note, "message": f"持仓 {symbol.upper()} 已标记为 {mark}"})


@app.post("/api/v1/strategies/{strategy_id}/signals/{symbol}/confirm")
def confirm_strategy_signal(strategy_id: str, symbol: str, request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    verify_action_permission(request)
    payload = payload or {}
    action = str(payload.get("action") or "confirm").strip()
    note = str(payload.get("note") or "").strip()
    return action_response("signal_confirm", {"strategy_id": strategy_id, "symbol": symbol.upper(), "action": action, "note": note, "message": f"{strategy_id} 信号 {symbol.upper()} 已确认"})


@app.post("/api/v1/strategies/picks/export")
def export_strategy_picks_action(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    verify_action_permission(request)
    payload = payload or {}
    strategy = str(payload.get("strategy") or "").strip() or None
    trade_date = str(payload.get("date") or payload.get("trade_date") or "").strip() or None
    picks_payload = filtered_strategy_picks(strategy=strategy, date=trade_date)
    data = picks_payload.get("data", {})
    items = data.get("items") if isinstance(data.get("items"), list) else []
    csv_text = strategy_picks_csv(picks_payload)
    now = now_hk()
    filename = f"picks-{now.strftime('%Y%m%d-%H%M%S')}.csv"
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    export_path = EXPORT_DIR / filename
    export_path.write_text(csv_text, encoding="utf-8")
    return action_response("picks_export", {"filename": filename, "rows": len(items), "csv": csv_text, "message": f"已导出 {len(items)} 条选股记录"})


@app.post("/api/v1/portfolio/rebalance-records")
def create_rebalance_record(request: Request, payload: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
    verify_action_permission(request)
    payload = payload or {}
    symbol = str(payload.get("symbol") or "").strip().upper()
    action = str(payload.get("action") or "rebalance").strip()
    weight_pct = payload.get("weight_pct")
    note = str(payload.get("note") or "").strip()
    return action_response("rebalance_record", {"symbol": symbol, "action": action, "weight_pct": weight_pct, "note": note, "message": f"调仓记录已保存{f'：{symbol}' if symbol else ''}"})


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    specs = []
    for spec in ENDPOINTS.values():
        if spec.path == "/api/v1/overview":
            continue
        try:
            data_path, source = available_path(spec)
            status = "ready"
            storage_path = str(data_path.relative_to(ROOT))
        except HTTPException:
            source = None
            status = "missing"
            storage_path = None
        specs.append(
            {
                "path": spec.path,
                "status": status,
                "source": source,
                "refresh_policy": spec.refresh_policy,
                "refresh_seconds": spec.refresh_seconds,
                "description": spec.description,
                "storage_path": storage_path,
            }
        )
    return {
        "meta": {
            "version": "1.0",
            "source": "live",
            "as_of": now_hk().isoformat(),
            "trade_date": now_hk().strftime("%Y-%m-%d"),
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(),
            "run_id": f"health-{now_hk().strftime('%Y%m%d-%H%M%S')}",
        },
        "data": {"endpoints": specs},
    }


@app.get("/api/v1/dashboard/overview")
def dashboard_overview() -> dict[str, Any]:
    return get_payload("/api/v1/dashboard/overview")


@app.get("/api/v1/overview")
def legacy_overview() -> dict[str, Any]:
    return get_payload("/api/v1/overview")


@app.get("/api/v1/watchlist")
def watchlist() -> dict[str, Any]:
    return get_payload("/api/v1/watchlist")


@app.get("/api/v1/watchlist/config")
def watchlist_config() -> dict[str, Any]:
    return {
        "meta": {
            "version": "1.0",
            "source": "config",
            "as_of": now_hk().isoformat(),
            "trade_date": now_hk().strftime("%Y-%m-%d"),
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(),
            "run_id": f"watchlist-config-{now_hk().strftime('%Y%m%d-%H%M%S')}",
        },
        "data": load_watchlist_config(),
    }


@app.post("/api/v1/watchlist")
def add_watchlist_item(request: Request, response: Response, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    verify_action_permission(request)
    item = normalize_watchlist_item(payload)
    config = load_watchlist_config()
    items = config["items"]
    item_key = (item["market_region"], item["symbol"])
    merged = [row for row in items if (row.get("market_region"), row.get("symbol")) != item_key]
    merged.append(item)
    save_watchlist_items(merged)
    return watchlist_mutation_payload(merged, config_status="saved", response=response)


@app.delete("/api/v1/watchlist/{symbol}")
def delete_watchlist_item(
    symbol: str,
    request: Request,
    response: Response,
    market_region: str | None = Query(default=None, alias="market"),
) -> dict[str, Any]:
    verify_action_permission(request)
    probe = normalize_watchlist_item({"symbol": symbol, "market_region": market_region} if market_region else {"symbol": symbol})
    raw_symbol = probe["symbol"]
    region = probe["market_region"]
    config = load_watchlist_config()
    items = config["items"]
    kept = [
        item
        for item in items
        if not (
            item.get("symbol") == raw_symbol
            and item.get("market_region") == region
        )
    ]
    if len(kept) == len(items):
        raise HTTPException(status_code=404, detail=f"自选股不存在: {raw_symbol}")
    save_watchlist_items(kept)
    return watchlist_mutation_payload(kept, config_status="deleted", response=response)


@app.get("/api/v1/strategies/picks")
def strategy_picks(
    strategy: str | None = Query(default=None),
    date: str | None = Query(default=None),
) -> dict[str, Any]:
    payload = filtered_strategy_picks(strategy=strategy, date=date)
    return validate_response_payload(
        "/api/v1/strategies/picks",
        payload,
        payload.get("meta", {}).get("storage_path") or "data/backend/strategies/picks.json",
    )


@app.get("/api/v1/strategies/picks/export")
def export_strategy_picks(
    strategy: str | None = Query(default=None),
    date: str | None = Query(default=None),
) -> StreamingResponse:
    payload = filtered_strategy_picks(strategy=strategy, date=date)
    csv_text = strategy_picks_csv(payload)
    trade_date = payload.get("data", {}).get("trade_date") or payload.get("meta", {}).get("trade_date") or now_hk().strftime("%Y-%m-%d")
    raw_strategy = normalize_filter_value(strategy or payload.get("data", {}).get("strategy") or "all") or "all"
    strategy_key = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_strategy).strip("-") or "all"
    filename = f"strategy-picks-{trade_date}-{strategy_key}.csv"
    return StreamingResponse(
        iter([csv_text]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/v1/portfolio/holdings")
def portfolio_holdings() -> dict[str, Any]:
    payload = get_payload("/api/v1/portfolio/holdings")
    return enrich_portfolio_holdings_with_strategy_outputs(payload)


def parse_query_date(value: str | None, field_name: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_name} 必须是 YYYY-MM-DD 格式") from exc


def parse_row_date(row: dict[str, Any]) -> date | None:
    raw = row.get("date") or row.get("trade_date") or row.get("day")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def numeric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def nav_value(row: dict[str, Any]) -> float | None:
    for key in ("nav", "net_value", "value", "equity", "portfolio_value"):
        value = numeric(row.get(key))
        if value is not None:
            return value
    return None


def normalize_nav_curve(rows: list[Any], start_date: date | None, end_date: date) -> list[dict[str, Any]]:
    dated_rows: list[tuple[date, float]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_date = parse_row_date(row)
        value = nav_value(row)
        if row_date is None or value is None:
            continue
        if row_date > end_date:
            continue
        if start_date and row_date < start_date:
            continue
        dated_rows.append((row_date, value))
    dated_rows.sort(key=lambda item: item[0])
    if not dated_rows:
        return []
    base = dated_rows[0][1] or 1
    return [
        {
            "date": row_date.isoformat(),
            "value": round(value, 4),
            "return_pct": round((value / base - 1) * 100, 4),
        }
        for row_date, value in dated_rows
    ]


def month_key(row: dict[str, Any]) -> date | None:
    if row.get("year") is not None and row.get("month") is not None:
        try:
            return date(int(row["year"]), int(row["month"]), 1)
        except (TypeError, ValueError):
            return None
    row_date = parse_row_date(row)
    if row_date:
        return row_date.replace(day=1)
    return None


def monthly_returns_from_curve(curve: list[dict[str, Any]], start_date: date | None, end_date: date) -> list[dict[str, Any]]:
    values_by_month: dict[tuple[int, int], tuple[float, float]] = {}
    for row in curve:
        row_date = parse_row_date(row)
        value = nav_value(row)
        if row_date is None or value is None:
            continue
        key = (row_date.year, row_date.month)
        first, _last = values_by_month.get(key, (value, value))
        values_by_month[key] = (first, value)
    result: list[dict[str, Any]] = []
    for (year, month), (first, last) in sorted(values_by_month.items()):
        current_month = date(year, month, 1)
        if start_date and current_month < date(start_date.year, start_date.month, 1):
            continue
        if current_month > date(end_date.year, end_date.month, 1):
            continue
        result.append({"year": year, "month": month, "return_pct": round((last / (first or 1) - 1) * 100, 4)})
    return result


def crop_monthly_returns(rows: list[Any], start_date: date | None, end_date: date) -> list[dict[str, Any]]:
    cropped = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        current_month = month_key(row)
        if current_month is None:
            continue
        if start_date and current_month < date(start_date.year, start_date.month, 1):
            continue
        if current_month > date(end_date.year, end_date.month, 1):
            continue
        cropped.append(row)
    return cropped


def period_returns(curve: list[dict[str, Any]]) -> list[float]:
    values = [nav_value(row) for row in curve]
    clean = [value for value in values if value is not None]
    return [(clean[index] / clean[index - 1] - 1) for index in range(1, len(clean)) if clean[index - 1]]


def build_drawdowns(curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    peak_value: float | None = None
    peak_date = ""
    active_start = ""
    worst_drawdown = 0.0
    worst_date = ""
    drawdowns: list[dict[str, Any]] = []
    for row in curve:
        value = nav_value(row)
        row_date = str(row.get("date") or "")
        if value is None:
            continue
        if peak_value is None or value >= peak_value:
            if active_start and worst_drawdown < 0:
                drawdowns.append({"start": active_start, "end": worst_date or row_date, "max_drawdown_pct": round(worst_drawdown * 100, 4)})
            peak_value = value
            peak_date = row_date
            active_start = ""
            worst_drawdown = 0.0
            worst_date = ""
            continue
        drawdown = value / peak_value - 1
        if not active_start:
            active_start = peak_date
        if drawdown < worst_drawdown:
            worst_drawdown = drawdown
            worst_date = row_date
    if active_start and worst_drawdown < 0:
        drawdowns.append({"start": active_start, "end": worst_date, "max_drawdown_pct": round(worst_drawdown * 100, 4)})
    return drawdowns[-5:]


def calculate_metrics(curve: list[dict[str, Any]], benchmark_curve: list[dict[str, Any]]) -> dict[str, Any]:
    values = [nav_value(row) for row in curve]
    clean_values = [value for value in values if value is not None]
    returns = period_returns(curve)
    benchmark_returns = period_returns(benchmark_curve)
    if len(clean_values) < 2:
        return {}
    first_date = parse_row_date(curve[0])
    last_date = parse_row_date(curve[-1])
    days = max(1, (last_date - first_date).days) if first_date and last_date else max(1, len(clean_values) - 1)
    total_return = clean_values[-1] / clean_values[0] - 1 if clean_values[0] else 0
    annual_return = (1 + total_return) ** (365 / days) - 1 if total_return > -1 else -1
    avg_return = sum(returns) / len(returns) if returns else 0
    variance = sum((item - avg_return) ** 2 for item in returns) / max(1, len(returns) - 1) if len(returns) > 1 else 0
    sharpe = (avg_return / math.sqrt(variance) * math.sqrt(252)) if variance > 0 else None
    max_drawdown = min((row["max_drawdown_pct"] for row in build_drawdowns(curve)), default=0)
    wins = [item for item in returns if item > 0]
    losses = [item for item in returns if item < 0]
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0
    beta = None
    alpha = None
    if returns and benchmark_returns:
        paired = list(zip(returns[-len(benchmark_returns):], benchmark_returns[-len(returns):]))
        if len(paired) > 1:
            strategy_part = [item[0] for item in paired]
            benchmark_part = [item[1] for item in paired]
            bm_avg = sum(benchmark_part) / len(benchmark_part)
            st_avg = sum(strategy_part) / len(strategy_part)
            bm_var = sum((item - bm_avg) ** 2 for item in benchmark_part)
            cov = sum((strategy_part[index] - st_avg) * (benchmark_part[index] - bm_avg) for index in range(len(paired)))
            if bm_var:
                beta = cov / bm_var
                benchmark_total = (benchmark_curve[-1]["value"] / benchmark_curve[0]["value"] - 1) if benchmark_curve and benchmark_curve[0].get("value") else 0
                alpha = total_return - beta * benchmark_total
    return {
        "annual_return_pct": round(annual_return * 100, 4),
        "max_drawdown_pct": round(max_drawdown, 4),
        "sharpe": None if sharpe is None else round(sharpe, 4),
        "calmar": round((annual_return * 100) / abs(max_drawdown), 4) if max_drawdown else None,
        "win_rate_pct": round(len(wins) / len(returns) * 100, 4) if returns else None,
        "profit_loss_ratio": round(avg_win / avg_loss, 4) if avg_loss else None,
        "beta": None if beta is None else round(beta, 4),
        "alpha_pct": None if alpha is None else round(alpha * 100, 4),
    }


def strategy_label_from_payload(strategy_id: str, payload: dict[str, Any] | None = None) -> str:
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    strategy = data.get("strategy") if isinstance(data.get("strategy"), dict) else {}
    label = str(strategy.get("name") or data.get("strategy_name") or "").strip()
    if label:
        return label
    known = {
        "joinquant-wufu-etf-v43": "五福 ETF 轮动",
        "small-cap-momentum": "涨停基因小市值",
    }
    return known.get(strategy_id, strategy_id)


def extract_raw_data(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def payload_positions(data: dict[str, Any], normalized_payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    raw = data.get("holdings") or data.get("positions") or []
    if not isinstance(raw, list) and normalized_payload:
        normalized_data = normalized_payload.get("data") if isinstance(normalized_payload.get("data"), dict) else {}
        raw = normalized_data.get("holdings") or normalized_data.get("positions") or normalized_data.get("recommendations") or []
    return [row for row in raw if isinstance(row, dict)] if isinstance(raw, list) else []


def position_market_value(row: dict[str, Any]) -> float | None:
    value = to_float(row.get("market_value") or row.get("value"))
    if value is not None:
        return value
    price = to_float(row.get("last_price") or row.get("price"))
    quantity = to_float(row.get("quantity") or row.get("amount") or row.get("total_amount") or row.get("shares"))
    if price is None or quantity is None:
        return None
    return price * quantity


def normalize_joinquant_trade(item: dict[str, Any]) -> dict[str, Any]:
    security = item.get("symbol") or item.get("security") or item.get("code") or item.get("stock")
    symbol, market = cn_code_parts(security)
    action, action_label = normalize_action(item.get("action") or item.get("side") or item.get("type"))
    return {
        "trade_id": str(item.get("trade_id") or item.get("id") or item.get("order_id") or ""),
        "time": str(item.get("time") or item.get("timestamp") or item.get("datetime") or ""),
        "symbol": symbol,
        "raw_symbol": str(security or ""),
        "market": market,
        "name": str(item.get("name") or symbol or ""),
        "action": action,
        "action_label": action_label,
        "price": to_float(item.get("price") or item.get("filled_price")),
        "quantity": to_float(item.get("quantity") or item.get("amount") or item.get("filled") or item.get("shares")),
        "value": to_float(item.get("value") or item.get("filled_value") or item.get("turnover")),
    }


def normalize_joinquant_account_snapshot(
    payload: dict[str, Any],
    normalized_payload: dict[str, Any],
    strategy_id: str,
    endpoint: str,
    storage_path: Path,
    received_at: str,
) -> dict[str, Any] | None:
    data = extract_raw_data(payload)
    portfolio = data.get("portfolio") if isinstance(data.get("portfolio"), dict) else {}
    normalized_meta = normalized_payload.get("meta") if isinstance(normalized_payload.get("meta"), dict) else {}
    total_value = to_float(
        portfolio.get("total_value")
        or portfolio.get("portfolio_value")
        or data.get("total_value")
        or data.get("portfolio_value")
        or data.get("account_value")
    )
    if total_value is None:
        return None
    cash = to_float(
        portfolio.get("cash")
        or portfolio.get("available_cash")
        or portfolio.get("available")
        or data.get("cash")
        or data.get("available_cash"),
        0,
    )
    positions = payload_positions(data, normalized_payload)
    positions_market_value = sum(value for value in (position_market_value(row) for row in positions) if value is not None)
    trade_rows = data.get("trades") or data.get("orders") or data.get("transactions") or []
    trades = [normalize_joinquant_trade(row) for row in trade_rows if isinstance(row, dict)] if isinstance(trade_rows, list) else []
    as_of = iso_hk(data.get("as_of") or normalized_meta.get("as_of") or received_at)
    run_id = str(data.get("run_id") or normalized_meta.get("run_id") or f"joinquant-{parse_hk_datetime(as_of).strftime('%Y%m%d-%H%M%S')}")
    trade_date = str(data.get("trade_date") or normalized_meta.get("trade_date") or as_of[:10])
    snapshot_id = f"{strategy_id}|{run_id}|{as_of}"
    snapshot_hash = stable_json_hash(redact_secret_fields(payload))
    return {
        "snapshot_id": snapshot_id,
        "snapshot_hash": snapshot_hash,
        "received_at": received_at,
        "strategy_id": strategy_id,
        "strategy_label": strategy_label_from_payload(strategy_id, normalized_payload),
        "endpoint": endpoint,
        "storage_path": str(storage_path.relative_to(ROOT)),
        "run_id": run_id,
        "as_of": as_of,
        "trade_date": trade_date,
        "total_value": round(total_value, 4),
        "cash": round(cash or 0, 4),
        "positions_market_value": round(positions_market_value, 4),
        "position_count": len(positions),
        "trade_count": len(trades),
        "trades": trades,
        "reconciliation": {
            "cash_plus_positions": round((cash or 0) + positions_market_value, 4),
            "diff": round(total_value - ((cash or 0) + positions_market_value), 4),
        },
        "trace": {
            "raw_webhook_hash": snapshot_hash,
            "raw_webhook_log": str(JOINQUANT_SIGNAL_LOG_PATH.relative_to(ROOT)),
            "normalized_snapshot_path": str(PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH.relative_to(ROOT)),
            "nav_ledger_path": str(PERFORMANCE_JOINQUANT_NAV_PATH.relative_to(ROOT)),
        },
        "raw_webhook": redact_secret_fields(payload),
    }


def upsert_jsonl_rows(path: Path, rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {
        str(row.get(key)): row
        for row in load_jsonl(path)
        if row.get(key)
    }
    for row in rows:
        row_key = str(row.get(key) or "")
        if row_key:
            merged[row_key] = row
    result = list(merged.values())
    result.sort(key=lambda row: (str(row.get("strategy_id") or ""), str(row.get("as_of") or row.get("date") or ""), str(row.get(key) or "")))
    write_jsonl_atomic(path, result)
    return result


def persist_joinquant_performance_snapshot(
    payload: dict[str, Any],
    normalized_payload: dict[str, Any],
    strategy_id: str,
    endpoint: str,
    storage_path: Path,
    received_at: str,
) -> dict[str, Any] | None:
    snapshot = normalize_joinquant_account_snapshot(payload, normalized_payload, strategy_id, endpoint, storage_path, received_at)
    if snapshot is None:
        return None
    upsert_jsonl_rows(PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH, [snapshot], "snapshot_id")
    rebuild_joinquant_nav_ledger()
    return snapshot


def rebuild_joinquant_nav_ledger() -> list[dict[str, Any]]:
    snapshots = [
        row
        for row in load_jsonl(PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH)
        if row.get("strategy_id") and to_float(row.get("total_value")) is not None and row.get("as_of")
    ]
    snapshots.sort(key=lambda row: (str(row.get("strategy_id")), str(row.get("as_of"))))
    base_by_strategy: dict[str, float] = {}
    ledger: list[dict[str, Any]] = []
    for row in snapshots:
        strategy_id = str(row["strategy_id"])
        total_value = to_float(row.get("total_value"), 0) or 0
        base = base_by_strategy.setdefault(strategy_id, total_value or 1)
        net_value = total_value / (base or 1)
        cash = to_float(row.get("cash"), 0) or 0
        positions_value = to_float(row.get("positions_market_value"), 0) or 0
        ledger.append(
            {
                "snapshot_id": row["snapshot_id"],
                "snapshot_hash": row.get("snapshot_hash"),
                "strategy_id": strategy_id,
                "strategy_label": row.get("strategy_label") or strategy_id,
                "run_id": row.get("run_id"),
                "as_of": row.get("as_of"),
                "date": str(row.get("trade_date") or row.get("as_of"))[:10],
                "trade_date": row.get("trade_date") or str(row.get("as_of"))[:10],
                "net_value": round(net_value, 6),
                "total_value": round(total_value, 4),
                "cash": round(cash, 4),
                "positions_market_value": round(positions_value, 4),
                "cash_plus_positions": round(cash + positions_value, 4),
                "reconciliation_diff": round(total_value - cash - positions_value, 4),
                "position_count": to_int(row.get("position_count"), 0),
                "trade_count": to_int(row.get("trade_count"), 0),
                "source": "joinquant",
                "trace": {
                    **(row.get("trace") if isinstance(row.get("trace"), dict) else {}),
                    "snapshot_id": row["snapshot_id"],
                    "strategy_id": strategy_id,
                    "run_id": row.get("run_id"),
                    "as_of": row.get("as_of"),
                    "calculation": "net_value=total_value/first_total_value",
                },
            }
        )
    write_jsonl_atomic(PERFORMANCE_JOINQUANT_NAV_PATH, ledger)
    return ledger


def load_joinquant_nav_ledger() -> list[dict[str, Any]]:
    rows = load_jsonl(PERFORMANCE_JOINQUANT_NAV_PATH)
    if rows:
        return rows
    if PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH.exists():
        return rebuild_joinquant_nav_ledger()
    return []


def strategy_rows_from_ledger(ledger: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest_by_strategy: dict[str, dict[str, Any]] = {}
    for row in ledger:
        strategy_id = str(row.get("strategy_id") or "")
        if not strategy_id:
            continue
        if strategy_id not in latest_by_strategy or str(row.get("as_of") or "") > str(latest_by_strategy[strategy_id].get("as_of") or ""):
            latest_by_strategy[strategy_id] = row
    return [
        {
            "id": strategy_id,
            "label": row.get("strategy_label") or strategy_id,
            "last_seen": row.get("as_of"),
            "stale_seconds": seconds_since(row.get("as_of")),
            "source": "joinquant",
        }
        for strategy_id, row in sorted(latest_by_strategy.items())
    ]


def fetch_eastmoney_benchmark_nav(benchmark_id: str, days: int = 260) -> dict[str, Any]:
    config = REAL_BENCHMARKS[benchmark_id]
    params = {
        "secid": config["secid"],
        "fields1": "f1,f2,f3,f4,f5",
        "fields2": "f51,f52,f53,f54,f55",
        "klt": "101",
        "fqt": "1",
        "end": "20500101",
        "lmt": str(days),
    }
    url = f"https://push2his.eastmoney.com/api/qt/stock/kline/get?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
    with urllib.request.urlopen(req, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8", "ignore"))
    klines = data.get("data", {}).get("klines", []) if isinstance(data, dict) else []
    rows = []
    for line in klines:
        parts = str(line).split(",")
        if len(parts) < 3:
            continue
        close = to_float(parts[2])
        if close is None:
            continue
        rows.append({"date": parts[0], "value": close, "close": close})
    if not rows:
        raise RuntimeError(f"{benchmark_id} 基准行情为空")
    now = now_hk()
    return {
        "id": benchmark_id,
        "label": config["label"],
        "source": "eastmoney",
        "source_name": "东方财富行情中心",
        "as_of": now.isoformat(),
        "trade_date": rows[-1]["date"],
        "stale_seconds": 0,
        "nav": rows,
    }


def fetch_sina_benchmark_nav(benchmark_id: str, days: int = 260) -> dict[str, Any]:
    config = REAL_BENCHMARKS[benchmark_id]
    params = {
        "symbol": config["sina_symbol"],
        "scale": "240",
        "ma": "no",
        "datalen": str(days),
    }
    url = f"https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn/"})
    with urllib.request.urlopen(req, timeout=8) as response:
        data = json.loads(response.read().decode("utf-8", "ignore"))
    raw_rows = data.get("result", {}).get("data", []) if isinstance(data, dict) else []
    rows = []
    for item in raw_rows:
        if not isinstance(item, dict):
            continue
        close = to_float(item.get("close"))
        day = str(item.get("day") or "").strip()
        if close is None or not day:
            continue
        rows.append({"date": day, "value": close, "close": close})
    if not rows:
        raise RuntimeError(f"{benchmark_id} 新浪基准行情为空")
    now = now_hk()
    return {
        "id": benchmark_id,
        "label": config["label"],
        "source": "sina",
        "source_name": "新浪财经",
        "as_of": now.isoformat(),
        "trade_date": rows[-1]["date"],
        "stale_seconds": 0,
        "nav": rows,
    }


def fetch_real_benchmark_nav(benchmark_id: str, days: int = 260) -> dict[str, Any]:
    errors = []
    for fetcher in (fetch_eastmoney_benchmark_nav, fetch_sina_benchmark_nav):
        try:
            return fetcher(benchmark_id, days)
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def load_benchmark_cache() -> dict[str, Any]:
    try:
        return load_json(PERFORMANCE_BENCHMARK_NAV_PATH)
    except HTTPException:
        return {"meta": {}, "data": {"benchmarks": {}}}


def save_benchmark_cache(cache: dict[str, Any]) -> None:
    write_json_atomic(PERFORMANCE_BENCHMARK_NAV_PATH, cache)


def load_or_refresh_benchmarks() -> dict[str, dict[str, Any]]:
    cache = load_benchmark_cache()
    data = cache.setdefault("data", {})
    benchmarks = data.setdefault("benchmarks", {})
    now = now_hk()
    changed = False
    for benchmark_id in REAL_BENCHMARKS:
        current = benchmarks.get(benchmark_id) if isinstance(benchmarks.get(benchmark_id), dict) else {}
        age = seconds_since(current.get("as_of"), now)
        if current.get("nav") and age is not None and age <= BENCHMARK_CACHE_SECONDS:
            current["stale_seconds"] = age
            current["status"] = "live" if age <= BENCHMARK_CACHE_SECONDS else "stale"
            benchmarks[benchmark_id] = current
            continue
        try:
            benchmarks[benchmark_id] = fetch_real_benchmark_nav(benchmark_id)
            benchmarks[benchmark_id]["status"] = "live"
            changed = True
        except Exception as exc:
            if current:
                current["stale_seconds"] = age
                current["status"] = "stale" if current.get("nav") else "unavailable"
                current["error"] = str(exc)
                benchmarks[benchmark_id] = current
            else:
                benchmarks[benchmark_id] = {
                    "id": benchmark_id,
                    "label": REAL_BENCHMARKS[benchmark_id]["label"],
                    "source": "eastmoney+sina",
                    "source_name": REAL_BENCHMARKS[benchmark_id]["source_name"],
                    "as_of": None,
                    "trade_date": None,
                    "stale_seconds": None,
                    "status": "unavailable",
                    "error": str(exc),
                    "nav": [],
                }
            changed = True
    if changed:
        cache["meta"] = {
            "version": "1.0",
            "source": "eastmoney",
            "as_of": now.isoformat(),
            "trade_date": now.strftime("%Y-%m-%d"),
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(now),
            "run_id": f"benchmark-live-{now.strftime('%Y%m%d-%H%M%S')}",
        }
        save_benchmark_cache(cache)
    return {key: value for key, value in benchmarks.items() if isinstance(value, dict)}


def crop_nav_ledger(rows: list[dict[str, Any]], start_date: date | None, end_date: date) -> list[dict[str, Any]]:
    cropped = []
    for row in rows:
        row_date = parse_row_date(row)
        if row_date is None or row_date > end_date:
            continue
        if start_date and row_date < start_date:
            continue
        cropped.append(row)
    return cropped


def build_performance_payload(strategy: str | None, benchmark: str | None, start: str | None, to: str | None) -> dict[str, Any]:
    ledger = load_joinquant_nav_ledger()
    strategies = strategy_rows_from_ledger(ledger)
    benchmark_disabled = benchmark is not None and benchmark.lower() in {"", "none", "off", "false"}
    benchmarks = load_or_refresh_benchmarks()
    benchmark_id = "" if benchmark_disabled else (benchmark if benchmark in benchmarks else "CSI300")
    query_start = parse_query_date(start, "from")
    query_to = parse_query_date(to, "to")
    now = now_hk()
    today = now.date()
    selected_strategy = strategy or (strategies[0]["id"] if strategies else "")
    if strategy and strategy not in {item["id"] for item in strategies}:
        raise HTTPException(status_code=404, detail=f"策略净值不存在：{strategy}")
    strategy_ledger = [row for row in ledger if row.get("strategy_id") == selected_strategy] if selected_strategy else []
    latest = max(strategy_ledger, key=lambda row: str(row.get("as_of") or ""), default={})
    latest_trade_date = parse_query_date(str(latest.get("trade_date") or "") or None, "trade_date") if latest else None
    end_date = min(query_to or latest_trade_date or today, latest_trade_date or today, today)
    if query_start and query_start > end_date:
        raise HTTPException(status_code=422, detail="from 不能晚于 to 或数据日期")
    strategy_ledger = crop_nav_ledger(strategy_ledger, query_start, end_date)
    equity_curve = [
        {
            "date": row["date"],
            "value": row["net_value"],
            "return_pct": round((to_float(row.get("net_value"), 1) - 1) * 100, 4),
            "source": "joinquant",
            "snapshot_id": row.get("snapshot_id"),
            "snapshot_hash": row.get("snapshot_hash"),
            "strategy_id": row.get("strategy_id"),
            "run_id": row.get("run_id"),
            "as_of": row.get("as_of"),
            "trade_date": row.get("trade_date"),
            "total_value": row.get("total_value"),
            "cash": row.get("cash"),
            "positions_market_value": row.get("positions_market_value"),
            "cash_plus_positions": row.get("cash_plus_positions"),
            "reconciliation_diff": row.get("reconciliation_diff"),
            "trace": row.get("trace") if isinstance(row.get("trace"), dict) else {},
        }
        for row in strategy_ledger
    ]
    benchmark_data = benchmarks.get(benchmark_id, {}) if benchmark_id else {}
    benchmark_curve = normalize_nav_curve(
        benchmark_data.get("nav") if isinstance(benchmark_data.get("nav"), list) else [],
        query_start,
        end_date,
    ) if benchmark_id else []
    monthly_returns = monthly_returns_from_curve(equity_curve, query_start, end_date)
    last_seen = latest.get("as_of") if latest else None
    stale = seconds_since(last_seen, now)
    is_stale = stale is None or stale > PERFORMANCE_STALE_SECONDS
    source_state = "joinquant-pending" if not latest else "joinquant-stale" if is_stale else "joinquant"
    payload = {
        "meta": {
            "version": "1.0",
            "source": source_state,
            "as_of": now.isoformat(),
            "trade_date": (latest.get("trade_date") if latest else today.isoformat()),
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(now),
            "run_id": f"performance-joinquant-{now.strftime('%Y%m%d-%H%M%S')}",
            "refresh_policy": "performance",
            "refresh_seconds": 30,
            "storage_path": str(PERFORMANCE_JOINQUANT_NAV_PATH.relative_to(ROOT)),
            "query": {"strategy": selected_strategy or None, "benchmark": benchmark_id or None, "from": start, "to": to, "effective_to": end_date.isoformat()},
            "last_seen": last_seen,
            "stale_seconds": stale,
            "source_quality": "real" if latest else "pending",
        },
        "data": {
            "strategy": selected_strategy,
            "strategy_label": latest.get("strategy_label") or strategy_label_from_payload(selected_strategy) if selected_strategy else "等待聚宽上报",
            "benchmark": benchmark_data.get("label") or (REAL_BENCHMARKS.get(benchmark_id, {}).get("label") if benchmark_id else None),
            "benchmark_id": benchmark_id or None,
            "strategies": strategies,
            "benchmarks": [
                {
                    "id": key,
                    "label": value.get("label") or key,
                    "source": value.get("source") or "eastmoney",
                    "as_of": value.get("as_of"),
                    "trade_date": value.get("trade_date"),
                    "stale_seconds": value.get("stale_seconds"),
                    "status": value.get("status") or "unknown",
                }
                for key, value in benchmarks.items()
            ],
            "equity_curve": equity_curve,
            "benchmark_curve": benchmark_curve,
            "drawdowns": build_drawdowns(equity_curve),
            "metrics": calculate_metrics(equity_curve, benchmark_curve),
            "monthly_returns": monthly_returns,
            "annotations": [],
            "nav_source": {
                "source": source_state,
                "storage_path": str(PERFORMANCE_JOINQUANT_NAV_PATH.relative_to(ROOT)),
                "snapshot_path": str(PERFORMANCE_JOINQUANT_SNAPSHOTS_PATH.relative_to(ROOT)),
                "last_seen": last_seen,
                "stale_seconds": stale,
                "stale_after_seconds": PERFORMANCE_STALE_SECONDS,
                "point_count": len(equity_curve),
            },
            "benchmark_status": {
                "id": benchmark_id or None,
                "source": benchmark_data.get("source") if benchmark_data else None,
                "source_name": benchmark_data.get("source_name") if benchmark_data else None,
                "as_of": benchmark_data.get("as_of") if benchmark_data else None,
                "trade_date": benchmark_data.get("trade_date") if benchmark_data else None,
                "stale_seconds": benchmark_data.get("stale_seconds") if benchmark_data else None,
                "status": benchmark_data.get("status") if benchmark_data else None,
            },
            "reconciliation": {
                "total_value": latest.get("total_value"),
                "cash": latest.get("cash"),
                "positions_market_value": latest.get("positions_market_value"),
                "cash_plus_positions": latest.get("cash_plus_positions"),
                "diff": latest.get("reconciliation_diff"),
                "formula": "net_value=total_value/first_total_value",
            },
        },
    }
    return validate_response_payload("/api/v1/performance", payload, str(PERFORMANCE_JOINQUANT_NAV_PATH.relative_to(ROOT)))


@app.get("/api/v1/performance")
def performance(
    strategy: str | None = Query(default=None),
    benchmark: str | None = Query(default=None),
    start: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> dict[str, Any]:
    return build_performance_payload(strategy, benchmark, start, to)


def heatmap_group_key(cell: dict[str, Any], group_by: str) -> list[tuple[str, str]]:
    if group_by == "size":
        cap = to_float(cell.get("market_cap") or cell.get("weight"), 0) or 0
        if cap >= 1_000_000_000_000:
            return [("large", "超大市值")]
        if cap >= 200_000_000_000:
            return [("mid", "核心市值")]
        return [("small", "弹性市值")]
    if group_by == "index":
        memberships = cell.get("index_memberships") if isinstance(cell.get("index_memberships"), list) else []
        labels = [str(name) for name in memberships if str(name).strip()]
        if not labels:
            labels = ["未归入指数"]
        return [(label, label) for label in labels]
    label = str(cell.get("sector") or "其他")
    return [(label, label)]


def build_heatmap_groups(cells: list[dict[str, Any]], group_by: str) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for cell in cells:
        weight = to_float(cell.get("market_cap") or cell.get("weight"), 1) or 1
        change = to_float(cell.get("change_pct"))
        for key, label in heatmap_group_key(cell, group_by):
            bucket = grouped.setdefault(
                key,
                {
                    "key": key,
                    "label": label,
                    "weight": 0.0,
                    "market_cap": 0.0,
                    "change_sum": 0.0,
                    "change_weight": 0.0,
                    "children": [],
                },
            )
            bucket["children"].append(cell)
            bucket["weight"] += to_float(cell.get("weight"), 1) or 1
            bucket["market_cap"] += to_float(cell.get("market_cap"), 0) or 0
            if change is not None:
                bucket["change_sum"] += change * weight
                bucket["change_weight"] += weight

    groups = []
    for bucket in grouped.values():
        change_weight = bucket.pop("change_weight")
        change_sum = bucket.pop("change_sum")
        bucket["change_pct"] = round(change_sum / change_weight, 2) if change_weight else None
        bucket["count"] = len(bucket["children"])
        bucket["children"].sort(key=lambda row: row.get("market_cap") or row.get("weight") or 0, reverse=True)
        groups.append(bucket)
    groups.sort(key=lambda row: (row.get("market_cap") or row.get("weight") or 0), reverse=True)
    return groups


@app.get("/api/v1/market/heatmap")
def market_heatmap(
    timeframe: str = Query(default="1D"),
    group_by: str = Query(default="sector"),
    market: str = Query(default="all"),
) -> dict[str, Any]:
    payload = get_payload("/api/v1/market/heatmap")
    payload["meta"]["query"] = {"timeframe": timeframe, "group_by": group_by, "market": market}
    period = timeframe.upper()
    cells = payload.get("data", {}).get("cells", [])
    market_key = market.lower()
    if market_key in {"cn", "us"}:
        cells = [cell for cell in cells if cell.get("market") == market_key]
    normalized_group_by = group_by.lower() if group_by.lower() in {"sector", "size", "index"} else "sector"
    for cell in cells:
        returns = cell.get("returns") if isinstance(cell.get("returns"), dict) else {}
        has_period_return = period in returns and returns[period] is not None
        cell["has_period_return"] = has_period_return
        cell["active_timeframe"] = period
        cell["change_pct"] = returns[period] if has_period_return else None
    if normalized_group_by == "size":
        cells.sort(key=lambda row: row.get("market_cap") or row.get("weight") or 0, reverse=True)
    elif normalized_group_by == "index":
        cells.sort(
            key=lambda row: (
                str((row.get("index_memberships") if isinstance(row.get("index_memberships"), list) else [""]) or [""])[0],
                -(row.get("market_cap") or row.get("weight") or 0),
            )
        )
    else:
        cells.sort(key=lambda row: (str(row.get("sector") or ""), -(row.get("market_cap") or row.get("weight") or 0)))
    groups = build_heatmap_groups(cells, normalized_group_by)
    payload["data"]["timeframe"] = period
    payload["data"]["group_by"] = normalized_group_by
    payload["data"]["market"] = market_key if market_key in {"cn", "us"} else "all"
    payload["data"]["groups"] = groups
    payload["data"]["cells"] = cells
    return validate_response_payload(
        "/api/v1/market/heatmap",
        payload,
        payload.get("meta", {}).get("storage_path") or "data/backend/market/heatmap.json",
    )


@app.get("/api/v1/market/sectors")
def market_sectors(period: str = Query(default="1D")) -> dict[str, Any]:
    payload = get_payload("/api/v1/market/sectors")
    payload["meta"]["query"] = {"period": period}
    return payload


@app.get("/api/v1/market/etf-rankings")
def market_etf_rankings(period: str = Query(default="1D")) -> dict[str, Any]:
    payload = get_payload("/api/v1/market/etf-rankings")
    period_key = {"TODAY": "1D", "WEEK": "5D", "MONTH": "1M", "YEAR": "YTD"}.get(period.upper(), period.upper())
    periods = payload.get("data", {}).get("periods") if isinstance(payload.get("data", {}).get("periods"), dict) else {}
    if period_key in periods:
        payload["data"]["items"] = periods[period_key]
        payload["data"]["period"] = period_key
    payload["meta"]["query"] = {"period": period_key}
    return payload


@app.get("/api/v1/strategies/etf")
def strategy_etf() -> dict[str, Any]:
    payload = get_payload("/api/v1/strategies/etf")
    data = payload.get("data", {})
    logs = data.get("logs") if isinstance(data.get("logs"), list) else []
    if len(logs) < ETF_INLINE_LOG_LINES:
        archive_logs = get_recent_strategy_logs(ETF_INLINE_LOG_LINES, trade_date=payload.get("meta", {}).get("trade_date"))
        if not archive_logs:
            archive_logs = get_recent_strategy_logs(ETF_INLINE_LOG_LINES)
        if archive_logs:
            logs = archive_logs
    data["logs"] = logs[-ETF_INLINE_LOG_LINES:]
    return payload


@app.post("/api/v1/joinquant/signals")
def receive_joinquant_signals(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    verify_action_permission(request)
    verify_joinquant_token(request, payload)
    target_path, strategy_id, storage_path, strategy_kind = joinquant_strategy_target(payload)
    if strategy_kind == "small_cap":
        next_payload = build_small_cap_strategy_payload_from_joinquant(payload)
    else:
        next_payload = build_etf_strategy_payload_from_joinquant(payload)
    received_at = now_hk().isoformat()
    stored_logs = append_strategy_logs(
        payload,
        received_at,
        next_payload["meta"]["run_id"],
        next_payload["meta"]["trade_date"],
        strategy_id,
    )
    if stored_logs:
        next_payload["data"]["logs"] = stored_logs[-ETF_INLINE_LOG_LINES:]
    normalized_next_payload = normalize_payload(
        next_payload,
        ENDPOINTS[target_path],
        "joinquant",
        storage_path,
    )
    performance_snapshot = persist_joinquant_performance_snapshot(
        payload,
        normalized_next_payload,
        strategy_id,
        target_path,
        storage_path,
        received_at,
    )
    if performance_snapshot:
        next_payload.setdefault("data", {})["performance_snapshot"] = {
            "snapshot_id": performance_snapshot["snapshot_id"],
            "total_value": performance_snapshot["total_value"],
            "cash": performance_snapshot["cash"],
            "positions_market_value": performance_snapshot["positions_market_value"],
            "reconciliation_diff": performance_snapshot["reconciliation"]["diff"],
            "nav_ledger_path": performance_snapshot["trace"]["nav_ledger_path"],
        }
        normalized_next_payload.setdefault("data", {})["performance_snapshot"] = next_payload["data"]["performance_snapshot"]
    schema = PAYLOAD_SCHEMAS.get(target_path)
    if schema:
        try:
            validate_payload(
                schema,
                normalized_next_payload,
                str(storage_path.relative_to(ROOT)),
            )
        except SchemaValidationError as exc:
            raise HTTPException(status_code=500, detail=schema_error_detail(exc)) from exc
    write_json_atomic(storage_path, next_payload)
    append_jsonl(
        JOINQUANT_SIGNAL_LOG_PATH,
        {
            "received_at": received_at,
            "run_id": next_payload["meta"]["run_id"],
            "trade_date": next_payload["meta"]["trade_date"],
            "strategy_id": strategy_id,
            "endpoint": target_path,
            "source_ip": request.client.host if request.client else None,
            "log_count": len(stored_logs),
            "payload": redact_secret_fields(payload),
        },
    )
    return validate_response_payload(
        target_path,
        normalized_next_payload,
        str(storage_path.relative_to(ROOT)),
    )


@app.get("/api/v1/strategies/etf/logs")
def strategy_etf_logs(
    limit: int = Query(default=ETF_INLINE_LOG_LINES, ge=1, le=2000),
    trade_date: str | None = Query(default=None),
    run_id: str | None = Query(default=None),
) -> dict[str, Any]:
    rows = get_recent_strategy_logs(limit, trade_date=trade_date, run_id=run_id)
    return {
        "meta": {
            "version": "1.0",
            "source": "joinquant",
            "as_of": now_hk().isoformat(),
            "trade_date": trade_date or now_hk().strftime("%Y-%m-%d"),
            "timezone": "Asia/Hong_Kong",
            "market_session": market_session(),
            "run_id": f"joinquant-logs-{now_hk().strftime('%Y%m%d-%H%M%S')}",
            "storage_path": str(JOINQUANT_FULL_LOG_PATH.relative_to(ROOT)),
        },
        "data": {
            "count": len(rows),
            "items": rows,
        },
    }


@app.get("/api/v1/strategies/small-cap")
def strategy_small_cap() -> dict[str, Any]:
    payload = get_payload("/api/v1/strategies/small-cap")
    if not is_real_joinquant_snapshot(payload):
        return pending_small_cap_payload(payload)
    data = payload.get("data", {})
    logs = data.get("logs") if isinstance(data.get("logs"), list) else []
    if len(logs) < ETF_INLINE_LOG_LINES:
        archive_logs = get_recent_strategy_logs(
            ETF_INLINE_LOG_LINES,
            trade_date=payload.get("meta", {}).get("trade_date"),
            strategy_id="small-cap-momentum",
        )
        if not archive_logs:
            archive_logs = get_recent_strategy_logs(ETF_INLINE_LOG_LINES, strategy_id="small-cap-momentum")
        if archive_logs:
            logs = archive_logs
    data["logs"] = logs[-ETF_INLINE_LOG_LINES:]
    return payload


@app.get("/api/v1/market/breadth")
def market_breadth() -> dict[str, Any]:
    return get_payload("/api/v1/market/breadth")


@app.get("/api/v1/market/sentiment")
def market_sentiment() -> dict[str, Any]:
    return get_payload("/api/v1/market/sentiment")


@app.get("/api/v1/macro")
def macro() -> dict[str, Any]:
    return get_payload("/api/v1/macro")


app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")
app.mount("/src", StaticFiles(directory=ROOT / "src"), name="src")
if (ROOT / "assets").exists():
    app.mount("/assets", StaticFiles(directory=ROOT / "assets"), name="assets")


@app.get("/{page_path:path}", include_in_schema=False)
def static_page(page_path: str) -> FileResponse:
    route = f"/{page_path}" if page_path else "/"
    if page_path in STATIC_FILES:
        return FileResponse(ROOT / page_path)
    filename = STATIC_PAGES.get(route)
    if not filename:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(ROOT / filename)
