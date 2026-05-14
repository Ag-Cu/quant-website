# ==================== 网站 Webhook 接入补丁 ====================
# 使用方式：
# 1. 把本段完整粘贴到“五福闹新春 v4.3”策略源码最后面。
# 2. 不需要修改原来的 initialize/morning_routine/afternoon_routine 等函数。
# 3. 模拟运行时，这段补丁会自动包装关键函数并把信号推送到网站后端。
#
# 当前正式公网地址：
# - 后端接收入口: https://quantlife.site/api/v1/joinquant/signals
# - 网站策略页面: https://quantlife.site/etf.html

import json
import time

try:
    import requests
except Exception:
    requests = None

try:
    from urllib import request as urllib_request
except Exception:
    urllib_request = None


WEBHOOK_URL = "https://quantlife.site/api/v1/joinquant/signals"
WEBHOOK_TOKEN = "6139de478f78edb474c56f19ec715e35eefb88dd289af28038e2ccb21b260b95"
WEBHOOK_TIMEOUT = 5
WEBHOOK_MIN_INTERVAL_SECONDS = 8
WEBHOOK_MAX_LOG_LINES = 260

_webhook_last_sent_at = {}
_webhook_log_buffer = []


def _webhook_now_text():
    try:
        return str(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S")


def _webhook_capture_log(level, message, stage=None):
    try:
        _webhook_log_buffer.append({
            "time": _webhook_now_text(),
            "level": level,
            "stage": stage or "",
            "message": str(message),
        })
        if len(_webhook_log_buffer) > WEBHOOK_MAX_LOG_LINES:
            del _webhook_log_buffer[:-WEBHOOK_MAX_LOG_LINES]
    except Exception:
        pass


def _webhook_log_info(message):
    _webhook_capture_log("info", message, "webhook")
    try:
        log.info(message)
    except Exception:
        print(message)


def _webhook_log_warning(message):
    _webhook_capture_log("warning", message, "webhook")
    try:
        log.warning(message)
    except Exception:
        print(message)


def _webhook_safe_float(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _webhook_jq_code_parts(code):
    raw = str(code or "")
    if "." not in raw:
        return raw, ""
    symbol, suffix = raw.split(".", 1)
    market = {"XSHG": "SH", "XSHE": "SZ"}.get(suffix, suffix)
    return symbol, market


def _webhook_position_payload(context):
    total_value = _webhook_safe_float(getattr(context.portfolio, "total_value", 0), 0)
    rows = []
    try:
        positions = context.portfolio.positions
        for security in positions:
            position = positions[security]
            if getattr(position, "total_amount", 0) <= 0:
                continue
            _symbol, market = _webhook_jq_code_parts(security)
            price = _webhook_safe_float(getattr(position, "price", 0), 0)
            avg_cost = _webhook_safe_float(getattr(position, "avg_cost", 0), 0)
            amount = _webhook_safe_float(getattr(position, "total_amount", 0), 0)
            market_value = amount * price
            rows.append({
                "symbol": security,
                "name": get_security_name(security),
                "market": market,
                "weight_pct": market_value / total_value * 100 if total_value else 0,
                "avg_cost": avg_cost,
                "last_price": price,
                "market_value": market_value,
                "pnl_pct": (price / avg_cost - 1) * 100 if avg_cost else 0,
            })
    except Exception as e:
        _webhook_log_warning("【Webhook】持仓序列化失败：%s" % e)
    return rows


def _webhook_recommendation_payload(context):
    rows = []
    try:
        ranked = getattr(g, "ranked_etfs_result", []) or []
        target_set = set(getattr(g, "target_etfs_list", []) or [])
        holdings_num = max(1, int(getattr(g, "holdings_num", 1) or 1))
        for index, item in enumerate(ranked[:10], start=1):
            if not isinstance(item, dict):
                continue
            code = item.get("etf")
            if not code:
                continue
            is_target = code in target_set
            rows.append({
                "symbol": code,
                "name": item.get("etf_name") or get_security_name(code),
                "action": "buy" if is_target else "watch",
                "action_label": "买入" if is_target else "观察",
                "rank": index,
                "score": item.get("momentum_score"),
                "suggested_weight_pct": 100.0 / holdings_num if is_target else 0,
                "last_price": item.get("current_price"),
                "change_pct": 0,
                "volume_ratio": item.get("volume_ratio"),
                "reason": "动量、R2、成交量、短期风控和动态滤波综合排序",
            })
    except Exception as e:
        _webhook_log_warning("【Webhook】目标信号序列化失败：%s" % e)
    return rows


def _webhook_summary_payload(context):
    target_count = len(getattr(g, "target_etfs_list", []) or [])
    ranked_count = len(getattr(g, "ranked_etfs_result", []) or [])
    total_value = _webhook_safe_float(getattr(context.portfolio, "total_value", 0), 0)
    available_cash = _webhook_safe_float(getattr(context.portfolio, "available_cash", 0), 0)
    current_exposure = (total_value - available_cash) / total_value * 100 if total_value else 0
    max_value = _webhook_safe_float(getattr(g, "max_portfolio_value", 0), 0)
    max_drawdown = (total_value / max_value - 1) * 100 if max_value and total_value else 0
    return {
        "buy_count": target_count,
        "watch_count": max(0, ranked_count - target_count),
        "target_exposure_pct": 100 if target_count else 0,
        "current_exposure_pct": current_exposure,
        "day_pnl_pct": 0,
        "week_pnl_pct": 0,
        "month_pnl_pct": 0,
        "max_drawdown_pct": max_drawdown,
    }


def _webhook_regime_payload():
    risk_state = str(getattr(g, "risk_state", "正常期"))
    current_filter = str(getattr(g, "current_filter", "正常期"))
    is_range_bound = "震荡" in risk_state or "震荡" in current_filter
    return {
        "label": "%s / %s" % (risk_state, current_filter),
        "score": 45 if is_range_bound else 66,
        "factors": [
            {
                "name": "风险状态",
                "value": 45 if is_range_bound else 66,
                "detail": risk_state,
            },
            {
                "name": "动态滤波",
                "value": 50 if is_range_bound else 70,
                "detail": current_filter,
            },
            {
                "name": "合并池",
                "value": min(100, len(getattr(g, "merged_etf_pool", []) or [])),
                "detail": "%s 只 ETF+LOF" % len(getattr(g, "merged_etf_pool", []) or []),
            },
        ],
    }


def _webhook_ranked_log_lines(limit=40):
    lines = []
    try:
        ranked = getattr(g, "ranked_etfs_result", []) or []
        for index, item in enumerate(ranked[:limit], start=1):
            if not isinstance(item, dict):
                continue
            lines.append({
                "time": _webhook_now_text(),
                "level": "info",
                "stage": "rank",
                "message": "%02d %s %s score=%s r2=%s volume_ratio=%s price=%s" % (
                    index,
                    item.get("etf"),
                    item.get("etf_name"),
                    item.get("momentum_score"),
                    item.get("r_squared"),
                    item.get("volume_ratio"),
                    item.get("current_price"),
                ),
            })
    except Exception as e:
        _webhook_capture_log("warning", "排名日志生成失败：%s" % e, "rank")
    return lines


def _webhook_position_log_lines(context):
    lines = []
    try:
        for security, position in context.portfolio.positions.items():
            if getattr(position, "total_amount", 0) <= 0:
                continue
            lines.append({
                "time": _webhook_now_text(),
                "level": "info",
                "stage": "position",
                "message": "%s %s amount=%s avg_cost=%s price=%s closeable=%s" % (
                    security,
                    get_security_name(security),
                    getattr(position, "total_amount", 0),
                    getattr(position, "avg_cost", 0),
                    getattr(position, "price", 0),
                    getattr(position, "closeable_amount", 0),
                ),
            })
    except Exception as e:
        _webhook_capture_log("warning", "持仓日志生成失败：%s" % e, "position")
    return lines


def _webhook_pool_log_lines():
    rows = []
    try:
        rows.append("fixed=%s filtered_fixed=%s dynamic=%s merged=%s" % (
            len(getattr(g, "fixed_etf_pool", []) or []),
            len(getattr(g, "filtered_fixed_pool", []) or []),
            len(getattr(g, "dynamic_etf_pool", []) or []),
            len(getattr(g, "merged_etf_pool", []) or []),
        ))
        rows.append("risk_state=%s current_filter=%s target=%s" % (
            getattr(g, "risk_state", ""),
            getattr(g, "current_filter", ""),
            ",".join(getattr(g, "target_etfs_list", []) or []),
        ))
    except Exception as e:
        rows.append("pool log failed: %s" % e)
    return [
        {
            "time": _webhook_now_text(),
            "level": "info",
            "stage": "pool",
            "message": row,
        }
        for row in rows
    ]


def _webhook_collect_logs(context, stage, detail):
    _webhook_capture_log("info", "%s: %s" % (stage, detail or ""), stage)
    logs = []
    logs.extend(_webhook_log_buffer[-120:])
    logs.extend(_webhook_pool_log_lines())
    logs.extend(_webhook_position_log_lines(context))
    logs.extend(_webhook_ranked_log_lines())
    return logs[-WEBHOOK_MAX_LOG_LINES:]


def _webhook_strategy_payload(context, stage, detail):
    now = context.current_dt
    risk_state = str(getattr(g, "risk_state", "正常期"))
    current_filter = str(getattr(g, "current_filter", "正常期"))
    target_count = len(getattr(g, "target_etfs_list", []) or [])
    return {
        "strategy_name": "五福闹新春 v4.3",
        "strategy_id": "joinquant-wufu-etf-v43",
        "trade_date": str(now.date()),
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "run_id": "jq-wufu-%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), stage),
        "risk_state": risk_state,
        "current_filter": current_filter,
        "strategy": {
            "id": "joinquant-wufu-etf-v43",
            "name": "五福闹新春 v4.3",
            "status": "running",
            "rebalance_time": now.strftime("%H:%M"),
            "risk_budget_pct": 100 if target_count else 0,
            "cash_weight_pct": 0 if target_count else 100,
            "drawdown_guard": "%s / %s" % (risk_state, current_filter),
            "decision_title": stage,
            "decision_detail": detail or "聚宽策略状态已同步到网站。",
            "decision_tone": "warning" if "震荡" in (risk_state + current_filter) else "blue",
        },
        "summary": _webhook_summary_payload(context),
        "regime": _webhook_regime_payload(),
        "recommendations": _webhook_recommendation_payload(context),
        "holdings": _webhook_position_payload(context),
        "events": [{
            "time": now.strftime("%H:%M"),
            "label": stage,
            "detail": detail or "",
            "status": "done",
        }],
        "logs": _webhook_collect_logs(context, stage, detail),
    }


def _webhook_http_post(payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Token": WEBHOOK_TOKEN,
        "bypass-tunnel-reminder": "1",
    }
    if requests is not None:
        response = requests.post(WEBHOOK_URL, data=body, headers=headers, timeout=WEBHOOK_TIMEOUT)
        return response.status_code, response.text[:300]
    if urllib_request is not None:
        req = urllib_request.Request(WEBHOOK_URL, data=body, headers=headers, method="POST")
        response = urllib_request.urlopen(req, timeout=WEBHOOK_TIMEOUT)
        text = response.read().decode("utf-8", "ignore")[:300]
        return response.getcode(), text
    return 0, "当前环境没有 requests 或 urllib.request"


def post_strategy_signal(context, stage, detail=None, force=False):
    now_ts = time.time()
    last_ts = _webhook_last_sent_at.get(stage, 0)
    if not force and now_ts - last_ts < WEBHOOK_MIN_INTERVAL_SECONDS:
        return False
    _webhook_last_sent_at[stage] = now_ts
    payload = _webhook_strategy_payload(context, stage, detail)
    try:
        status_code, text = _webhook_http_post(payload)
        if status_code >= 200 and status_code < 300:
            _webhook_log_info("【Webhook】已上报：%s" % stage)
            return True
        _webhook_log_warning("【Webhook】上报失败 HTTP %s: %s" % (status_code, text))
    except Exception as e:
        _webhook_log_warning("【Webhook】上报异常：%s" % e)
    return False


if not globals().get("_WUFU_WEBHOOK_PATCH_INSTALLED"):
    _WUFU_WEBHOOK_PATCH_INSTALLED = True

    _WUFU_ORIGINAL_LOG_INFO = None
    _WUFU_ORIGINAL_LOG_WARNING = None
    _WUFU_ORIGINAL_LOG_ERROR = None
    try:
        _WUFU_ORIGINAL_LOG_INFO = log.info
        _WUFU_ORIGINAL_LOG_WARNING = log.warning
        _WUFU_ORIGINAL_LOG_ERROR = log.error

        def _wufu_log_info_with_capture(message, *args, **kwargs):
            _webhook_capture_log("info", message, "strategy")
            return _WUFU_ORIGINAL_LOG_INFO(message, *args, **kwargs)

        def _wufu_log_warning_with_capture(message, *args, **kwargs):
            _webhook_capture_log("warning", message, "strategy")
            return _WUFU_ORIGINAL_LOG_WARNING(message, *args, **kwargs)

        def _wufu_log_error_with_capture(message, *args, **kwargs):
            _webhook_capture_log("error", message, "strategy")
            return _WUFU_ORIGINAL_LOG_ERROR(message, *args, **kwargs)

        log.info = _wufu_log_info_with_capture
        log.warning = _wufu_log_warning_with_capture
        log.error = _wufu_log_error_with_capture
    except Exception as e:
        _webhook_capture_log("warning", "日志捕获包装失败：%s" % e, "webhook")

    _WUFU_ORIGINAL_MORNING_ROUTINE = morning_routine
    _WUFU_ORIGINAL_CALCULATE_AND_LOG_RANKED_ETFS = calculate_and_log_ranked_etfs
    _WUFU_ORIGINAL_EXECUTE_SELL_TRADES = execute_sell_trades
    _WUFU_ORIGINAL_EXECUTE_BUY_TRADES = execute_buy_trades
    _WUFU_ORIGINAL_MINUTE_LEVEL_STOP_LOSS = minute_level_stop_loss
    _WUFU_ORIGINAL_MINUTE_LEVEL_PCT_STOP_LOSS = minute_level_pct_stop_loss

    def morning_routine(context):
        _WUFU_ORIGINAL_MORNING_ROUTINE(context)
        post_strategy_signal(
            context,
            "晨间池更新完成",
            "固定池%s只，动态池%s只，合并池%s只" % (
                len(getattr(g, "filtered_fixed_pool", []) or []),
                len(getattr(g, "dynamic_etf_pool", []) or []),
                len(getattr(g, "merged_etf_pool", []) or []),
            ),
        )

    def calculate_and_log_ranked_etfs(context):
        _WUFU_ORIGINAL_CALCULATE_AND_LOG_RANKED_ETFS(context)
        post_strategy_signal(
            context,
            "午后目标生成",
            "完成动量排序，候选结果%s只" % len(getattr(g, "ranked_etfs_result", []) or []),
        )

    def execute_sell_trades(context):
        _WUFU_ORIGINAL_EXECUTE_SELL_TRADES(context)
        post_strategy_signal(
            context,
            "卖出执行完成",
            "目标列表：%s" % ",".join(getattr(g, "target_etfs_list", []) or []),
        )

    def execute_buy_trades(context):
        _WUFU_ORIGINAL_EXECUTE_BUY_TRADES(context)
        post_strategy_signal(
            context,
            "买入执行完成",
            "当前持仓%s只" % len([
                sec for sec, pos in context.portfolio.positions.items()
                if getattr(pos, "total_amount", 0) > 0
            ]),
        )

    def minute_level_stop_loss(context):
        before = bool(getattr(g, "stop_loss_triggered_today", False))
        _WUFU_ORIGINAL_MINUTE_LEVEL_STOP_LOSS(context)
        after = bool(getattr(g, "stop_loss_triggered_today", False))
        if (not before) and after:
            post_strategy_signal(context, "分钟级固定止损触发", "固定比例止损已触发", force=True)

    def minute_level_pct_stop_loss(context):
        before = bool(getattr(g, "stop_loss_triggered_today", False))
        _WUFU_ORIGINAL_MINUTE_LEVEL_PCT_STOP_LOSS(context)
        after = bool(getattr(g, "stop_loss_triggered_today", False))
        if (not before) and after:
            post_strategy_signal(context, "分钟级跌幅止损触发", "当日跌幅止损已触发", force=True)

    _webhook_log_info("【Webhook】五福闹新春 v4.3 网站信号接入补丁已安装")
