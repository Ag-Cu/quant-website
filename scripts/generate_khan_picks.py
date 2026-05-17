#!/usr/bin/env python3
"""Generate daily picks using the khan-quant-data JoinQuant strategy logic.

The selection rules intentionally mirror
``khan-quant-data/src/backtest/stategy/macd.py::before_market_open``:

- exclude ChiNext ``300`` names, ST names, and stocks listed less than one year
- use the latest completed trade date as ``yesterday``
- compute MA12, MA26, volume ratio, and daily return from 30 daily bars
- keep stocks within +/-5% of min(MA12, MA26), volume ratio >= 1.8,
  and return > 1.5% - CSI300 return
- group by industry and keep the highest volume-ratio stock from the top 5
  industries by average volume ratio
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import tushare as ts


ROOT = Path(__file__).resolve().parents[1]
HK_TZ = ZoneInfo("Asia/Hong_Kong")
STRATEGY_ID = "khan-macd-volume"
STRATEGY_LABEL = "Khan MA 量价选股"


def safe_user_slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower())
    return text.strip(".-") or "default"


def output_path(root: Path, user: str = "") -> Path:
    if user:
        return root / "data" / "backend" / "users" / safe_user_slug(user) / "strategies" / "picks.json"
    return root / "data" / "backend" / "strategies" / "picks.json"


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")
        tmp_name = file.name
    os.replace(tmp_name, path)


def load_existing_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def strategy_value(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("id") or item.get("key") or item.get("value") or item.get("strategy") or item.get("label") or item.get("name") or "")
    return str(item or "")


def merge_picks_payload(existing: dict[str, Any] | None, khan_payload: dict[str, Any]) -> dict[str, Any]:
    if not existing or not isinstance(existing.get("data"), dict):
        return khan_payload
    existing_data = existing.get("data", {})
    khan_data = khan_payload["data"]
    old_items = existing_data.get("items") if isinstance(existing_data.get("items"), list) else []
    kept_items = [
        item for item in old_items
        if not (
            isinstance(item, dict)
            and STRATEGY_ID in {str(item.get("strategy") or ""), str(item.get("strategy_id") or ""), str(item.get("strategy_label") or "")}
        )
    ]
    strategies = existing_data.get("strategies") if isinstance(existing_data.get("strategies"), list) else []
    strategy_by_value = {strategy_value(item): item for item in strategies if strategy_value(item)}
    strategy_by_value[STRATEGY_ID] = {"id": STRATEGY_ID, "label": STRATEGY_LABEL}
    merged_items = [*kept_items, *khan_data["items"]]
    payload = {
        **existing,
        "meta": khan_payload["meta"],
        "data": {
            **existing_data,
            "trade_date": khan_data["trade_date"],
            "status": khan_data["status"],
            "count": len(merged_items),
            "strategies": list(strategy_by_value.values()),
            "items": merged_items,
            "source": khan_data["source"],
        },
    }
    payload["data"].setdefault("strategy", existing_data.get("strategy") or STRATEGY_ID)
    payload["data"].setdefault("strategy_label", existing_data.get("strategy_label") or STRATEGY_LABEL)
    return payload


def to_yyyymmdd(value: date) -> str:
    return value.strftime("%Y%m%d")


def parse_yyyymmdd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def latest_open_trade_date(pro: Any, end_date: date | None = None) -> str:
    end = end_date or datetime.now(HK_TZ).date()
    start = end - timedelta(days=45)
    calendar = pro.trade_cal(exchange="SSE", start_date=to_yyyymmdd(start), end_date=to_yyyymmdd(end), is_open="1")
    if calendar.empty:
        raise RuntimeError("Tushare trade_cal did not return open trade dates")
    dates = sorted(str(item) for item in calendar["cal_date"].tolist())
    return dates[-1]


def fetch_recent_daily(pro: Any, trade_dates: list[str]) -> pd.DataFrame:
    frames = []
    for trade_date in trade_dates:
        frame = pro.daily(trade_date=trade_date)
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError("Tushare daily did not return rows for recent trade dates")
    daily = pd.concat(frames, ignore_index=True)
    daily = daily.rename(columns={"vol": "volume", "pct_chg": "change_pct"})
    required = {"ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "volume", "amount", "change_pct"}
    missing = required - set(daily.columns)
    if missing:
        raise RuntimeError(f"Tushare daily missing columns: {sorted(missing)}")
    daily = daily[list(required)].copy()
    daily["trade_date"] = daily["trade_date"].astype(str)
    for column in ["open", "high", "low", "close", "pre_close", "volume", "amount", "change_pct"]:
        daily[column] = pd.to_numeric(daily[column], errors="coerce")
    return daily.sort_values(["ts_code", "trade_date"])


def previous_trade_dates(pro: Any, end_trade_date: str, count: int = 30) -> list[str]:
    end = parse_yyyymmdd(end_trade_date)
    start = end - timedelta(days=max(75, count * 3))
    calendar = pro.trade_cal(exchange="SSE", start_date=to_yyyymmdd(start), end_date=end_trade_date, is_open="1")
    dates = sorted(str(item) for item in calendar["cal_date"].tolist())
    if len(dates) < count:
        raise RuntimeError(f"Only {len(dates)} open trade dates available before {end_trade_date}")
    return dates[-count:]


def fetch_stock_basic(pro: Any) -> pd.DataFrame:
    fields = "ts_code,symbol,name,area,industry,list_date"
    basic = pro.stock_basic(exchange="", list_status="L", fields=fields)
    if basic.empty:
        raise RuntimeError("Tushare stock_basic returned empty result")
    basic["ts_code"] = basic["ts_code"].astype(str)
    basic["name"] = basic["name"].astype(str)
    basic["industry"] = basic["industry"].fillna("unknown").astype(str)
    basic["list_date"] = basic["list_date"].astype(str)
    return basic


def fetch_sw_l1_industry_map(pro: Any) -> pd.DataFrame:
    """Map each stock to its current SW2021 level-1 industry.

    JoinQuant's source strategy groups preliminary candidates by
    ``get_industry(code, date)['sw_l1']['industry_code']``. Tushare exposes the
    same industry system through SW2021 index memberships, so use that first
    and fall back to ``stock_basic.industry`` if the membership API is
    unavailable or rate-limited.
    """

    try:
        industries = pro.index_classify(src="SW2021", level="L1")
        if industries is None or industries.empty:
            return pd.DataFrame()
        frames = []
        for record in industries.to_dict("records"):
            index_code = str(record.get("index_code") or "")
            if not index_code:
                continue
            industry_name = str(record.get("industry_name") or record.get("index_name") or index_code)
            members = pro.index_member(
                index_code=index_code,
                fields="index_code,index_name,con_code,con_name,in_date,out_date,is_new",
            )
            if members is None or members.empty or "con_code" not in members.columns:
                continue
            current = members.copy()
            if "is_new" in current.columns:
                active = current[current["is_new"].astype(str).str.upper().eq("Y")]
                if not active.empty:
                    current = active
            elif "out_date" in current.columns:
                out_date = current["out_date"].fillna("").astype(str).str.strip()
                current = current[out_date.isin({"", "nan", "None"})]
            current = current[["con_code"]].copy()
            current["industry"] = index_code
            current["industry_name"] = industry_name
            frames.append(current)
        if not frames:
            return pd.DataFrame()
        mapping = pd.concat(frames, ignore_index=True)
        mapping["con_code"] = mapping["con_code"].astype(str)
        mapping = mapping.drop_duplicates("con_code", keep="first")
        return mapping.set_index("con_code")
    except Exception as exc:  # pragma: no cover - depends on remote data quota.
        print(f"warning: SW2021 industry mapping unavailable, fallback to stock_basic.industry: {exc}", file=sys.stderr)
        return pd.DataFrame()


def csi300_return(pro: Any, trade_date: str) -> float:
    dates = previous_trade_dates(pro, trade_date, count=2)
    frame = pro.index_daily(ts_code="000300.SH", start_date=dates[0], end_date=dates[-1])
    if frame.empty or len(frame) < 2:
        return 0.0
    frame = frame.sort_values("trade_date")
    closes = pd.to_numeric(frame["close"], errors="coerce").dropna().tolist()
    if len(closes) < 2 or closes[-2] == 0:
        return 0.0
    return (closes[-1] - closes[-2]) / closes[-2]


def build_stats(
    daily: pd.DataFrame,
    trade_date: str,
    basic: pd.DataFrame,
    index_ret: float,
    industry_map: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for ts_code, group in daily.groupby("ts_code"):
        group = group.sort_values("trade_date").tail(30)
        if len(group) < 26:
            continue
        rows.append(
            {
                "ts_code": ts_code,
                "ma12": group["close"].tail(12).mean(),
                "ma26": group["close"].tail(26).mean(),
                "curr_price": group["close"].iloc[-1],
                "prev_price": group["close"].iloc[-2],
                "curr_vol": group["volume"].iloc[-1],
                "prev_vol": group["volume"].iloc[-2],
            }
        )
    stats = pd.DataFrame(rows).set_index("ts_code") if rows else pd.DataFrame()
    if stats.empty:
        return stats
    stats["low_near"] = stats[["ma12", "ma26"]].min(axis=1)
    stats["vol_ratio"] = stats["curr_vol"] / stats["prev_vol"].replace(0, math.nan)
    stats["ret"] = (stats["curr_price"] - stats["prev_price"]) / stats["prev_price"].replace(0, math.nan)
    merged = stats.join(basic.set_index("ts_code"), how="left")
    merged["industry"] = merged["industry"].fillna("unknown").replace("", "unknown")
    merged["industry_name"] = merged["industry"]
    if industry_map is not None and not industry_map.empty:
        mapped = industry_map.reindex(merged.index)
        if "industry" in mapped.columns:
            merged["industry"] = mapped["industry"].fillna(merged["industry"])
        if "industry_name" in mapped.columns:
            merged["industry_name"] = mapped["industry_name"].fillna(merged["industry_name"])
    one_year_ago = parse_yyyymmdd(trade_date) - timedelta(days=365)
    listed_long_enough = pd.to_datetime(merged["list_date"], format="%Y%m%d", errors="coerce").dt.date < one_year_ago
    non_chinext = ~merged.index.to_series().str.startswith("300")
    non_st = ~merged["name"].fillna("").str.contains("ST", case=False, regex=False)
    mask = (
        non_chinext
        & non_st
        & listed_long_enough
        & (merged["curr_price"] >= merged["low_near"] * 0.95)
        & (merged["curr_price"] <= merged["low_near"] * 1.05)
        & (merged["vol_ratio"] >= 1.8)
        & (merged["ret"] > (0.015 - index_ret))
    )
    return merged[mask].copy()


def pick_by_industry(selected: pd.DataFrame) -> pd.DataFrame:
    if selected.empty:
        return selected
    selected["industry"] = selected["industry"].fillna("unknown").replace("", "unknown")
    top_industries = selected.groupby("industry")["vol_ratio"].mean().nlargest(5).index.tolist()
    rows = []
    for industry in top_industries:
        row = selected[selected["industry"] == industry].sort_values("vol_ratio", ascending=False).iloc[0]
        rows.append(row)
    return pd.DataFrame(rows).reset_index().rename(columns={"index": "ts_code"})


def score_from_volume_ratio(vol_ratio: float) -> int:
    if not math.isfinite(vol_ratio):
        return 60
    return max(60, min(99, round(60 + (vol_ratio - 1.8) * 15)))


def output_items(picks: pd.DataFrame, trade_date: str, index_ret: float, candidate_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, row in enumerate(picks.to_dict("records"), start=1):
        symbol = str(row.get("symbol") or str(row.get("ts_code", "")).split(".")[0])
        name = str(row.get("name") or symbol)
        industry_label = str(row.get("industry_name") or row.get("industry") or "unknown")
        price = float(row.get("curr_price") or 0)
        vol_ratio = float(row.get("vol_ratio") or 0)
        ret_pct = float(row.get("ret") or 0) * 100
        ma12 = float(row.get("ma12") or 0)
        ma26 = float(row.get("ma26") or 0)
        low_near = float(row.get("low_near") or 0)
        score = score_from_volume_ratio(vol_ratio)
        near_score = 100 - min(40, abs(price / low_near - 1) * 800) if low_near else 70
        rows.append(
            {
                "symbol": symbol,
                "ts_code": str(row.get("ts_code") or ""),
                "name": name,
                "strategy": STRATEGY_ID,
                "strategy_id": STRATEGY_ID,
                "strategy_label": STRATEGY_LABEL,
                "trade_date": f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:]}",
                "rank": rank,
                "score": score,
                "confidence": round(score / 100, 2),
                "is_new": True,
                "in_portfolio": False,
                "factors": [
                    {"name": "量比", "value": round(min(100, vol_ratio / 3 * 100)), "weight": 0.45},
                    {"name": "相对指数涨幅", "value": round(min(100, max(0, (ret_pct - (1.5 - index_ret * 100)) * 18 + 60))), "weight": 0.30},
                    {"name": "均线贴近", "value": round(max(0, near_score)), "weight": 0.25},
                ],
                "entry_price": round(price, 3),
                "stop_loss": round(price * 0.92, 3),
                "take_profit": round(price * 1.30, 3),
                "tags": ["Khan", "MA12/MA26", "放量", industry_label],
                "explanation": (
                    f"复刻 khan-quant-data macd.py 入池逻辑：价格在 MA12/MA26 较低者 ±5% 内，"
                    f"量比 {vol_ratio:.2f}，涨幅 {ret_pct:.2f}% 高于 1.5%-沪深300涨幅阈值；"
                    f"所属行业按平均量比进入前5，并选行业内量比最高标的。"
                ),
                "invalidation": "跌破入池价 8% 或 RSI 高位卖出/周度仓位规则触发时退出。",
                "raw_metrics": {
                    "ma12": round(ma12, 4),
                    "ma26": round(ma26, 4),
                    "low_near": round(low_near, 4),
                    "vol_ratio": round(vol_ratio, 4),
                    "ret_pct": round(ret_pct, 4),
                    "index_ret_pct": round(index_ret * 100, 4),
                    "candidate_count": candidate_count,
                },
            }
        )
    return rows


def build_payload(token: str, trade_date: str | None = None) -> dict[str, Any]:
    pro = ts.pro_api(token)
    target_trade_date = trade_date or latest_open_trade_date(pro)
    dates = previous_trade_dates(pro, target_trade_date, count=30)
    basic = fetch_stock_basic(pro)
    industry_map = fetch_sw_l1_industry_map(pro)
    daily = fetch_recent_daily(pro, dates)
    index_ret = csi300_return(pro, target_trade_date)
    selected = build_stats(daily, target_trade_date, basic, index_ret, industry_map)
    picks = pick_by_industry(selected)
    items = output_items(picks, target_trade_date, index_ret, len(selected))
    now = datetime.now(HK_TZ).replace(microsecond=0)
    trade_date_text = f"{target_trade_date[:4]}-{target_trade_date[4:6]}-{target_trade_date[6:]}"
    return {
        "meta": {
            "version": "1.0",
            "source": "tushare+khan-quant-data",
            "as_of": now.isoformat(),
            "trade_date": trade_date_text,
            "timezone": "Asia/Hong_Kong",
            "market_session": "closed",
            "run_id": f"khan-picks-{target_trade_date}-{now.strftime('%H%M%S')}",
            "source_quality": "real",
        },
        "data": {
            "strategy": STRATEGY_ID,
            "strategy_label": STRATEGY_LABEL,
            "trade_date": trade_date_text,
            "status": "ready",
            "count": len(items),
            "strategies": [{"id": STRATEGY_ID, "label": STRATEGY_LABEL}],
            "items": items,
            "source": {
                "repo": "git@github.com:JustinWu00/khan-quant-data.git",
                "logic_file": "src/backtest/stategy/macd.py",
                "data_source": "Tushare daily + SW2021 index_member + stock_basic + CSI300 index_daily",
                "industry_source": "Tushare SW2021 index_member" if not industry_map.empty else "Tushare stock_basic.industry fallback",
                "candidate_count": len(selected),
                "selected_count": len(items),
                "index_return_pct": round(index_ret * 100, 4),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--user", default="")
    parser.add_argument("--trade-date", default="", help="YYYYMMDD; defaults to latest open SSE trade date")
    parser.add_argument("--token", default="", help="Tushare token. Prefer TUSHARE_TOKEN env for production.")
    args = parser.parse_args()
    root = args.root.resolve()
    token = args.token or os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        raise SystemExit("TUSHARE_TOKEN is required")
    payload = build_payload(token, args.trade_date or None)
    path = output_path(root, args.user)
    merged = merge_picks_payload(load_existing_payload(path), payload)
    atomic_write_json(path, merged)
    print(f"wrote {path.relative_to(root)} with {len(payload['data']['items'])} khan picks for {payload['data']['trade_date']}")


if __name__ == "__main__":
    main()
