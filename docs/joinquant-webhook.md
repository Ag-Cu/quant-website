# 聚宽策略 Webhook 接入

目标：聚宽策略继续在聚宽运行和下单，网站只接收策略动作事件，并在网站端计算量化持仓和收益曲线。

## 推荐链路

1. 在网页端“量化策略”页面创建策略，得到 `strategy_id`。
2. 聚宽只向网站上报动作事件：信号、订单、成交、调仓解释。
3. 网站把事件写入 `data/backend/performance/strategy-events.jsonl`。
4. 网站按事件台账、本地现金、持仓成本和交易日收盘价计算 `/api/v1/performance` 的日频收益曲线。
5. “持仓信息”里的量化持仓也从事件台账和策略快照中生成。

推荐入口：

```text
POST /api/v1/quant/strategies/{strategy_id}/events
```

兼容入口：

```text
POST /api/v1/quant/strategies/{strategy_id}/snapshot
POST /api/v1/joinquant/signals
```

兼容入口仍可更新旧策略快照，但不要再把聚宽上报的总资产或净值作为收益主链路。

## 鉴权

服务端启动时配置：

```bash
export JOINQUANT_WEBHOOK_TOKEN="replace-with-a-long-random-token"
export QUANT_ACTION_TOKEN="replace-with-a-long-action-token"
export QUANT_REQUIRE_ACTION_TOKEN=true
python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

聚宽请求头：

```text
Content-Type: application/json
X-Webhook-Token: replace-with-a-long-random-token
X-Action-Token: replace-with-a-long-action-token
```

## 事件结构

最小成交事件：

```json
{
  "strategy_name": "五福 ETF",
  "run_id": "jq-wufu-20260516-145500",
  "events": [
    {
      "event_id": "20260516-145502-159915-buy",
      "event_type": "trade",
      "trade_date": "2026-05-16",
      "time": "2026-05-16T14:55:02+08:00",
      "symbol": "159915.XSHE",
      "name": "创业板 ETF 易方达",
      "side": "buy",
      "quantity": 10000,
      "price": 1.923,
      "commission": 5,
      "tax": 0,
      "slippage": 0,
      "initial_cash": 1000000,
      "reason": "目标 ETF 动量排名第一，风险过滤通过"
    }
  ]
}
```

字段说明：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `event_id` | 建议 | 聚宽侧唯一事件 ID；相同 ID 重复上报会覆盖，避免重复成交。 |
| `event_type` | 是 | `trade` 会改变持仓；`signal`/`order` 只解释，不改变收益。 |
| `trade_date` | 是 | `YYYY-MM-DD`。 |
| `time` | 建议 | 带时区的事件时间。 |
| `symbol` | 是 | 聚宽代码，如 `300476.XSHE`、`600519.XSHG`、`159915.XSHE`。 |
| `side` | 成交必填 | `buy` 或 `sell`。兼容 `action`。 |
| `quantity` | 成交必填 | 成交数量。 |
| `price` | 成交必填 | 成交价。 |
| `commission`/`tax`/`slippage` | 可选 | 交易成本，参与现金计算。 |
| `initial_cash` | 首次建议 | 初始资金；不传时网站默认用 100 万或首批买入额较大者。 |
| `reason` | 建议 | 买入/卖出原因，用于页面解释和审计。 |

## 聚宽侧示例代码

```python
import json
import time

try:
    import requests
except Exception:
    requests = None

EVENTS_URL = "https://quant.quantlife.site/api/v1/quant/strategies/joinquant-wufu-etf-v43/events"
WEBHOOK_TOKEN = "replace-with-a-long-random-token"
ACTION_TOKEN = "replace-with-a-long-action-token"
WEBHOOK_TIMEOUT = 5
INITIAL_CASH = 1000000


def post_strategy_events(context, events):
    if requests is None:
        log.warning("【Webhook】当前聚宽环境无法导入 requests，跳过上报")
        return False
    if not events:
        return True
    now = context.current_dt
    payload = {
        "strategy_name": "五福 ETF",
        "run_id": "jq-wufu-%s" % now.strftime("%Y%m%d-%H%M%S"),
        "events": events,
    }
    try:
        response = requests.post(
            EVENTS_URL,
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Token": WEBHOOK_TOKEN,
                "X-Action-Token": ACTION_TOKEN,
            },
            timeout=WEBHOOK_TIMEOUT,
        )
        if response.status_code >= 300:
            log.warning("【Webhook】事件上报失败 HTTP %s: %s" % (response.status_code, response.text[:200]))
            return False
        log.info("【Webhook】事件已上报：%s 条" % len(events))
        return True
    except Exception as exc:
        log.warning("【Webhook】事件上报异常：%s" % exc)
        return False


def trade_event(context, security, side, quantity, price, reason, event_id=None):
    now = context.current_dt
    return {
        "event_id": event_id or "%s-%s-%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), security, side, quantity),
        "event_type": "trade",
        "trade_date": str(now.date()),
        "time": now.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "symbol": security,
        "name": get_security_name(security),
        "side": side,
        "quantity": quantity,
        "price": price,
        "commission": 0,
        "tax": 0,
        "slippage": 0,
        "initial_cash": INITIAL_CASH,
        "reason": reason,
    }
```

调用方式：只在真实下单成功或成交确认后上报 `trade`。

```python
# 买入成功后
post_strategy_events(context, [
    trade_event(context, security, "buy", amount, current_price, "目标 ETF 动量排名第一")
])

# 卖出成功后
post_strategy_events(context, [
    trade_event(context, security, "sell", amount, current_price, "止损触发或排名跌出持仓池")
])
```

如果只是策略判断，没有成交，发 `signal`：

```python
post_strategy_events(context, [{
    "event_id": "signal-%s-%s" % (context.current_dt.strftime("%Y%m%d"), security),
    "event_type": "signal",
    "trade_date": str(context.current_dt.date()),
    "time": context.current_dt.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
    "symbol": security,
    "name": get_security_name(security),
    "action": "buy",
    "score": 88,
    "target_weight_pct": 50,
    "reason": "候选买入，但尚未成交"
}])
```

## 联调

```bash
curl -X POST https://quant.quantlife.site/api/v1/quant/strategies/joinquant-wufu-etf-v43/events \
  -H "Content-Type: application/json" \
  -H "X-Webhook-Token: replace-with-a-long-random-token" \
  -H "X-Action-Token: replace-with-a-long-action-token" \
  -d '{"strategy_name":"五福 ETF","events":[{"event_id":"demo-buy-1","event_type":"trade","trade_date":"2026-05-16","time":"2026-05-16T14:55:02+08:00","symbol":"159915.XSHE","name":"创业板 ETF 易方达","side":"buy","quantity":10000,"price":1.923,"initial_cash":1000000,"reason":"联调买入"}]}'
```

验证页面：

```text
https://quant.quantlife.site/holdings.html?type=quant&strategy_id=joinquant-wufu-etf-v43
https://quant.quantlife.site/performance.html?strategy=joinquant-wufu-etf-v43&benchmark=none
```
