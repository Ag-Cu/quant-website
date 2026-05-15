# ==================== 小市值策略网站 Webhook 接入补丁 ====================
# 使用方式：
# 1. 把本段完整粘贴到“涨停基因轮动V2.2”策略源码最后面。
# 2. 修改 SMALL_CAP_WEBHOOK_TOKEN 为服务器 JOINQUANT_WEBHOOK_TOKEN 对应值。
# 3. 不需要删除原有飞书通知；本补丁会额外把策略状态、持仓、目标和日志推送到网站。
#
# 当前正式公网地址：
# - 后端接收入口: https://quant.quantlife.site/api/v1/joinquant/signals
# - 网站策略页面: https://quant.quantlife.site/small-cap.html

import json
import time as _webhook_time

try:
    import requests as _webhook_requests
except Exception:
    _webhook_requests = None

try:
    from urllib import request as _webhook_urllib_request
except Exception:
    _webhook_urllib_request = None


SMALL_CAP_WEBHOOK_URL = "https://quant.quantlife.site/api/v1/joinquant/signals"
SMALL_CAP_WEBHOOK_TOKEN = "replace-with-your-joinquant-webhook-token"
SMALL_CAP_WEBHOOK_TIMEOUT = 5
SMALL_CAP_WEBHOOK_MIN_INTERVAL_SECONDS = 8
SMALL_CAP_WEBHOOK_MAX_LOG_LINES = 1000

_small_cap_webhook_last_sent_at = {}
_small_cap_webhook_log_buffer = []


def _small_cap_now_text():
    try:
        return str(datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        try:
            return str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            return _webhook_time.strftime("%Y-%m-%d %H:%M:%S")


def _small_cap_capture_log(level, message, stage=None):
    try:
        _small_cap_webhook_log_buffer.append({
            "time": _small_cap_now_text(),
            "level": str(level or "info"),
            "stage": str(stage or ""),
            "message": str(message),
        })
        if len(_small_cap_webhook_log_buffer) > SMALL_CAP_WEBHOOK_MAX_LOG_LINES:
            del _small_cap_webhook_log_buffer[:-SMALL_CAP_WEBHOOK_MAX_LOG_LINES]
    except Exception:
        pass


def _small_cap_log_info(message):
    _small_cap_capture_log("info", message, "webhook")
    try:
        log.info(message)
    except Exception:
        print(message)


def _small_cap_log_warning(message):
    _small_cap_capture_log("warning", message, "webhook")
    try:
        log.warning(message)
    except Exception:
        print(message)


def _small_cap_safe_float(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _small_cap_stock_name(stock):
    try:
        return get_security_info(stock).display_name
    except Exception:
        return str(stock)


def _small_cap_industry_name(stock):
    try:
        result = get_industry(security=[stock])
        info = result.get(stock, {})
        return info.get("sw_l2", {}).get("industry_name") or info.get("sw_l1", {}).get("industry_name") or "--"
    except Exception:
        return "--"


def _small_cap_position_payload(context):
    rows = []
    total_value = _small_cap_safe_float(getattr(context.portfolio, "total_value", 0), 0)
    try:
        current_data = get_current_data()
    except Exception:
        current_data = {}
    try:
        for stock, position in context.portfolio.positions.items():
            if getattr(position, "total_amount", 0) <= 0:
                continue
            price = _small_cap_safe_float(getattr(position, "price", 0), 0)
            if price <= 0:
                try:
                    price = _small_cap_safe_float(current_data[stock].last_price, 0)
                except Exception:
                    price = 0
            cost = _small_cap_safe_float(getattr(position, "avg_cost", 0), 0)
            amount = _small_cap_safe_float(getattr(position, "total_amount", 0), 0)
            market_value = _small_cap_safe_float(getattr(position, "value", 0), 0) or amount * price
            rows.append({
                "symbol": stock,
                "name": _small_cap_stock_name(stock),
                "theme": _small_cap_industry_name(stock),
                "quantity": amount,
                "weight_pct": market_value / total_value * 100 if total_value else 0,
                "cost": cost,
                "avg_cost": cost,
                "last_price": price,
                "market_value": market_value,
                "pnl_amount": (price - cost) * amount if cost and price else 0,
                "pnl_pct": (price / cost - 1) * 100 if cost else 0,
                "holding_days": 0,
            })
    except Exception as e:
        _small_cap_log_warning("持仓序列化失败：%s" % e)
    return rows


def _small_cap_portfolio_payload(context, holdings=None):
    holdings = holdings if holdings is not None else _small_cap_position_payload(context)
    total_value = _small_cap_safe_float(getattr(context.portfolio, "total_value", 0), 0)
    cash = _small_cap_safe_float(getattr(context.portfolio, "cash", 0), 0)
    available_cash = _small_cap_safe_float(getattr(context.portfolio, "available_cash", cash), cash)
    positions_market_value = sum(_small_cap_safe_float(row.get("market_value"), 0) for row in holdings)
    return {
        "total_value": total_value,
        "cash": cash,
        "available_cash": available_cash,
        "positions_market_value": positions_market_value,
        "cash_plus_positions": cash + positions_market_value,
        "position_count": len(holdings),
        "current_exposure_pct": positions_market_value / total_value * 100 if total_value else 0,
    }


def _small_cap_trade_payload():
    rows = []
    try:
        trades = get_trades()
        if hasattr(trades, "items"):
            iterable = trades.items()
        else:
            iterable = enumerate(trades or [])
        for trade_id, trade in iterable:
            security = getattr(trade, "security", None) or getattr(trade, "order_book_id", None) or getattr(trade, "symbol", None)
            amount = _small_cap_safe_float(getattr(trade, "amount", 0), 0)
            price = _small_cap_safe_float(getattr(trade, "price", 0), 0)
            rows.append({
                "trade_id": str(trade_id),
                "time": str(getattr(trade, "time", "") or getattr(trade, "datetime", "") or _small_cap_now_text()),
                "symbol": security,
                "action": "buy" if amount > 0 else "sell" if amount < 0 else "",
                "quantity": abs(amount),
                "price": price,
                "value": abs(amount) * price,
            })
    except Exception:
        pass
    return rows[-100:]


def _small_cap_signal_payload(context):
    rows = []
    target_list = list(getattr(g, "target_list", []) or [])
    hold_set = set(getattr(g, "hold_list", []) or [])
    stock_num = max(1, int(getattr(g, "stock_num", 6) or 6))
    try:
        current_data = get_current_data()
    except Exception:
        current_data = {}
    for index, stock in enumerate(target_list[:stock_num * 2], start=1):
        try:
            price = _small_cap_safe_float(current_data[stock].last_price, None)
        except Exception:
            price = None
        action = "hold" if stock in hold_set else "buy"
        rows.append({
            "symbol": stock,
            "name": _small_cap_stock_name(stock),
            "theme": _small_cap_industry_name(stock),
            "signal": action,
            "signal_label": "持有" if action == "hold" else "买入",
            "score": max(0, 100 - (index - 1) * 6),
            "suggested_range": "%.2f" % price if price else "--",
            "last_price": price,
            "change_pct": 0,
            "risk": "mid",
            "liquidity": "正常",
            "invalidation": "止损线 %.0f%% / 大盘趋势止损 %.0f%%" % (
                (1 - _small_cap_safe_float(getattr(g, "stoploss_limit", 0.91), 0.91)) * 100,
                (1 - _small_cap_safe_float(getattr(g, "stoploss_market", 0.93), 0.93)) * 100,
            ),
            "suggested_weight_pct": 100.0 / stock_num,
        })
    return rows


def _small_cap_pool_log_lines(limit=60):
    lines = []
    try:
        target_list = list(getattr(g, "target_list", []) or [])
        hold_list = list(getattr(g, "hold_list", []) or [])
        yesterday_hl = list(getattr(g, "yesterday_HL_list", []) or [])
        lines.append("target_list(%d): %s" % (len(target_list), ",".join(target_list[:80])))
        lines.append("hold_list(%d): %s" % (len(hold_list), ",".join(hold_list[:80])))
        lines.append("yesterday_HL_list(%d): %s" % (len(yesterday_hl), ",".join(yesterday_hl[:80])))
        lines.append("not_buy_again(%d): %s" % (
            len(getattr(g, "not_buy_again", []) or []),
            ",".join((getattr(g, "not_buy_again", []) or [])[:80]),
        ))
        lines.append("loss_black(%d): %s" % (
            len(getattr(g, "loss_black", {}) or {}),
            ",".join(list((getattr(g, "loss_black", {}) or {}).keys())[:80]),
        ))
        lines.append("no_trading_today=%s reason_to_sell=%s stoploss_strategy=%s" % (
            getattr(g, "no_trading_today_signal", None),
            getattr(g, "reason_to_sell", ""),
            getattr(g, "stoploss_strategy", ""),
        ))
    except Exception as e:
        lines.append("pool log failed: %s" % e)
    return [
        {
            "time": _small_cap_now_text(),
            "level": "info",
            "stage": "pool",
            "message": row,
        }
        for row in lines[:limit]
    ]


def _small_cap_position_log_lines(context):
    lines = []
    try:
        for stock, position in context.portfolio.positions.items():
            if getattr(position, "total_amount", 0) <= 0:
                continue
            lines.append({
                "time": _small_cap_now_text(),
                "level": "info",
                "stage": "position",
                "message": "%s %s amount=%s avg_cost=%s price=%s closeable=%s value=%s" % (
                    stock,
                    _small_cap_stock_name(stock),
                    getattr(position, "total_amount", 0),
                    getattr(position, "avg_cost", 0),
                    getattr(position, "price", 0),
                    getattr(position, "closeable_amount", 0),
                    getattr(position, "value", 0),
                ),
            })
    except Exception as e:
        _small_cap_capture_log("warning", "持仓日志生成失败：%s" % e, "position")
    return lines


def _small_cap_collect_logs(context, stage, detail):
    _small_cap_capture_log("info", "%s: %s" % (stage, detail or ""), stage)
    logs = []
    logs.extend(_small_cap_webhook_log_buffer[-760:])
    logs.extend(_small_cap_pool_log_lines())
    logs.extend(_small_cap_position_log_lines(context))
    return logs[-SMALL_CAP_WEBHOOK_MAX_LOG_LINES:]


def _small_cap_summary_payload(context):
    total_value = _small_cap_safe_float(getattr(context.portfolio, "total_value", 0), 0)
    cash = _small_cap_safe_float(getattr(context.portfolio, "cash", 0), 0)
    exposure_pct = (total_value - cash) / total_value * 100 if total_value else 0
    holdings = _small_cap_position_payload(context)
    floating_pnl = 0
    if holdings:
        floating_pnl = sum(_small_cap_safe_float(row.get("pnl_pct"), 0) for row in holdings) / len(holdings)
    target_list = list(getattr(g, "target_list", []) or [])
    return {
        "signal_count": len(target_list),
        "buy_count": len([stock for stock in target_list if stock not in set(getattr(g, "hold_list", []) or [])]),
        "hold_count": len(holdings),
        "exposure_pct": exposure_pct,
        "day_pnl_pct": 0,
        "floating_pnl_pct": floating_pnl,
        "turnover_pct": 0,
    }


def _small_cap_strategy_payload(context, stage, detail):
    now = context.current_dt
    target_list = list(getattr(g, "target_list", []) or [])
    holdings = _small_cap_position_payload(context)
    stock_num = max(1, int(getattr(g, "stock_num", 6) or 6))
    no_trade = bool(getattr(g, "no_trading_today_signal", False))
    return {
        "strategy_name": "涨停基因小市值轮动V2.2",
        "strategy_id": "small-cap-momentum",
        "trade_date": str(now.date()),
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "run_id": "jq-small-cap-%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), stage),
        "strategy": {
            "id": "small-cap-momentum",
            "name": "涨停基因小市值轮动V2.2",
            "status": "paused" if no_trade else "running",
            "stock_num": stock_num,
            "universe_size": int(getattr(g, "init_stock_count", 0) or 0),
            "candidate_count": len(target_list),
            "max_position_pct": 100.0 / stock_num,
            "stop_policy": "个股止损 %.0f%%，大盘趋势止损 %.0f%%" % (
                (1 - _small_cap_safe_float(getattr(g, "stoploss_limit", 0.91), 0.91)) * 100,
                (1 - _small_cap_safe_float(getattr(g, "stoploss_market", 0.93), 0.93)) * 100,
            ),
            "decision_title": stage,
            "decision_detail": detail or "聚宽小市值策略状态已同步到网站。",
            "decision_tone": "warning" if no_trade or getattr(g, "reason_to_sell", "") else "blue",
        },
        "summary": _small_cap_summary_payload(context),
        "portfolio": _small_cap_portfolio_payload(context, holdings),
        "signals": _small_cap_signal_payload(context),
        "holdings": holdings,
        "trades": _small_cap_trade_payload(),
        "risk": {
            "liquidity_pass_pct": 100,
            "concentration_pct": max([_small_cap_safe_float(row.get("weight_pct"), 0) for row in holdings] or [0]),
            "stop_watch_count": len(getattr(g, "loss_black", {}) or {}),
            "volatility_score": 70 if getattr(g, "reason_to_sell", "") else 45,
        },
        "events": [{
            "time": now.strftime("%H:%M"),
            "label": stage,
            "detail": detail or "",
            "status": "done",
        }],
        "logs": _small_cap_collect_logs(context, stage, detail),
    }


def _small_cap_http_post(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Token": SMALL_CAP_WEBHOOK_TOKEN,
        "bypass-tunnel-reminder": "1",
    }
    if _webhook_requests is not None:
        response = _webhook_requests.post(SMALL_CAP_WEBHOOK_URL, data=body, headers=headers, timeout=SMALL_CAP_WEBHOOK_TIMEOUT)
        return response.status_code, response.text[:300]
    if _webhook_urllib_request is not None:
        req = _webhook_urllib_request.Request(SMALL_CAP_WEBHOOK_URL, data=body, headers=headers, method="POST")
        response = _webhook_urllib_request.urlopen(req, timeout=SMALL_CAP_WEBHOOK_TIMEOUT)
        return response.getcode(), response.read().decode("utf-8", "ignore")[:300]
    return 0, "当前环境没有 requests 或 urllib.request"


def post_small_cap_strategy_signal(context, stage, detail=None, force=False):
    now_ts = _webhook_time.time()
    last_ts = _small_cap_webhook_last_sent_at.get(stage, 0)
    if not force and now_ts - last_ts < SMALL_CAP_WEBHOOK_MIN_INTERVAL_SECONDS:
        return False
    _small_cap_webhook_last_sent_at[stage] = now_ts
    payload = _small_cap_strategy_payload(context, stage, detail)
    try:
        status_code, text = _small_cap_http_post(payload)
        if status_code >= 200 and status_code < 300:
            _small_cap_log_info("【网站Webhook】已上报：%s" % stage)
            return True
        _small_cap_log_warning("【网站Webhook】上报失败 HTTP %s: %s" % (status_code, text))
    except Exception as e:
        _small_cap_log_warning("【网站Webhook】上报异常：%s" % e)
    return False


def _small_cap_wrap_function(function_name, stage, detail_func=None, force=False):
    original = globals().get(function_name)
    if original is None or getattr(original, "_small_cap_webhook_wrapped", False):
        return

    def wrapped(context, *args, **kwargs):
        result = original(context, *args, **kwargs)
        detail = None
        try:
            detail = detail_func(context) if detail_func else None
        except Exception as e:
            detail = "detail failed: %s" % e
        post_small_cap_strategy_signal(context, stage, detail, force=force)
        return result

    wrapped._small_cap_webhook_wrapped = True
    globals()[function_name] = wrapped


def _small_cap_install_webhook_patch():
    if globals().get("_SMALL_CAP_WEBHOOK_PATCH_INSTALLED"):
        return
    globals()["_SMALL_CAP_WEBHOOK_PATCH_INSTALLED"] = True

    try:
        original_info = log.info
        original_debug = log.debug
        original_warning = log.warning
        original_error = log.error

        def info_with_capture(message, *args, **kwargs):
            _small_cap_capture_log("info", message, "strategy")
            return original_info(message, *args, **kwargs)

        def debug_with_capture(message, *args, **kwargs):
            _small_cap_capture_log("debug", message, "strategy")
            return original_debug(message, *args, **kwargs)

        def warning_with_capture(message, *args, **kwargs):
            _small_cap_capture_log("warning", message, "strategy")
            return original_warning(message, *args, **kwargs)

        def error_with_capture(message, *args, **kwargs):
            _small_cap_capture_log("error", message, "strategy")
            return original_error(message, *args, **kwargs)

        log.info = info_with_capture
        log.debug = debug_with_capture
        log.warning = warning_with_capture
        log.error = error_with_capture
    except Exception:
        pass

    _small_cap_wrap_function(
        "prepare_stock_list",
        "晨间准备完成",
        lambda context: "持仓 %d 只，昨日涨停 %d 只，今日空仓信号=%s" % (
            len(getattr(g, "hold_list", []) or []),
            len(getattr(g, "yesterday_HL_list", []) or []),
            getattr(g, "no_trading_today_signal", None),
        ),
    )
    _small_cap_wrap_function(
        "weekly_sell",
        "周度卖出执行完成",
        lambda context: "目标 %d 只，持仓 %d 只，卖出原因=%s" % (
            len(getattr(g, "target_list", []) or []),
            len(getattr(g, "hold_list", []) or []),
            getattr(g, "reason_to_sell", ""),
        ),
        force=True,
    )
    _small_cap_wrap_function(
        "weekly_buy",
        "周度买入执行完成",
        lambda context: "目标 %d 只，当前持仓 %d 只" % (
            len(getattr(g, "target_list", []) or []),
            len(getattr(context.portfolio, "positions", {}) or {}),
        ),
        force=True,
    )
    _small_cap_wrap_function("sell_stocks", "止盈止损检查完成", lambda context: "reason_to_sell=%s" % getattr(g, "reason_to_sell", ""))
    _small_cap_wrap_function("trade_afternoon", "午后风控检查完成", lambda context: "reason_to_sell=%s" % getattr(g, "reason_to_sell", ""))
    _small_cap_wrap_function("close_account", "收盘空仓检查完成", lambda context: "cash=%.0f" % _small_cap_safe_float(getattr(context.portfolio, "cash", 0), 0))

    _small_cap_log_info("【网站Webhook】小市值策略补丁已安装")


_small_cap_install_webhook_patch()
