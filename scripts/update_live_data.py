#!/usr/bin/env python3
"""Generate live JSON payloads for the quant dashboard API.

This script intentionally uses only the Python standard library so it can run
from cron on a clean server. It writes JSON files under data/live/ that the
FastAPI backend can serve for realtime endpoints.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import tempfile
import urllib.parse
import urllib.request
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


HK_TZ = ZoneInfo("Asia/Hong_Kong")
ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "data" / "backend"
LIVE_DIR = ROOT / "data" / "live"
CONFIG_DIR = ROOT / "data" / "config"

EASTMONEY_BOARD_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EASTMONEY_QUOTE_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
SINA_KLINE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData"
SINA_QUOTE_URL = "https://hq.sinajs.cn/list={symbols}"
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SENTIMENT_WARNING_LINE = 0.15
BRILLIANT_WINDOW_MINUTES = 5
SENTIMENT_EXCLUDED_MINUTES = ("09:30", "09:31", "13:01", "14:58", "14:59", "15:00")

WATCHLIST_CONFIG = [
    {"symbol": "NVDA", "name": "NVIDIA Corp", "logo": "N", "sector": "科技股", "provider": "yahoo", "provider_symbol": "NVDA"},
    {"symbol": "TSLA", "name": "Tesla Inc", "logo": "T", "sector": "科技股", "provider": "yahoo", "provider_symbol": "TSLA"},
    {"symbol": "AAPL", "name": "Apple Inc", "logo": "A", "sector": "科技股", "provider": "yahoo", "provider_symbol": "AAPL"},
    {"symbol": "300308", "name": "中际旭创", "logo": "中", "sector": "AI 链", "provider": "eastmoney", "market": "SZ"},
    {"symbol": "002463", "name": "沪电股份", "logo": "沪", "sector": "AI 链", "provider": "eastmoney", "market": "SZ"},
    {"symbol": "600519", "name": "贵州茅台", "logo": "茅", "sector": "消费股", "provider": "eastmoney", "market": "SH"},
]

HEATMAP_CONFIG = [
    {"symbol": "NVDA", "name": "NVIDIA", "sector": "科技", "provider": "yahoo", "provider_symbol": "NVDA", "market_region": "us"},
    {"symbol": "AAPL", "name": "Apple", "sector": "科技", "provider": "yahoo", "provider_symbol": "AAPL", "market_region": "us"},
    {"symbol": "MSFT", "name": "Microsoft", "sector": "科技", "provider": "yahoo", "provider_symbol": "MSFT", "market_region": "us"},
    {"symbol": "TSLA", "name": "Tesla", "sector": "科技", "provider": "yahoo", "provider_symbol": "TSLA", "market_region": "us"},
    {"symbol": "JPM", "name": "JPMorgan", "sector": "金融", "provider": "yahoo", "provider_symbol": "JPM", "market_region": "us"},
    {"symbol": "BAC", "name": "Bank of America", "sector": "金融", "provider": "yahoo", "provider_symbol": "BAC", "market_region": "us"},
    {"symbol": "XOM", "name": "Exxon Mobil", "sector": "能源", "provider": "yahoo", "provider_symbol": "XOM", "market_region": "us"},
    {"symbol": "JNJ", "name": "Johnson & Johnson", "sector": "医疗", "provider": "yahoo", "provider_symbol": "JNJ", "market_region": "us"},
    {"symbol": "300308", "name": "中际旭创", "sector": "AI 链", "provider": "eastmoney", "market": "SZ", "market_region": "cn"},
    {"symbol": "002463", "name": "沪电股份", "sector": "AI 链", "provider": "eastmoney", "market": "SZ", "market_region": "cn"},
    {"symbol": "300476", "name": "胜宏科技", "sector": "AI 链", "provider": "eastmoney", "market": "SZ", "market_region": "cn"},
    {"symbol": "600519", "name": "贵州茅台", "sector": "消费", "provider": "eastmoney", "market": "SH", "market_region": "cn"},
]

ETF_CONFIG = [
    {"symbol": "512100", "name": "中证1000ETF", "market": "SH"},
    {"symbol": "510300", "name": "沪深300ETF", "market": "SH"},
    {"symbol": "159915", "name": "创业板ETF", "market": "SZ"},
]

PERIOD_TO_YAHOO_RANGE = {
    "1D": "5d",
    "5D": "10d",
    "1W": "10d",
    "1M": "1mo",
    "3M": "3mo",
    "YTD": "ytd",
    "1Y": "1y",
}

ETF_PERIOD_ALIASES = {
    "TODAY": "1D",
    "WEEK": "5D",
    "MONTH": "1M",
    "YEAR": "YTD",
}

SENTIMENT_INDEXES = [
    {"symbol": "sh000001", "name": "上证指数", "weight": 0.4},
    {"symbol": "sz399001", "name": "深证成指", "weight": 0.35},
    {"symbol": "sz399006", "name": "创业板指", "weight": 0.25},
]


@dataclass(frozen=True)
class BoardRecord:
    code: str
    name: str
    change_pct: float
    up_count: int
    down_count: int
    flat_count: int

    @property
    def total_count(self) -> int:
        return max(0, self.up_count + self.down_count + self.flat_count)

    @property
    def width_pct(self) -> float:
        if self.total_count <= 0:
            return 0.0
        return round(self.up_count * 100.0 / self.total_count)


@dataclass(frozen=True)
class BreadthSource:
    records: list["BoardRecord"]
    name: str
    quality: str
    universe: str
    industry_standard: str
    notes: list[str]


@dataclass(frozen=True)
class SentimentMinuteRecord:
    timestamp: datetime
    close: float
    volume: float
    symbol: str
    name: str


@dataclass(frozen=True)
class SentimentSignal:
    source_quality: str
    source_name: str
    data_source: str
    source_file: str
    symbol: str
    name: str
    close: float | None
    sentiment_value: float
    temperature: int
    surge_count: int
    last_surge_time: str | None
    status: str
    warning_line: float
    signal_detail: str
    time_window: str
    excluded_minutes: list[str]
    brilliant_window_minutes: int | None
    volatility_formula: str
    surge_rule: str
    trend_value: float


@dataclass(frozen=True)
class QuoteRecord:
    symbol: str
    name: str
    provider: str
    price: float | None
    change_pct: float | None
    change_amount: float | None
    open_price: float | None
    previous_close: float | None
    high: float | None
    low: float | None
    volume: int | None
    turnover: float | None
    market_cap: float | None
    float_market_cap: float | None
    week52_high: float | None = None
    week52_low: float | None = None
    trend: tuple[float, ...] = ()


def now_hk() -> datetime:
    return datetime.now(HK_TZ)


def iso_now() -> str:
    return now_hk().replace(microsecond=0).isoformat()


def trade_date() -> str:
    return now_hk().strftime("%Y-%m-%d")


def mmdd() -> str:
    return now_hk().strftime("%m-%d")


def http_json(url: str, timeout: int = 18) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://quote.eastmoney.com/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_text(url: str, timeout: int = 18, encoding: str = "utf-8") -> str:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "*/*",
            "Referer": "https://finance.sina.com.cn/",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode(encoding, errors="replace")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_watchlist_config() -> list[dict[str, Any]]:
    path = CONFIG_DIR / "watchlist.json"
    if not path.exists():
        return WATCHLIST_CONFIG
    payload = load_json(path)
    items = payload.get("items") if isinstance(payload.get("items"), list) else []
    cleaned = [normalize_watchlist_item(item) for item in items if isinstance(item, dict)]
    return [item for item in cleaned if item.get("symbol")]


def normalize_watchlist_item(item: dict[str, Any]) -> dict[str, Any]:
    symbol = str(item.get("symbol") or "").strip().upper()
    market_region = str(item.get("market_region") or infer_market_region(symbol)).lower()
    provider = item.get("provider") or ("yahoo" if market_region == "us" else "eastmoney")
    normalized = {
        **item,
        "symbol": symbol,
        "name": str(item.get("name") or symbol).strip(),
        "logo": str(item.get("logo") or symbol[:1]).strip(),
        "sector": str(item.get("sector") or ("美股自选" if market_region == "us" else "A股自选")).strip(),
        "provider": provider,
        "market_region": market_region,
    }
    if market_region == "us":
        normalized["provider_symbol"] = str(item.get("provider_symbol") or symbol).strip().upper()
    else:
        normalized["market"] = str(item.get("market") or infer_cn_market(symbol)).upper()
    return normalized


def infer_market_region(symbol: str) -> str:
    return "cn" if symbol.isdigit() else "us"


def infer_cn_market(symbol: str) -> str:
    return "SH" if symbol.startswith(("5", "6", "9")) else "SZ"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
        tmp_name = file.name
    os.replace(tmp_name, path)


def base_payload(name: str) -> dict[str, Any]:
    live_path = LIVE_DIR / f"{name}.json"
    if live_path.exists():
        return load_json(live_path)
    backend_path = BACKEND_DIR / backend_payload_name(name)
    return load_json(backend_path)


def backend_payload_name(name: str) -> str:
    return {
        "overview": "dashboard/overview.json",
        "breadth": "market/breadth.json",
        "sentiment": "market/sentiment.json",
        "macro": "macro.json",
    }.get(name, f"{name}.json")


def normalize_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def normalize_int(value: Any) -> int:
    return int(round(normalize_number(value, 0.0)))


def optional_number(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    number = normalize_number(value, math.nan)
    if math.isnan(number):
        return None
    return number


def eastmoney_market_id(symbol: str, market: str | None = None) -> str:
    if market:
        prefix = "1" if market.upper() in {"SH", "SSE", "XSHG"} else "0"
    else:
        prefix = "1" if symbol.startswith(("5", "6", "9")) else "0"
    return f"{prefix}.{symbol}"


def sina_symbol(symbol: str, market: str | None = None) -> str:
    if market:
        prefix = "sh" if market.upper() in {"SH", "SSE", "XSHG"} else "sz"
    else:
        prefix = "sh" if symbol.startswith(("5", "6", "9")) else "sz"
    return f"{prefix}{symbol}"


def yahoo_symbol(symbol: str, market: str | None = None) -> str:
    if market:
        suffix = ".SS" if market.upper() in {"SH", "SSE", "XSHG"} else ".SZ"
        return f"{symbol}{suffix}"
    if symbol.isdigit():
        suffix = ".SS" if symbol.startswith(("5", "6", "9")) else ".SZ"
        return f"{symbol}{suffix}"
    return symbol


def market_cap_label(value: float | None) -> str:
    if value is None:
        return "--"
    if abs(value) >= 1_000_000_000_000:
        return f"{value / 1_000_000_000_000:.2f}T"
    if abs(value) >= 1_000_000_000:
        return f"{value / 1_000_000_000:.0f}B"
    if abs(value) >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    return f"{value:.0f}"


def safe_pct_position(current: float | None, low: float | None, high: float | None) -> float | None:
    if current is None or low is None or high is None or high <= low:
        return None
    return round(max(0, min(100, (current - low) * 100.0 / (high - low))), 2)


def secids_from_configs(configs: list[dict[str, Any]]) -> str:
    return ",".join(
        eastmoney_market_id(item["symbol"], item.get("market"))
        for item in configs
        if item.get("provider", "eastmoney") == "eastmoney"
    )


def fetch_eastmoney_quotes(configs: list[dict[str, Any]]) -> dict[str, QuoteRecord]:
    secids = secids_from_configs(configs)
    if not secids:
        return {}
    params = {
        "fltt": "2",
        "invt": "2",
        "fields": "f12,f13,f14,f2,f3,f4,f5,f6,f15,f16,f17,f18,f20,f21,f10,f8",
        "secids": secids,
    }
    data = http_json(f"{EASTMONEY_QUOTE_URL}?{urllib.parse.urlencode(params)}")
    rows = data.get("data", {}).get("diff", []) or []
    quotes: dict[str, QuoteRecord] = {}
    for row in rows:
        symbol = str(row.get("f12") or "").strip()
        if not symbol:
            continue
        price = optional_number(row.get("f2"))
        quotes[symbol] = QuoteRecord(
            symbol=symbol,
            name=str(row.get("f14") or symbol),
            provider="eastmoney",
            price=price,
            change_pct=optional_number(row.get("f3")),
            change_amount=optional_number(row.get("f4")),
            open_price=optional_number(row.get("f17")),
            previous_close=optional_number(row.get("f18")),
            high=optional_number(row.get("f15")),
            low=optional_number(row.get("f16")),
            volume=normalize_int(row.get("f5")) if row.get("f5") not in (None, "-") else None,
            turnover=optional_number(row.get("f6")),
            market_cap=optional_number(row.get("f20")),
            float_market_cap=optional_number(row.get("f21")),
            trend=tuple(value for value in [optional_number(row.get("f18")), optional_number(row.get("f17")), optional_number(row.get("f16")), price] if value is not None),
        )
    return quotes


def fetch_sina_quotes(configs: list[dict[str, Any]]) -> dict[str, QuoteRecord]:
    symbols = [
        sina_symbol(item["symbol"], item.get("market"))
        for item in configs
        if item.get("provider", "eastmoney") in {"eastmoney", "sina"}
    ]
    if not symbols:
        return {}
    text = http_text(SINA_QUOTE_URL.format(symbols=",".join(symbols)), encoding="gbk")
    quotes: dict[str, QuoteRecord] = {}
    for market_prefix, symbol, raw in re.findall(r'var hq_str_(sh|sz)(\d+)="([^"]*)";', text):
        fields = raw.split(",")
        if len(fields) < 32 or not fields[0]:
            continue
        name = fields[0]
        open_price = optional_number(fields[1])
        previous_close = optional_number(fields[2])
        price = optional_number(fields[3])
        high = optional_number(fields[4])
        low = optional_number(fields[5])
        volume = normalize_int(fields[8]) if fields[8] else None
        turnover = optional_number(fields[9])
        change_amount = None
        change_pct = None
        if price is not None and previous_close:
            change_amount = round(price - previous_close, 4)
            change_pct = round(change_amount * 100.0 / previous_close, 2)
        quotes[symbol] = QuoteRecord(
            symbol=symbol,
            name=name,
            provider="sina",
            price=price,
            change_pct=change_pct,
            change_amount=change_amount,
            open_price=open_price,
            previous_close=previous_close,
            high=high,
            low=low,
            volume=volume,
            turnover=turnover,
            market_cap=None,
            float_market_cap=None,
            trend=tuple(value for value in [previous_close, open_price, low, price, high] if value is not None),
        )
    return quotes


def fetch_yahoo_quote(symbol: str, display_name: str | None = None) -> QuoteRecord:
    quoted = urllib.parse.quote(symbol, safe="")
    url = f"{YAHOO_CHART_URL.format(symbol=quoted)}?range=5d&interval=1d"
    data = http_json(url)
    result = (data.get("chart", {}).get("result") or [{}])[0]
    meta = result.get("meta", {})
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    closes = [optional_number(value) for value in quote.get("close") or []]
    closes = [value for value in closes if value is not None]
    highs = [optional_number(value) for value in quote.get("high") or []]
    lows = [optional_number(value) for value in quote.get("low") or []]
    opens = [optional_number(value) for value in quote.get("open") or []]
    volumes = [value for value in (quote.get("volume") or []) if value is not None]
    price = optional_number(meta.get("regularMarketPrice")) or (closes[-1] if closes else None)
    previous = optional_number(meta.get("chartPreviousClose"))
    if previous is None and len(closes) >= 2:
        previous = closes[-2]
    change_pct = None
    change_amount = None
    if price is not None and previous:
        change_amount = round(price - previous, 4)
        change_pct = round(change_amount * 100.0 / previous, 2)
    return QuoteRecord(
        symbol=symbol,
        name=display_name or meta.get("longName") or meta.get("shortName") or symbol,
        provider="yahoo",
        price=price,
        change_pct=change_pct,
        change_amount=change_amount,
        open_price=next((value for value in reversed(opens) if value is not None), None),
        previous_close=previous,
        high=optional_number(meta.get("regularMarketDayHigh")) or next((value for value in reversed(highs) if value is not None), None),
        low=optional_number(meta.get("regularMarketDayLow")) or next((value for value in reversed(lows) if value is not None), None),
        volume=normalize_int(meta.get("regularMarketVolume")) if meta.get("regularMarketVolume") is not None else (normalize_int(volumes[-1]) if volumes else None),
        turnover=None,
        market_cap=optional_number(meta.get("marketCap")),
        float_market_cap=None,
        week52_high=optional_number(meta.get("fiftyTwoWeekHigh")),
        week52_low=optional_number(meta.get("fiftyTwoWeekLow")),
        trend=tuple(closes),
    )


def fetch_yahoo_history(symbol: str, period: str = "1M") -> list[float]:
    yahoo_range = PERIOD_TO_YAHOO_RANGE.get(period.upper(), period)
    quoted = urllib.parse.quote(symbol, safe="")
    url = f"{YAHOO_CHART_URL.format(symbol=quoted)}?range={urllib.parse.quote(yahoo_range)}&interval=1d"
    data = http_json(url)
    result = (data.get("chart", {}).get("result") or [{}])[0]
    quote = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
    closes = [optional_number(value) for value in quote.get("close") or []]
    return [value for value in closes if value is not None]


def period_return_from_prices(prices: list[float], period: str) -> float | None:
    clean = [value for value in prices if value is not None]
    if len(clean) < 2:
        return None
    period_key = ETF_PERIOD_ALIASES.get(period.upper(), period.upper())
    lookback = {"1D": 1, "5D": 5, "1W": 5, "1M": 21, "3M": 63, "YTD": len(clean) - 1, "1Y": 252}.get(period_key, 1)
    start_index = max(0, len(clean) - 1 - lookback)
    start = clean[start_index]
    end = clean[-1]
    if not start:
        return None
    return round((end - start) * 100.0 / start, 2)


def fetch_quotes(configs: list[dict[str, Any]]) -> dict[str, QuoteRecord]:
    quotes: dict[str, QuoteRecord] = {}
    try:
        quotes.update(fetch_sina_quotes(configs))
    except Exception as exc:
        print(f"warning: sina quote fetch failed: {exc}")
    missing_em = [
        item for item in configs
        if item.get("provider", "eastmoney") == "eastmoney" and item.get("symbol") not in quotes
    ]
    if missing_em:
        try:
            quotes.update(fetch_eastmoney_quotes(missing_em))
        except Exception as exc:
            print(f"warning: eastmoney quote fetch failed: {exc}")
    for item in configs:
        if item.get("provider") != "yahoo":
            continue
        symbol = item.get("symbol")
        if not symbol:
            continue
        try:
            quotes[symbol] = fetch_yahoo_quote(item.get("provider_symbol", symbol), item.get("name"))
        except Exception as exc:
            print(f"warning: yahoo quote fetch failed for {symbol}: {exc}")
    return quotes


def fetch_industry_boards() -> list[BoardRecord]:
    params = {
        "pn": "1",
        "pz": "100",
        "po": "1",
        "np": "1",
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:2",
        "fields": "f12,f14,f3,f104,f105,f106",
    }
    data = http_json(f"{EASTMONEY_BOARD_URL}?{urllib.parse.urlencode(params)}")
    rows = data.get("data", {}).get("diff", []) or []
    records: list[BoardRecord] = []
    for row in rows:
        name = str(row.get("f14") or "").strip()
        code = str(row.get("f12") or "").strip()
        if not name or not code:
            continue
        records.append(
            BoardRecord(
                code=code,
                name=name,
                change_pct=normalize_number(row.get("f3")),
                up_count=normalize_int(row.get("f104")),
                down_count=normalize_int(row.get("f105")),
                flat_count=normalize_int(row.get("f106")),
            )
        )
    return records


def build_watchlist_payload(quotes: dict[str, QuoteRecord], watchlist_config: list[dict[str, Any]]) -> dict[str, Any]:
    payload = load_json(BACKEND_DIR / "watchlist/list.json")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in watchlist_config:
        quote = quotes.get(item["symbol"])
        if quote is None:
            continue
        grouped.setdefault(item["sector"], []).append(
            {
                "symbol": item["symbol"],
                "name": item.get("name") or quote.name,
                "logo": item.get("logo") or item["symbol"][:1],
                "market_region": item.get("market_region") or ("us" if item.get("provider") == "yahoo" else "cn"),
                "market": item.get("market"),
                "price": quote.price,
                "change_pct": quote.change_pct,
                "intraday_high": quote.high,
                "intraday_low": quote.low,
                "intraday_current": quote.price,
                "volume": quote.volume,
                "volume_ratio": quote.turnover and quote.float_market_cap and round(quote.turnover * 100.0 / quote.float_market_cap, 2),
                "market_cap": market_cap_label(quote.market_cap),
                "week52_low": quote.week52_low or quote.low,
                "week52_high": quote.week52_high or quote.high,
                "week52_current": quote.price,
                "price_series": [{"value": value} for value in quote.trend],
                "data_source": quote.provider,
            }
        )
    payload["data"] = {
        "groups": [{"name": name, "items": items} for name, items in grouped.items()],
    }
    update_meta(payload, "live-watchlist")
    return payload


def heatmap_weight(quote: QuoteRecord) -> int:
    cap = quote.market_cap or quote.float_market_cap
    if cap is None:
        return 14
    if cap >= 2_000_000_000_000:
        return 24
    if cap >= 500_000_000_000:
        return 20
    if cap >= 100_000_000_000:
        return 16
    return 12


def build_heatmap_payload(quotes: dict[str, QuoteRecord]) -> dict[str, Any]:
    payload = load_json(BACKEND_DIR / "market/heatmap.json")
    cells = []
    for item in HEATMAP_CONFIG:
        quote = quotes.get(item["symbol"])
        if quote is None:
            continue
        period_returns: dict[str, float] = {}
        history_symbol = item.get("provider_symbol") if item.get("provider") == "yahoo" else yahoo_symbol(item["symbol"], item.get("market"))
        try:
            history = fetch_yahoo_history(history_symbol, "3M")
            for period in ["1D", "5D", "1M", "3M"]:
                value = period_return_from_prices(history, period)
                if value is not None:
                    period_returns[period] = value
        except Exception as exc:
            print(f"warning: yahoo history failed for {history_symbol}: {exc}")
        cells.append(
            {
                "symbol": item["symbol"],
                "name": item.get("name") or quote.name,
                "sector": item.get("sector") or "--",
                "market": item.get("market_region") or ("us" if item.get("provider") == "yahoo" else "cn"),
                "market_label": "美股" if (item.get("market_region") or ("us" if item.get("provider") == "yahoo" else "cn")) == "us" else "A股",
                "display_name": item.get("name") or quote.name,
                "price": quote.price,
                "change_pct": quote.change_pct,
                "returns": period_returns,
                "volume": quote.volume,
                "market_cap": quote.market_cap,
                "weight": heatmap_weight(quote),
                "data_source": quote.provider,
            }
        )
    payload["data"] = {
        "timeframe": "1D",
        "group_by": "sector",
        "updated_at": iso_now(),
        "cells": cells,
    }
    update_meta(payload, "live-heatmap")
    return payload


def build_etf_rankings_payload(quotes: dict[str, QuoteRecord]) -> dict[str, Any]:
    payload = load_json(BACKEND_DIR / "market/etf-rankings.json")
    rows_by_period: dict[str, list[dict[str, Any]]] = {period: [] for period in ["1D", "5D", "1M", "YTD"]}
    for config in ETF_CONFIG:
        quote = quotes.get(config["symbol"])
        if quote is None:
            continue
        history_symbol = yahoo_symbol(config["symbol"], config.get("market"))
        history: list[float] = list(quote.trend)
        try:
            history = fetch_yahoo_history(history_symbol, "1y")
        except Exception as exc:
            print(f"warning: etf history failed for {history_symbol}: {exc}")
        for period in rows_by_period:
            rows_by_period[period].append(
                {
                    "symbol": config["symbol"],
                    "name": config.get("name") or quote.name,
                    "return_pct": period_return_from_prices(history, period) if history else quote.change_pct,
                    "aum": quote.market_cap,
                    "volume": quote.volume,
                    "turnover": quote.turnover,
                    "sparkline": history[-12:] if history else list(quote.trend),
                    "data_source": quote.provider,
                }
            )
    for period, items in rows_by_period.items():
        items.sort(key=lambda row: normalize_number(row.get("return_pct"), -999), reverse=True)
        for index, item in enumerate(items, 1):
            item["rank"] = index
    payload["data"] = {"period": "1D", "items": rows_by_period["1D"], "periods": rows_by_period}
    update_meta(payload, "live-etf-rankings")
    return payload


def build_sectors_payload(records: list[BoardRecord]) -> dict[str, Any]:
    payload = load_json(BACKEND_DIR / "market/sectors.json")
    sorted_records = sorted(records, key=lambda record: record.change_pct, reverse=True)[:10]
    sectors = []
    for index, record in enumerate(sorted_records, 1):
        sectors.append(
            {
                "id": record.code,
                "name": record.name,
                "icon": "◇",
                "performance_pct": record.change_pct,
                "up_count": record.up_count,
                "down_count": record.down_count,
                "flat_count": record.flat_count,
                "market_cap": None,
                "turnover": None,
                "rank": index,
                "data_source": "eastmoney",
            }
        )
    payload["data"] = {"period": "1D", "updated_at": iso_now(), "sectors": sectors}
    update_meta(payload, "live-sectors")
    return payload


def proxy_industry_boards_from_quotes(quotes: dict[str, QuoteRecord]) -> list[BoardRecord]:
    sector_rows: dict[str, list[QuoteRecord]] = {}
    for item in HEATMAP_CONFIG:
        quote = quotes.get(item["symbol"])
        if quote is None or quote.change_pct is None:
            continue
        sector_rows.setdefault(item.get("sector") or "其他", []).append(quote)
    records: list[BoardRecord] = []
    for index, (sector, rows) in enumerate(sector_rows.items(), 1):
        if not rows:
            continue
        changes = [normalize_number(row.change_pct) for row in rows]
        records.append(
            BoardRecord(
                code=f"proxy-{index}",
                name=sector,
                change_pct=round(sum(changes) / len(changes), 2),
                up_count=sum(1 for value in changes if value > 0),
                down_count=sum(1 for value in changes if value < 0),
                flat_count=sum(1 for value in changes if value == 0),
            )
        )
    return records


def previous_breadth_records() -> list[BoardRecord]:
    for path in (LIVE_DIR / "breadth.json", BACKEND_DIR / "market" / "breadth.json"):
        if not path.exists():
            continue
        try:
            payload = load_json(path)
        except Exception:
            continue
        rows = payload.get("data", {}).get("industry_width", [])
        records: list[BoardRecord] = []
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                continue
            total = max(1, normalize_int(row.get("total_count")) or 100)
            width = max(0, min(100, normalize_number(row.get("width_pct"))))
            up = round(total * width / 100)
            down = max(0, total - up)
            records.append(
                BoardRecord(
                    code=str(row.get("industry_code") or f"previous-{index}"),
                    name=str(row.get("name") or f"历史宽度{index}"),
                    change_pct=normalize_number(row.get("change_pct")),
                    up_count=up,
                    down_count=down,
                    flat_count=0,
                )
            )
        if records:
            return records
    return []


def fetch_eastmoney_all_a_breadth() -> list[BoardRecord]:
    """Fetch whole-market A-share breadth as an index/universe breadth source.

    Eastmoney's clist endpoint can page through all Shanghai/Shenzhen A shares.
    We aggregate advancers/decliners by exchange and by common broad index style
    buckets so the fallback universe is no longer limited to HEATMAP_CONFIG.
    """
    fields = "f12,f14,f3,f13"
    page_size = 500
    rows: list[dict[str, Any]] = []
    for page in range(1, 12):
        params = {
            "pn": str(page),
            "pz": str(page_size),
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
            "fields": fields,
        }
        data = http_json(f"{EASTMONEY_BOARD_URL}?{urllib.parse.urlencode(params)}")
        page_rows = data.get("data", {}).get("diff", []) or []
        if not page_rows:
            break
        rows.extend(row for row in page_rows if isinstance(row, dict))
        if len(page_rows) < page_size:
            break
    if not rows:
        return []

    buckets: dict[str, list[float]] = {
        "全A等权": [],
        "沪市A股": [],
        "深市A股": [],
        "沪深300近似": [],
        "中证500/1000近似": [],
        "创业板近似": [],
    }
    for row in rows:
        code = str(row.get("f12") or "").strip()
        change_pct = optional_number(row.get("f3"))
        if not code or change_pct is None:
            continue
        buckets["全A等权"].append(change_pct)
        if code.startswith("6"):
            buckets["沪市A股"].append(change_pct)
        else:
            buckets["深市A股"].append(change_pct)
        if code.startswith(("600", "601", "603", "000", "001", "002")):
            buckets["沪深300近似"].append(change_pct)
        if code.startswith(("002", "003", "300", "301", "688")):
            buckets["中证500/1000近似"].append(change_pct)
        if code.startswith(("300", "301")):
            buckets["创业板近似"].append(change_pct)

    records: list[BoardRecord] = []
    for index, (name, changes) in enumerate(buckets.items(), 1):
        if not changes:
            continue
        records.append(
            BoardRecord(
                code=f"all-a-{index}",
                name=name,
                change_pct=round(sum(changes) / len(changes), 2),
                up_count=sum(1 for value in changes if value > 0),
                down_count=sum(1 for value in changes if value < 0),
                flat_count=sum(1 for value in changes if value == 0),
            )
        )
    return records


def get_breadth_source(quotes: dict[str, QuoteRecord] | None = None) -> BreadthSource:
    try:
        industry_records = fetch_industry_boards()
        if industry_records:
            return BreadthSource(
                records=industry_records,
                name="东方财富全市场行业板块宽度",
                quality="real",
                universe="东方财富全量行业板块成分股",
                industry_standard="东方财富行业分类",
                notes=["优先使用东方财富行业板块接口 f104/f105/f106 上涨、下跌、平盘成分家数。"],
            )
    except Exception as exc:
        print(f"warning: eastmoney industry board fetch failed: {exc}")

    try:
        market_records = fetch_eastmoney_all_a_breadth()
        if market_records:
            return BreadthSource(
                records=market_records,
                name="东方财富全A/指数成分近似宽度",
                quality="real",
                universe="东方财富沪深 A 股 clist 全市场行情分页",
                industry_standard="全A、沪深交易所、创业板及宽基指数样式代码桶",
                notes=[
                    "当行业板块接口不可用时，分页拉取沪深 A 股全市场涨跌幅。",
                    "沪深300/中证500/1000为公开代码前缀近似桶，用于宽基成分宽度观察，不再依赖 HEATMAP_CONFIG 监控池。",
                ],
            )
    except Exception as exc:
        print(f"warning: eastmoney all-a breadth fetch failed: {exc}")

    proxy_records = proxy_industry_boards_from_quotes(quotes or {})
    proxy_universe = "HEATMAP_CONFIG 监控池真实 quote"
    proxy_notes = ["真实全市场行业/指数成分宽度源不可用，降级为监控池代理指标。"]
    if not proxy_records:
        proxy_records = previous_breadth_records()
        proxy_universe = "上一可用 breadth 快照"
        proxy_notes.append("监控池 quote 同样不可用，沿用上一可用宽度快照并标记为 proxy。")
    return BreadthSource(
        records=proxy_records,
        name="真实行情监控池代理宽度",
        quality="proxy",
        universe=proxy_universe,
        industry_standard="前端监控分组/历史宽度列",
        notes=proxy_notes,
    )


def align_heatmap_rows(old_rows: list[dict[str, Any]], old_columns: list[str], columns: list[str]) -> list[dict[str, Any]]:
    aligned: list[dict[str, Any]] = []
    old_index = {name: index for index, name in enumerate(old_columns)}
    for row in old_rows:
        values = row.get("values") or []
        if not isinstance(values, list):
            continue
        value_by_name = {
            name: normalize_int(values[index])
            for name, index in old_index.items()
            if index < len(values)
        }
        aligned.append(
            {
                "date": row.get("date") or "",
                "values": [value_by_name.get(name, 0) for name in columns],
            }
        )
    return aligned


def build_breadth_payload(source: BreadthSource | list[BoardRecord] | None = None, source_name: str = "东方财富全市场行业板块宽度") -> dict[str, Any]:
    payload = base_payload("breadth")
    if isinstance(source, BreadthSource):
        breadth_source = source
    else:
        records = source if source is not None else fetch_industry_boards()
        breadth_source = BreadthSource(
            records=records,
            name=source_name,
            quality="proxy" if "代理" in source_name else "real",
            universe="东方财富行业板块" if source_name.startswith("东方财富") else "监控池真实 quote",
            industry_standard="东方财富行业分类" if source_name.startswith("东方财富") else "前端监控分组",
            notes=["优先使用东方财富行业板块接口。", "当全市场真实源不可用时，降级为监控池代理宽度。"],
        )
    records = breadth_source.records
    if not records:
        raise RuntimeError("No breadth records returned")

    # Keep a stable, readable industry order by current board list order.
    industry_names = [record.name for record in records]
    columns = ["总体", *industry_names]
    widths = [record.width_pct for record in records]
    overall = round(sum(widths) / max(1, len(widths)))
    today_row = {"date": mmdd(), "values": [overall, *widths]}

    history = payload.get("data", {}).get("heatmap_history", {})
    old_columns = history.get("columns") or columns
    old_rows = align_heatmap_rows(history.get("rows") or [], old_columns, columns)
    rows = [today_row, *[row for row in old_rows if row.get("date") != today_row["date"]]][:10]

    previous_by_name: dict[str, int] = {}
    if len(rows) > 1:
        previous_by_name = dict(zip(columns, rows[1]["values"]))

    industry_width = []
    for record in records:
        prev = previous_by_name.get(record.name, record.width_pct)
        industry_width.append(
            {
                "industry_code": record.code,
                "name": record.name,
                "width_pct": record.width_pct,
                "prev_width_pct": prev,
                "delta_pct": record.width_pct - prev,
                "above_ma20_count": record.up_count,
                "total_count": record.total_count,
                "change_pct": record.change_pct,
            }
        )

    total_up = sum(record.up_count for record in records)
    total_down = sum(record.down_count for record in records)
    total_flat = sum(record.flat_count for record in records)
    total = max(1, total_up + total_down + total_flat)
    up_ratio = round(total_up * 100.0 / total)

    data = payload.setdefault("data", {})
    data["source_algorithm"] = {
        "name": breadth_source.name,
        "source_file": "scripts/update_live_data.py",
        "universe": breadth_source.universe,
        "industry_standard": breadth_source.industry_standard,
        "lookback_days": 10,
        "ma_window_days": None,
        "price_field": "realtime_advancers",
        "formula": "行业上涨家数 / (上涨家数 + 下跌家数 + 平盘家数) * 100",
        "output_table": "data/live/breadth.json",
        "source_quality": breadth_source.quality,
        "notes": breadth_source.notes,
    }
    data["summary"] = {
        **data.get("summary", {}),
        "score": overall,
        "label": "偏强" if overall >= 60 else "中性" if overall >= 45 else "偏弱",
        "market_width_pct": overall,
        "industry_sum_score": overall,
        "industry_count": len(records),
        "up_ratio_pct": up_ratio,
        "above_ma20_pct": overall,
    }
    data["metrics"] = [
        {"name": "总体行业热度", "value": overall, "unit": "%", "detail": "行业上涨家数比例均值"},
        {"name": "上涨家数占比", "value": up_ratio, "unit": "%", "detail": "全部行业成分汇总"},
        {"name": "强势行业数量", "value": sum(1 for value in widths if value >= 70), "unit": "个", "detail": "宽度 >= 70"},
        {"name": "弱势行业数量", "value": sum(1 for value in widths if value < 40), "unit": "个", "detail": "宽度 < 40"},
    ]
    data["industry_width"] = industry_width
    data["heatmap_history"] = {
        "title": "近10日市场热力图",
        "columns": columns,
        "rows": rows,
    }
    update_meta(payload, "live-breadth", source_quality=breadth_source.quality)
    return payload


def append_series(series: list[dict[str, Any]], item: dict[str, Any], limit: int = 80) -> list[dict[str, Any]]:
    date = item.get("date")
    rows = [row for row in series if row.get("date") != date]
    rows.append(item)
    return rows[-limit:]


def sentiment_score_from_value(value: Any) -> float:
    return round(max(0, min(100, normalize_number(value) * 650)))


def recent_sentiment_trend(series: list[dict[str, Any]], days: int = 183) -> list[dict[str, Any]]:
    cutoff = now_hk().date() - timedelta(days=days)
    rows: list[dict[str, Any]] = []
    for row in series:
        raw_date = str(row.get("date") or "")
        try:
            date_value = datetime.fromisoformat(raw_date).date()
        except ValueError:
            continue
        if date_value < cutoff:
            continue
        rows.append(
            {
                "date": raw_date,
                "value": sentiment_score_from_value(row.get("value")),
            }
        )
    return rows


def fetch_sina_index_daily(symbol: str, days: int = 180) -> list[dict[str, Any]]:
    params = {
        "symbol": symbol,
        "scale": "240",
        "ma": "no",
        "datalen": str(days),
    }
    data = http_json(f"{SINA_KLINE_URL}?{urllib.parse.urlencode(params)}", timeout=18)
    rows = data.get("result", {}).get("data", [])
    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = str(row.get("day") or "").strip()
        close = optional_number(row.get("close"))
        high = optional_number(row.get("high"))
        low = optional_number(row.get("low"))
        volume = optional_number(row.get("volume"))
        if not date or close is None:
            continue
        records.append({"date": date, "close": close, "high": high, "low": low, "volume": volume})
    return records


def build_daily_sentiment_trend_from_indexes(days: int = 180) -> list[dict[str, Any]]:
    by_symbol: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for config in SENTIMENT_INDEXES:
        rows = fetch_sina_index_daily(config["symbol"], days)
        if len(rows) >= 30:
            by_symbol.append((config, rows))
    if not by_symbol:
        return []

    daily_scores: dict[str, list[tuple[float, float]]] = {}
    for config, rows in by_symbol:
        closes: list[float] = []
        volumes: list[float] = []
        for row in rows:
            close = normalize_number(row.get("close"))
            high = normalize_number(row.get("high"), close)
            low = normalize_number(row.get("low"), close)
            volume = normalize_number(row.get("volume"))
            previous_close = closes[-1] if closes else close
            closes.append(close)
            volumes.append(volume)
            if len(closes) < 2 or previous_close <= 0:
                continue
            short_window = closes[-5:]
            long_window = closes[-20:]
            vol_window = [value for value in volumes[-20:] if value > 0]
            change_pct = (close - previous_close) * 100.0 / previous_close
            short_momentum = (close - short_window[0]) * 100.0 / short_window[0] if short_window[0] else 0
            long_momentum = (close - long_window[0]) * 100.0 / long_window[0] if long_window[0] else 0
            intraday_range = (high - low) * 100.0 / previous_close if previous_close else 0
            avg_volume = sum(vol_window) / len(vol_window) if vol_window else volume
            volume_heat = (volume / avg_volume - 1) * 18 if avg_volume else 0
            raw_score = 50 + change_pct * 6 + short_momentum * 2.2 + long_momentum * 0.8 + volume_heat + intraday_range * 1.2
            score = round(max(0, min(100, raw_score)), 2)
            daily_scores.setdefault(row["date"], []).append((score, normalize_number(config.get("weight"), 1)))

    trend: list[dict[str, Any]] = []
    for date in sorted(daily_scores):
        rows = daily_scores[date]
        weight_sum = sum(weight for _, weight in rows) or 1
        value = round(sum(score * weight for score, weight in rows) / weight_sum, 2)
        trend.append({"date": date, "value": value})
    return trend[-days:]


def resample_sentiment_trend(series: list[dict[str, Any]], days: int = 126) -> list[dict[str, Any]]:
    anchors = recent_sentiment_trend(series, days=365)
    if not anchors:
        return []
    parsed: list[tuple[date, float]] = []
    for row in anchors:
        try:
            parsed.append((datetime.fromisoformat(str(row["date"])).date(), normalize_number(row["value"], 50)))
        except (KeyError, ValueError):
            continue
    if not parsed:
        return []
    parsed.sort(key=lambda item: item[0])
    start = now_hk().date() - timedelta(days=183)
    current = start
    dates: list[date] = []
    while current <= now_hk().date():
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    dates = dates[-days:]
    output: list[dict[str, Any]] = []
    anchor_index = 0
    for date in dates:
        while anchor_index + 1 < len(parsed) and parsed[anchor_index + 1][0] <= date:
            anchor_index += 1
        left = parsed[anchor_index]
        right = parsed[min(anchor_index + 1, len(parsed) - 1)]
        if right[0] == left[0]:
            value = left[1]
        else:
            ratio = (date - left[0]).days / max(1, (right[0] - left[0]).days)
            value = left[1] + (right[1] - left[1]) * max(0, min(1, ratio))
        output.append({"date": date.isoformat(), "value": round(value, 2)})
    return output


def build_six_month_sentiment_trend(series: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str, str]:
    try:
        trend = build_daily_sentiment_trend_from_indexes(180)
        if len(trend) >= 60:
            return trend, "sina-index-daily", "散户情绪曲线使用新浪上证指数、深证成指、创业板指最近约 180 个交易日的日 K 数据生成；每日分数综合当日涨跌、5 日/20 日动量、振幅和量能热度，归一化到 0-100。"
    except Exception as exc:
        print(f"warning: sina index sentiment trend failed: {exc}")
    trend = resample_sentiment_trend(series)
    return trend, "resampled-snapshot", "散户情绪曲线当前由历史情绪快照按交易日重采样得到，用于避免稀疏点直连；实时源恢复后会优先切回指数日 K 生成的日频曲线。"


def trend_value_from_end(trend: list[dict[str, Any]], offset: int, default: Any = None) -> Any:
    if len(trend) <= offset:
        return default
    return trend[-1 - offset].get("value")



def is_excluded_sentiment_minute(timestamp: datetime) -> bool:
    return timestamp.strftime("%H:%M") in SENTIMENT_EXCLUDED_MINUTES


def parse_sentiment_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    candidates = [raw]
    if " " in raw and "T" not in raw:
        candidates.append(raw.replace(" ", "T", 1))
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.astimezone(HK_TZ) if parsed.tzinfo else parsed.replace(tzinfo=HK_TZ)
        except ValueError:
            continue
    if re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", raw):
        today = now_hk().date()
        try:
            parsed_time = datetime.strptime(raw[:5], "%H:%M").time()
        except ValueError:
            return None
        return datetime.combine(today, parsed_time, HK_TZ)
    return None


def normalize_sentiment_minute_row(row: dict[str, Any], default_symbol: str, default_name: str) -> SentimentMinuteRecord | None:
    timestamp = parse_sentiment_timestamp(row.get("timestamp") or row.get("datetime") or row.get("date") or row.get("time"))
    close = optional_number(row.get("close") or row.get("price") or row.get("last_price"))
    volume = optional_number(row.get("volume") or row.get("vol") or row.get("money") or row.get("turnover"))
    if timestamp is None or close is None or volume is None:
        return None
    return SentimentMinuteRecord(
        timestamp=timestamp,
        close=close,
        volume=volume,
        symbol=str(row.get("symbol") or default_symbol),
        name=str(row.get("name") or default_name),
    )


def parse_sentiment_minute_text(text: str, default_symbol: str, default_name: str) -> list[SentimentMinuteRecord]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    delimiter = "\t" if "\t" in lines[0] else ","
    headers = [part.strip().lower() for part in lines[0].split(delimiter)]
    has_header = any(name in headers for name in ("time", "timestamp", "datetime", "close", "volume"))
    records: list[SentimentMinuteRecord] = []
    data_lines = lines[1:] if has_header else lines
    for line in data_lines:
        parts = [part.strip() for part in line.split(delimiter)]
        if has_header:
            row = {headers[index]: value for index, value in enumerate(parts) if index < len(headers)}
        else:
            row = {"time": parts[0] if parts else "", "close": parts[1] if len(parts) > 1 else "", "volume": parts[2] if len(parts) > 2 else ""}
        record = normalize_sentiment_minute_row(row, default_symbol, default_name)
        if record:
            records.append(record)
    return records


def load_sentiment_minute_records() -> tuple[list[SentimentMinuteRecord], str, str, str]:
    """Load real yy1min/retail sentiment minutes from a configured URL or file.

    Supported env/config inputs:
    - RETAIL_SENTIMENT_MINUTE_URL: JSON/CSV endpoint.
    - RETAIL_SENTIMENT_MINUTE_PATH: JSON/CSV/TXT path; defaults to data/config/retail_sentiment_minutes.json.
    Rows need timestamp/time, close/price and volume/vol fields.
    """
    default_symbol = os.getenv("RETAIL_SENTIMENT_SYMBOL", "159915.XSHE")
    default_name = os.getenv("RETAIL_SENTIMENT_NAME", "创业板ETF")
    source_url = os.getenv("RETAIL_SENTIMENT_MINUTE_URL", "").strip()
    source_path = os.getenv("RETAIL_SENTIMENT_MINUTE_PATH", "").strip()
    source_text = ""
    source_file = ""
    data_source = ""
    if source_url:
        source_text = http_text(source_url, timeout=18)
        source_file = source_url
        data_source = "configured retail sentiment minute URL"
    else:
        path = Path(source_path) if source_path else CONFIG_DIR / "retail_sentiment_minutes.json"
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            return [], str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path), "未配置真实分钟源", default_symbol
        source_text = path.read_text(encoding="utf-8")
        source_file = str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
        data_source = "configured retail sentiment minute file"

    records: list[SentimentMinuteRecord] = []
    try:
        payload = json.loads(source_text)
        if isinstance(payload, dict):
            default_symbol = str(payload.get("symbol") or default_symbol)
            default_name = str(payload.get("name") or default_name)
            raw_rows = payload.get("rows") or payload.get("data") or payload.get("minutes") or []
        else:
            raw_rows = payload
        if isinstance(raw_rows, list):
            for item in raw_rows:
                if isinstance(item, dict):
                    record = normalize_sentiment_minute_row(item, default_symbol, default_name)
                    if record:
                        records.append(record)
    except json.JSONDecodeError:
        records = parse_sentiment_minute_text(source_text, default_symbol, default_name)
    return records, source_file, data_source, default_symbol


def build_real_sentiment_signal() -> SentimentSignal | None:
    records, source_file, data_source, default_symbol = load_sentiment_minute_records()
    records = sorted((row for row in records if not is_excluded_sentiment_minute(row.timestamp)), key=lambda row: row.timestamp)
    if len(records) < BRILLIANT_WINDOW_MINUTES + 3:
        return None
    volumes = [row.volume for row in records]
    mean_volume = sum(volumes) / len(volumes)
    variance = sum((value - mean_volume) ** 2 for value in volumes) / max(1, len(volumes) - 1)
    std_volume = math.sqrt(variance)
    surge_threshold = mean_volume + std_volume
    surge_indexes = [index for index, row in enumerate(records) if row.volume > surge_threshold and index + BRILLIANT_WINDOW_MINUTES <= len(records)]
    vols: list[float] = []
    surge_events: list[dict[str, Any]] = []
    for index in surge_indexes:
        window = records[index:index + BRILLIANT_WINDOW_MINUTES]
        returns: list[float] = []
        for left, right in zip(window, window[1:]):
            if left.close:
                returns.append((right.close - left.close) * 100.0 / left.close)
        if not returns:
            continue
        mean_return = sum(returns) / len(returns)
        return_std = math.sqrt(sum((value - mean_return) ** 2 for value in returns) / max(1, len(returns) - 1))
        vols.append(return_std)
        first = records[index]
        previous_volume = records[index - 1].volume if index else mean_volume
        surge_events.append(
            {
                "time": first.timestamp.strftime("%H:%M"),
                "volume_increase_ratio": round(first.volume / max(previous_volume, 1), 2),
                "return_std": round(return_std, 4),
                "price_change_pct": round((window[-1].close - first.close) * 100.0 / first.close, 4) if first.close else 0,
            }
        )
    daily_brilliant_vol = round(sum(vols) / len(vols), 4) if vols else 0.0
    warning_line = SENTIMENT_WARNING_LINE
    status = "预警" if daily_brilliant_vol >= warning_line else "淡定"
    latest = records[-1]
    first = records[0]
    temperature = round(max(0, min(100, daily_brilliant_vol * 650)))
    return SentimentSignal(
        source_quality="real",
        source_name="真实 1 分钟耀眼波动率",
        data_source=data_source,
        source_file=source_file,
        symbol=latest.symbol or default_symbol,
        name=latest.name or latest.symbol or default_symbol,
        close=latest.close,
        sentiment_value=daily_brilliant_vol,
        temperature=temperature,
        surge_count=len(surge_events),
        last_surge_time=surge_events[-1]["time"] if surge_events else None,
        status=status,
        warning_line=warning_line,
        signal_detail=f"真实分钟源计算值 {'高于' if daily_brilliant_vol >= warning_line else '低于'}预警线 {warning_line:.2f}。",
        time_window=f"{first.timestamp.strftime('%H:%M')} - {latest.timestamp.strftime('%H:%M')}",
        excluded_minutes=list(SENTIMENT_EXCLUDED_MINUTES),
        brilliant_window_minutes=BRILLIANT_WINDOW_MINUTES,
        volatility_formula="成交量激增分钟及后续 4 分钟的 1 分钟收益率标准差均值",
        surge_rule="volume > mean(volume) + std(volume)，并排除开盘/午后首分钟/尾盘集合竞价分钟",
        trend_value=daily_brilliant_vol,
    )


def build_proxy_sentiment_signal(summary: dict[str, Any], industry_width: list[dict[str, Any]]) -> SentimentSignal:
    overall = normalize_number(summary.get("market_width_pct"), 50)
    strong_count = sum(1 for row in industry_width if normalize_number(row.get("width_pct")) >= 70)
    avg_change = sum(normalize_number(row.get("change_pct")) for row in industry_width) / max(1, len(industry_width))
    temperature = round(max(0, min(100, overall * 0.72 + strong_count * 1.5 + max(-5, min(5, avg_change)) * 2 + 18)))
    sentiment_value = round(max(0.02, min(1.1, temperature / 650)), 4)
    warning_line = SENTIMENT_WARNING_LINE
    status = "预警" if sentiment_value >= warning_line else "淡定"
    return SentimentSignal(
        source_quality="proxy",
        source_name="行业/指数宽度散户情绪代理指标",
        data_source="market breadth proxy from data/live/breadth.json",
        source_file="scripts/update_live_data.py",
        symbol="BREADTH_PROXY",
        name="代理指标：全市场宽度热度",
        close=overall,
        sentiment_value=sentiment_value,
        temperature=temperature,
        surge_count=strong_count,
        last_surge_time=now_hk().strftime("%H:%M"),
        status=status,
        warning_line=warning_line,
        signal_detail="真实散户情绪/耀眼波动率分钟源不可用，当前为全市场宽度代理指标。",
        time_window="daily snapshot",
        excluded_minutes=[],
        brilliant_window_minutes=None,
        volatility_formula="sentiment_value = clipped((market_width * 0.72 + strong_industries * 1.5 + avg_industry_change * 2 + 18) / 650)",
        surge_rule="强势行业/指数桶数量（宽度 >= 70）替代分钟成交激增次数",
        trend_value=sentiment_value,
    )


def build_sentiment_payload(breadth: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = base_payload("sentiment")
    if breadth is None:
        breadth = build_breadth_payload()
    summary = breadth.get("data", {}).get("summary", {})
    industry_width = breadth.get("data", {}).get("industry_width", [])

    signal = build_real_sentiment_signal()
    if signal is None:
        signal = build_proxy_sentiment_signal(summary, industry_width)
    today = trade_date()

    data = payload.setdefault("data", {})
    trend = data.get("sentiment_trend") or []
    trend = append_series(trend, {"date": today, "value": signal.trend_value}, limit=80)

    data["source_algorithm"] = {
        "name": signal.source_name,
        "source_file": signal.source_file,
        "data_source": signal.data_source,
        "source_quality": signal.source_quality,
        "time_window": signal.time_window,
        "surge_rule": signal.surge_rule,
        "excluded_minutes": signal.excluded_minutes,
        "brilliant_window_minutes": signal.brilliant_window_minutes,
        "volatility_formula": signal.volatility_formula,
        "warning_line": signal.warning_line,
        "output_fields": ["daily_brilliant_vol", "surge_count", "close", "source_quality"],
    }
    data["summary"] = {
        **data.get("summary", {}),
        "score": signal.temperature,
        "label": "活跃" if signal.temperature >= 70 else "中性" if signal.temperature >= 45 else "低迷",
        "temperature": signal.temperature,
        "daily_brilliant_vol": signal.sentiment_value,
        "surge_count": signal.surge_count,
        "tracked_symbol": signal.symbol,
        "hot_topic_count": signal.surge_count,
        "source_quality": signal.source_quality,
    }
    data["latest_snapshot"] = {
        "updated_at": iso_now(),
        "update_frequency": "分钟源自动更新" if signal.source_quality == "real" else "真实源不可用时降级更新",
        "symbol": signal.symbol,
        "name": signal.name,
        "sentiment_value": signal.sentiment_value,
        "status": signal.status,
        "last_count": signal.surge_count,
        "warning_line": signal.warning_line,
        "source_quality": signal.source_quality,
    }
    data["brilliant_volatility"] = {
        "symbol": signal.symbol,
        "name": signal.name,
        "close": signal.close,
        "daily_brilliant_vol": signal.sentiment_value,
        "surge_count": signal.surge_count,
        "last_surge_time": signal.last_surge_time or "--",
        "intraday_signal": signal.status,
        "signal_detail": signal.signal_detail,
        "baseline": signal.surge_rule,
        "window": signal.time_window,
        "source_quality": signal.source_quality,
    }
    data["sentiment_trend"] = trend
    if signal.source_quality == "real":
        data["gauges"] = [
            {"name": "耀眼波动率", "value": min(100, signal.sentiment_value * 650), "detail": f"预警线 {signal.warning_line:.2f}"},
            {"name": "成交激增次数", "value": min(100, signal.surge_count * 4), "detail": f"窗口 {signal.time_window}"},
            {"name": "排除分钟", "value": min(100, len(signal.excluded_minutes) * 10), "detail": "、".join(signal.excluded_minutes)},
            {"name": "数据质量", "value": 100, "detail": "真实分钟源"},
        ]
    else:
        overall = normalize_number(summary.get("market_width_pct"), 50)
        avg_change = sum(normalize_number(row.get("change_pct")) for row in industry_width) / max(1, len(industry_width))
        data["gauges"] = [
            {"name": "总体行业/指数热度", "value": overall, "detail": "来自市场宽度 live 数据"},
            {"name": "强势行业/指数数量", "value": min(100, signal.surge_count * 4), "detail": f"{signal.surge_count} 个宽度 >= 70"},
            {"name": "平均涨跌", "value": round(max(0, min(100, 50 + avg_change * 10))), "detail": f"{avg_change:.2f}%"},
            {"name": "数据质量", "value": 35, "detail": "代理指标"},
        ]
    top_topics = sorted(industry_width, key=lambda row: normalize_number(row.get("width_pct")), reverse=True)[:8]
    data["topics"] = [
        {
            "name": row.get("name", "--"),
            "heat": normalize_number(row.get("width_pct")),
            "change": normalize_number(row.get("delta_pct")),
            "leader": row.get("industry_code", ""),
        }
        for row in top_topics
    ]
    data["warnings"] = [
        {
            "level": "warning" if signal.sentiment_value >= signal.warning_line else "info",
            "title": "情绪指标已自动更新" if signal.source_quality == "real" else "当前为代理指标",
            "detail": f"当前情绪值 {signal.sentiment_value:.4f}，预警线 {signal.warning_line:.2f}。{signal.signal_detail}",
        }
    ]
    update_meta(payload, "live-sentiment", source_quality=signal.source_quality)
    return payload


def yahoo_latest(symbol: str) -> tuple[float | None, float | None]:
    quoted = urllib.parse.quote(symbol, safe="")
    url = f"{YAHOO_CHART_URL.format(symbol=quoted)}?range=5d&interval=1d"
    data = http_json(url)
    result = (data.get("chart", {}).get("result") or [{}])[0]
    meta = result.get("meta", {})
    price = meta.get("regularMarketPrice")
    closes = (((result.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    cleaned = [normalize_number(value, None) for value in closes if value is not None]
    change_pct = None
    if len(cleaned) >= 2 and cleaned[-2]:
        change_pct = round((cleaned[-1] - cleaned[-2]) * 100.0 / cleaned[-2], 2)
    return (normalize_number(price, None) if price is not None else None, change_pct)


def build_macro_payload() -> dict[str, Any]:
    payload = base_payload("macro")
    data = payload.setdefault("data", {})
    previous_summary = data.get("summary", {})

    try:
        usd_cnh, usd_cnh_change = yahoo_latest("USDCNH=X")
    except Exception as exc:
        print(f"warning: yahoo macro fetch failed for USDCNH=X: {exc}")
        usd_cnh = previous_summary.get("usd_cnh")
        usd_cnh_change = None
    try:
        us10y, us10y_change = yahoo_latest("^TNX")
    except Exception as exc:
        print(f"warning: yahoo macro fetch failed for ^TNX: {exc}")
        us10y = previous_summary.get("us_ten_year_yield_pct")
        us10y_change = None
    if us10y is not None:
        us10y = round(us10y, 3)

    china10y = previous_summary.get("ten_year_yield_pct", 2.31)
    risk_score = previous_summary.get("risk_preference_score", 60)
    spread = None
    if us10y is not None and china10y is not None:
        spread = round(normalize_number(china10y) - normalize_number(us10y), 2)

    data["summary"] = {
        **previous_summary,
        "risk_preference_score": risk_score,
        "label": "中性",
        "ten_year_yield_pct": china10y,
        "us_ten_year_yield_pct": us10y,
        "usd_cnh": usd_cnh,
        "equity_bond_spread_pct": previous_summary.get("equity_bond_spread_pct", 3.84),
    }
    data["rates"] = [
        {"name": "中国 10Y 国债", "value": china10y, "unit": "%", "change_bp": 0},
        {"name": "美国 10Y 国债", "value": us10y, "unit": "%", "change_bp": None if us10y_change is None else round(us10y_change * 100, 1)},
        {"name": "中美 10Y 利差", "value": None if spread is None else round(spread * 100), "unit": "bp", "change_bp": 0},
    ]
    data["fx"] = [
        {"name": "USD/CNH", "value": usd_cnh, "change_pct": usd_cnh_change},
        *[row for row in data.get("fx", []) if row.get("name") != "USD/CNH"],
    ][:4]
    data["observations"] = [
        {"level": "info", "title": "宏观数据已自动更新", "detail": "USD/CNH 与美国 10Y 来自 Yahoo Finance 公共图表接口。"},
        {"level": "warning", "title": "中国 10Y 暂沿用上一值", "detail": "后续接入 AKShare/Tushare 后可替换为真实中国国债收益率。"},
    ]
    update_meta(payload, "live-macro")
    return payload


def build_overview_payload(
    breadth: dict[str, Any],
    sentiment: dict[str, Any],
    macro: dict[str, Any],
    heatmap: dict[str, Any] | None = None,
    etf_rankings: dict[str, Any] | None = None,
    sectors: dict[str, Any] | None = None,
    watchlist: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = base_payload("overview")
    data = payload.setdefault("data", {})
    breadth_summary = breadth.get("data", {}).get("summary", {})
    sentiment_summary = sentiment.get("data", {}).get("summary", {})
    macro_summary = macro.get("data", {}).get("summary", {})

    data["market"] = {
        **data.get("market", {}),
        "breadth_score": breadth_summary.get("score"),
        "sentiment_score": sentiment_summary.get("score"),
        "ten_year_yield_pct": macro_summary.get("ten_year_yield_pct"),
        "usd_cnh": macro_summary.get("usd_cnh"),
        "risk_preference_score": macro_summary.get("risk_preference_score"),
    }
    if heatmap:
        data["heatmap"] = heatmap.get("data", {})
    if etf_rankings:
        data["top_etfs"] = etf_rankings.get("data", {}).get("items", [])
    if sectors:
        data["sectors"] = sectors.get("data", {}).get("sectors", [])
    if watchlist:
        data["watchlist"] = watchlist.get("data", {})
    sentiment_trend = sentiment.get("data", {}).get("sentiment_trend", [])
    if isinstance(data.get("sentiment_gauge"), dict):
        trend_6m, trend_source, trend_note = build_six_month_sentiment_trend(sentiment_trend)
        latest_score = trend_value_from_end(trend_6m, 0, sentiment_summary.get("score") or data["sentiment_gauge"].get("score"))
        previous_day_score = trend_value_from_end(trend_6m, 1, data["sentiment_gauge"].get("previous_day_score"))
        previous_week_score = trend_value_from_end(trend_6m, 5, data["sentiment_gauge"].get("previous_week_score"))
        data["sentiment_gauge"] = {
            **data["sentiment_gauge"],
            "score": latest_score,
            "label": sentiment_summary.get("label") or data["sentiment_gauge"].get("label"),
            "previous_day_score": previous_day_score,
            "previous_week_score": previous_week_score,
            "trend_6m": trend_6m,
            "trend_source": trend_source,
            "calculation_note": trend_note,
        }
    data["decision"] = build_market_decision(data.get("market", {}), data.get("top_etfs", []))
    data["health"] = {
        **data.get("health", {}),
        "backend": "fastapi",
        "scheduler": "cron",
        "latest_job": "update_live_data",
        "latest_job_status": "success",
        "next_run_at": "next scheduled cron run",
        "api_latency_ms": None,
    }
    data["alerts"] = [
        {"level": "info", "title": "真实行情已更新", "detail": "东方财富与 Yahoo 行情已写入 data/live，并由 API 对前端提供。"},
        *data.get("alerts", [])[:2],
    ]
    update_meta(payload, "live-overview")
    return payload


def build_market_decision(market: dict[str, Any], etfs: list[dict[str, Any]]) -> dict[str, str]:
    breadth = normalize_number(market.get("breadth_score"), 0)
    sentiment = normalize_number(market.get("sentiment_score"), 0)
    risk = normalize_number(market.get("risk_preference_score"), 50)
    leading_etf = etfs[0] if etfs else {}
    if breadth >= 60 and risk >= 55:
        return {
            "tone": "positive",
            "title": "真实行情显示市场扩散偏强",
            "detail": f"行业宽度 {breadth:.0f}/100，情绪温度 {sentiment:.0f}/100；ETF 排名领先项为 {leading_etf.get('symbol', '--')}。",
            "action": "保持策略信号跟随",
        }
    if breadth < 45:
        return {
            "tone": "negative",
            "title": "真实行情显示市场宽度偏弱",
            "detail": f"行业宽度 {breadth:.0f}/100，先观察扩散修复再提高仓位。",
            "action": "降低弱信号权重",
        }
    return {
        "tone": "blue",
        "title": "真实行情显示市场处于中性区间",
        "detail": f"行业宽度 {breadth:.0f}/100，情绪温度 {sentiment:.0f}/100，等待更明确的策略信号。",
        "action": "维持观察",
    }


def update_meta(payload: dict[str, Any], run_prefix: str, source_quality: str = "real") -> None:
    payload["meta"] = {
        **payload.get("meta", {}),
        "version": "1.0",
        "source": "live",
        "as_of": iso_now(),
        "trade_date": trade_date(),
        "timezone": "Asia/Hong_Kong",
        "market_session": market_session(),
        "run_id": f"{run_prefix}-{now_hk().strftime('%Y%m%d-%H%M%S')}",
        "stale_seconds": 0,
        "source_quality": source_quality,
    }


def market_session() -> str:
    now = now_hk()
    minutes = now.hour * 60 + now.minute
    if now.weekday() >= 5:
        return "closed"
    if 9 * 60 + 30 <= minutes <= 11 * 60 + 30 or 13 * 60 <= minutes <= 15 * 60:
        return "open"
    if 11 * 60 + 30 < minutes < 13 * 60:
        return "lunch"
    return "closed"


def main() -> None:
    global LIVE_DIR, BACKEND_DIR, CONFIG_DIR, ROOT
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    ROOT = args.root.resolve()
    BACKEND_DIR = ROOT / "data" / "backend"
    LIVE_DIR = ROOT / "data" / "live"
    CONFIG_DIR = ROOT / "data" / "config"

    watchlist_config = load_watchlist_config()
    watched_symbols = {config["symbol"] for config in watchlist_config}
    quote_configs = watchlist_config + [
        item for item in HEATMAP_CONFIG + ETF_CONFIG
        if item["symbol"] not in watched_symbols
    ]
    quotes = fetch_quotes(quote_configs)
    breadth_source = get_breadth_source(quotes)

    watchlist = build_watchlist_payload(quotes, watchlist_config)
    heatmap = build_heatmap_payload(quotes)
    etf_rankings = build_etf_rankings_payload(quotes)
    sectors = build_sectors_payload(breadth_source.records)
    breadth = build_breadth_payload(breadth_source)
    sentiment = build_sentiment_payload(breadth)
    macro = build_macro_payload()
    overview = build_overview_payload(breadth, sentiment, macro, heatmap, etf_rankings, sectors, watchlist)

    write_json(LIVE_DIR / "watchlist.json", watchlist)
    write_json(LIVE_DIR / "heatmap.json", heatmap)
    write_json(LIVE_DIR / "sectors.json", sectors)
    write_json(LIVE_DIR / "etf-rankings.json", etf_rankings)
    write_json(LIVE_DIR / "breadth.json", breadth)
    write_json(LIVE_DIR / "sentiment.json", sentiment)
    write_json(LIVE_DIR / "macro.json", macro)
    write_json(LIVE_DIR / "overview.json", overview)
    print(f"updated live data at {iso_now()}")


if __name__ == "__main__":
    main()
