# 聚宽策略 Webhook 接入

目标：聚宽策略继续在聚宽运行和下单，网站只接收策略信号并更新“量化策略”和“持仓信息”页面。

## 网站后端

推荐的新策略接收入口：

```text
POST /api/v1/quant/strategies/{strategy_id}/snapshot
```

兼容旧接收入口：

```text
POST /api/v1/joinquant/signals
```

新策略先在网页端“量化策略”页面创建，创建后即可使用对应的 `{strategy_id}` 上报快照。旧入口仍兼容 ETF 和小盘策略。

启动时需要配置鉴权 token：

```bash
export JOINQUANT_WEBHOOK_TOKEN="replace-with-a-long-random-token"
export QUANT_ACTION_TOKEN="replace-with-a-long-action-token"
export QUANT_REQUIRE_ACTION_TOKEN=true
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

聚宽侧请求头带 webhook token；如果后端配置了 `QUANT_ACTION_TOKEN` 或 `QUANT_REQUIRE_ACTION_TOKEN=true`，还需要同时携带操作令牌：

```text
X-Webhook-Token: replace-with-a-long-random-token
X-Action-Token: replace-with-a-long-action-token
```

后端收到统一快照后会：

- 写入 `data/backend/strategies/custom/{strategy_id}.json`，量化策略页会读取这个文件。
- 将快照中的 `holdings[]` 汇总进持仓信息页的“量化持仓”板块。
- 追加脱敏原始请求到 `data/backend/strategies/joinquant-signals.jsonl`。

统一快照最小结构：

```json
{
  "strategy_id": "new-alpha",
  "strategy_name": "新策略 Alpha",
  "trade_date": "2026-05-16",
  "as_of": "2026-05-16T10:30:00+08:00",
  "run_id": "jq-new-alpha-20260516-103000",
  "status": "running",
  "summary": {
    "target_exposure_pct": 80,
    "current_exposure_pct": 62,
    "day_pnl_pct": 0.35
  },
  "signals": [
    {"symbol": "300476.XSHE", "name": "胜宏科技", "signal": "buy", "score": 88}
  ],
  "holdings": [
    {"symbol": "300476.XSHE", "name": "胜宏科技", "quantity": 1000, "last_price": 42, "market_value": 42000, "weight_pct": 42}
  ],
  "logs": [
    {"time": "2026-05-16 10:30:00", "stage": "snapshot", "message": "策略快照"}
  ]
}
```

## 聚宽侧上报模块

把下面这一段加到策略文件顶部参数区附近。不要把真实 token 提交到公开代码里。

```python
import json
import time

try:
    import requests
except Exception:
    requests = None

WEBHOOK_URL = "https://your-domain.example.com/api/v1/joinquant/signals"
WEBHOOK_TOKEN = "replace-with-a-long-random-token"
WEBHOOK_TIMEOUT = 5


def jq_code_parts(code):
    raw = str(code or "")
    if "." not in raw:
        return raw, ""
    symbol, suffix = raw.split(".", 1)
    market = {"XSHG": "SH", "XSHE": "SZ"}.get(suffix, suffix)
    return symbol, market


def build_position_payload(context):
    total_value = getattr(context.portfolio, "total_value", 0) or 0
    rows = []
    for security, position in context.portfolio.positions.items():
        if position.total_amount <= 0:
            continue
        symbol, market = jq_code_parts(security)
        market_value = position.total_amount * position.price
        rows.append({
            "symbol": security,
            "name": get_security_name(security),
            "market": market,
            "weight_pct": market_value / total_value * 100 if total_value else 0,
            "avg_cost": position.avg_cost,
            "last_price": position.price,
            "market_value": market_value,
            "pnl_pct": (position.price / position.avg_cost - 1) * 100 if position.avg_cost else 0,
        })
    return rows


def build_recommendation_payload(context):
    rows = []
    ranked = getattr(g, "ranked_etfs_result", []) or []
    target_set = set(getattr(g, "target_etfs_list", []) or [])
    for index, item in enumerate(ranked[:10], start=1):
        code = item.get("etf")
        if not code:
            continue
        rows.append({
            "symbol": code,
            "name": item.get("etf_name") or get_security_name(code),
            "action": "buy" if code in target_set else "watch",
            "rank": index,
            "score": item.get("momentum_score"),
            "suggested_weight_pct": 100.0 / g.holdings_num if code in target_set and g.holdings_num else 0,
            "last_price": item.get("current_price"),
            "change_pct": 0,
            "volume_ratio": item.get("volume_ratio"),
            "reason": "动量、R2、成交量、短期风控和动态滤波综合排序",
        })
    return rows


def post_strategy_signal(context, stage, extra=None):
    if requests is None:
        log.warning("【Webhook】当前聚宽环境无法导入 requests，跳过上报")
        return False
    now = context.current_dt
    target_count = len(getattr(g, "target_etfs_list", []) or [])
    current_exposure = 0
    if context.portfolio.total_value:
        current_exposure = (
            context.portfolio.total_value - context.portfolio.available_cash
        ) / context.portfolio.total_value * 100
    payload = {
        "strategy_name": "五福闹新春 v4.3",
        "strategy_id": "joinquant-wufu-etf-v43",
        "trade_date": str(now.date()),
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "run_id": "jq-wufu-%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), stage),
        "risk_state": getattr(g, "risk_state", "正常期"),
        "current_filter": getattr(g, "current_filter", "正常期"),
        "summary": {
            "buy_count": target_count,
            "watch_count": max(0, len(getattr(g, "ranked_etfs_result", []) or []) - target_count),
            "target_exposure_pct": 100 if target_count else 0,
            "current_exposure_pct": current_exposure,
            "day_pnl_pct": 0,
            "max_drawdown_pct": 0,
        },
        "recommendations": build_recommendation_payload(context),
        "holdings": build_position_payload(context),
        "events": [{
            "time": now.strftime("%H:%M"),
            "label": stage,
            "detail": extra or "",
            "status": "done",
        }],
    }
    try:
        response = requests.post(
            WEBHOOK_URL,
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Token": WEBHOOK_TOKEN,
            },
            timeout=WEBHOOK_TIMEOUT,
        )
        if response.status_code >= 300:
            log.warning("【Webhook】上报失败 HTTP %s: %s" % (response.status_code, response.text[:200]))
            return False
        log.info("【Webhook】已上报：%s" % stage)
        return True
    except Exception as e:
        log.warning("【Webhook】上报异常：%s" % e)
        return False
```

## 在原策略中调用

建议在关键节点调用，不要在 `every_bar` 里无条件调用。

```python
def morning_routine(context):
    # 原有逻辑...
    daily_merge_etf_pools(context)
    post_strategy_signal(
        context,
        "晨间池更新完成",
        "固定池%s只，动态池%s只，合并池%s只" % (
            len(getattr(g, "filtered_fixed_pool", [])),
            len(getattr(g, "dynamic_etf_pool", [])),
            len(getattr(g, "merged_etf_pool", [])),
        )
    )


def afternoon_routine(context):
    # 原有逻辑...
    calculate_and_log_ranked_etfs(context)
    post_strategy_signal(context, "午后目标生成")
    execute_sell_trades(context)
    post_strategy_signal(context, "卖出执行完成")
    execute_buy_trades(context)
    post_strategy_signal(context, "买入执行完成")
```

止损处可以只在实际卖出成功后上报：

```python
if success and g.enable_stop_loss_trigger:
    g.stop_loss_triggered_today = True
    post_strategy_signal(context, "分钟级止损触发", "%s %s" % (security, security_name))
```

## 联调

本地先用 curl 模拟聚宽：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/joinquant/signals \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: replace-with-a-long-random-token" \
  -H "X-Action-Token: replace-with-a-long-action-token" \
  -d '{"strategy_name":"五福闹新春 v4.3","recommendations":[{"symbol":"518880.XSHG","name":"黄金ETF","action":"buy","score":4.2,"suggested_weight_pct":100}],"events":[{"time":"13:10","label":"测试信号","status":"done"}]}'
```

然后打开：

```text
http://127.0.0.1:8000/etf.html
```

如果聚宽无法直接访问你的后端，优先把后端部署到有公网 HTTPS 的服务器；临时测试可以用内网穿透，但不要在公开 URL 上使用弱 token。
