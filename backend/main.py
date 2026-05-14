from __future__ import annotations

import csv
import json
import hmac
import io
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
BACKEND_DIR = DATA_DIR / "backend"
LIVE_DIR = DATA_DIR / "live"
CONFIG_DIR = DATA_DIR / "config"
WATCHLIST_CONFIG_PATH = CONFIG_DIR / "watchlist.json"
ETF_STRATEGY_PATH = BACKEND_DIR / "strategies" / "etf.json"
JOINQUANT_SIGNAL_LOG_PATH = BACKEND_DIR / "strategies" / "joinquant-signals.jsonl"
JOINQUANT_FULL_LOG_PATH = BACKEND_DIR / "strategies" / "joinquant-full-logs.jsonl"
STRATEGY_PICKS_PARTITION_DIR = BACKEND_DIR / "strategies" / "picks"
MAX_STRATEGY_LOG_LINES = 300
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
        "performance/overview",
        "daily",
        86_400,
        "历史绩效曲线，收盘后由回测和归因任务更新。",
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


app = FastAPI(title="Quant Dashboard API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
        raise HTTPException(status_code=503, detail=f"数据文件不存在: {path.relative_to(ROOT)}") from exc
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"数据文件格式错误: {path.relative_to(ROOT)}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=500, detail=f"数据文件根节点必须是对象: {path.relative_to(ROOT)}")
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


def normalize_strategy_logs(payload: dict[str, Any], received_at: str, run_id: str, trade_date: str) -> list[dict[str, Any]]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    raw_logs = data.get("logs") or data.get("log_lines") or data.get("full_logs") or []
    if isinstance(raw_logs, str):
        raw_logs = raw_logs.splitlines()
    if not isinstance(raw_logs, list):
        return []

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
                "sequence": index + 1,
                "time": timestamp,
                "stage": stage,
                "level": level,
                "message": message,
            }
        )
    return rows


def append_strategy_logs(payload: dict[str, Any], received_at: str, run_id: str, trade_date: str) -> list[dict[str, Any]]:
    rows = normalize_strategy_logs(payload, received_at, run_id, trade_date)
    for row in rows:
        append_jsonl(JOINQUANT_FULL_LOG_PATH, row)
    return rows


def get_recent_strategy_logs(limit: int = 80, trade_date: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    rows = read_jsonl_tail(JOINQUANT_FULL_LOG_PATH, max(limit * 4, limit))
    if trade_date:
        rows = [row for row in rows if row.get("trade_date") == trade_date]
    if run_id:
        rows = [row for row in rows if row.get("run_id") == run_id]
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
    weight_pct = to_float(item.get("weight_pct"))
    if weight_pct is None and market_value is not None and total_value:
        weight_pct = market_value / total_value * 100
    cost = to_float(item.get("cost") or item.get("avg_cost"))
    last_price = to_float(item.get("last_price") or item.get("price"))
    pnl_pct = to_float(item.get("pnl_pct"))
    if pnl_pct is None and cost and last_price:
        pnl_pct = (last_price / cost - 1) * 100
    return {
        "symbol": symbol,
        "name": str(item.get("name") or item.get("etf_name") or symbol or "--"),
        "weight_pct": weight_pct or 0,
        "cost": cost,
        "last_price": last_price,
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
    latest_logs = normalize_strategy_logs(payload, now.isoformat(), run_id, trade_date)[-80:]

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


def available_path(spec: EndpointSpec) -> tuple[Path, str]:
    ensure_fresh_live_data(spec)
    if spec.live_path and spec.live_path.exists():
        return spec.live_path, "live"
    if spec.live_key:
        raise HTTPException(status_code=503, detail=f"{spec.path} 实时数据暂不可用")
    if spec.backend_path.exists():
        return spec.backend_path, "backend"
    raise HTTPException(status_code=503, detail=f"{spec.path} 暂无可用数据")


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
    }
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return {"meta": normalized_meta, "data": data}


def get_payload(path: str) -> dict[str, Any]:
    spec = ENDPOINTS[path]
    data_path, source = available_path(spec)
    payload = load_json(data_path)
    return normalize_payload(payload, spec, source, data_path)


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
            return normalize_payload(load_json(path), spec, "backend", path)
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
def add_watchlist_item(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    item = normalize_watchlist_item(payload)
    config = load_watchlist_config()
    items = config["items"]
    item_key = (item["market_region"], item["symbol"])
    merged = [row for row in items if (row.get("market_region"), row.get("symbol")) != item_key]
    merged.append(item)
    save_watchlist_items(merged)
    invalidate_watchlist_live_data()
    refreshed, detail = run_live_data_refresh()
    if not refreshed:
        raise HTTPException(status_code=503, detail=f"自选股已保存，但行情刷新失败: {detail}")
    return get_payload("/api/v1/watchlist")


@app.delete("/api/v1/watchlist/{symbol}")
def delete_watchlist_item(symbol: str, market_region: str | None = Query(default=None, alias="market")) -> dict[str, Any]:
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
    invalidate_watchlist_live_data()
    refreshed, detail = run_live_data_refresh()
    if not refreshed:
        raise HTTPException(status_code=503, detail=f"自选股已删除，但行情刷新失败: {detail}")
    return get_payload("/api/v1/watchlist")


@app.get("/api/v1/strategies/picks")
def strategy_picks(
    strategy: str | None = Query(default=None),
    date: str | None = Query(default=None),
) -> dict[str, Any]:
    return filtered_strategy_picks(strategy=strategy, date=date)


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
    return get_payload("/api/v1/portfolio/holdings")


@app.get("/api/v1/performance")
def performance(
    strategy: str | None = Query(default=None),
    benchmark: str | None = Query(default=None),
    start: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> dict[str, Any]:
    payload = get_payload("/api/v1/performance")
    payload["meta"]["query"] = {"strategy": strategy, "benchmark": benchmark, "from": start, "to": to}
    return payload


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
    for cell in cells:
        returns = cell.get("returns") if isinstance(cell.get("returns"), dict) else {}
        if period in returns:
            cell["change_pct"] = returns[period]
    if group_by == "size":
        cells.sort(key=lambda row: row.get("market_cap") or row.get("weight") or 0, reverse=True)
    elif group_by == "index":
        cells.sort(key=lambda row: str(row.get("symbol") or ""))
    else:
        cells.sort(key=lambda row: (str(row.get("sector") or ""), -(row.get("market_cap") or row.get("weight") or 0)))
    payload["data"]["timeframe"] = period
    payload["data"]["group_by"] = group_by
    payload["data"]["market"] = market_key if market_key in {"cn", "us"} else "all"
    payload["data"]["cells"] = cells
    return payload


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
    if not logs:
        logs = get_recent_strategy_logs(80, trade_date=payload.get("meta", {}).get("trade_date"))
    data["logs"] = logs[-80:]
    return payload


@app.post("/api/v1/joinquant/signals")
def receive_joinquant_signals(request: Request, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    verify_joinquant_token(request, payload)
    next_payload = build_etf_strategy_payload_from_joinquant(payload)
    received_at = now_hk().isoformat()
    stored_logs = append_strategy_logs(
        payload,
        received_at,
        next_payload["meta"]["run_id"],
        next_payload["meta"]["trade_date"],
    )
    if stored_logs:
        next_payload["data"]["logs"] = stored_logs[-80:]
    write_json_atomic(ETF_STRATEGY_PATH, next_payload)
    append_jsonl(
        JOINQUANT_SIGNAL_LOG_PATH,
        {
            "received_at": received_at,
            "run_id": next_payload["meta"]["run_id"],
            "trade_date": next_payload["meta"]["trade_date"],
            "source_ip": request.client.host if request.client else None,
            "log_count": len(stored_logs),
            "payload": redact_secret_fields(payload),
        },
    )
    return normalize_payload(next_payload, ENDPOINTS["/api/v1/strategies/etf"], "joinquant", ETF_STRATEGY_PATH)


@app.get("/api/v1/strategies/etf/logs")
def strategy_etf_logs(
    limit: int = Query(default=200, ge=1, le=1000),
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
    return get_payload("/api/v1/strategies/small-cap")


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
