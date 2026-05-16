# 聚宽动作事件 API 规划

本文档用于梳理当前网站 API，并定义聚宽后续应该接入的统一动作事件 API。

## 现有 API 梳理

只读页面 API：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 服务健康检查和已注册数据接口列表。 |
| `GET` | `/api/v1/dashboard/overview` | 首页聚合数据。 |
| `GET` | `/api/v1/overview` | 首页旧兼容接口。 |
| `GET` | `/api/v1/watchlist` | 自选股行情列表。 |
| `GET` | `/api/v1/watchlist/config` | 自选股配置。 |
| `GET` | `/api/v1/strategies/picks` | 今日选股结果。 |
| `GET` | `/api/v1/strategies/picks/export` | 今日选股 CSV 导出。 |
| `GET` | `/api/v1/portfolio/holdings` | 持仓信息，支持 `type=quant/personal` 与 `strategy_id` 筛选。 |
| `GET` | `/api/v1/performance` | 收益曲线，支持 `strategy`、`benchmark`、`from`、`to`。 |
| `GET` | `/api/v1/market/heatmap` | 市场热力图。 |
| `GET` | `/api/v1/market/sectors` | 板块表现。 |
| `GET` | `/api/v1/market/etf-rankings` | ETF 排名。 |
| `GET` | `/api/v1/market/breadth` | 市场宽度。 |
| `GET` | `/api/v1/market/sentiment` | 散户情绪。 |
| `GET` | `/api/v1/macro` | 宏观指标。 |
| `GET` | `/api/v1/strategies/etf` | ETF 策略旧详情页数据。 |
| `GET` | `/api/v1/strategies/etf/logs` | ETF 策略日志。 |
| `GET` | `/api/v1/strategies/small-cap` | 小盘股策略旧详情页数据。 |
| `GET` | `/api/v1/quant/strategies` | 统一量化策略列表。 |
| `GET` | `/api/v1/quant/strategies/{strategy_id}` | 单个量化策略详情。 |
| `GET` | `/api/v1/quant/strategies/{strategy_id}/logs` | 单个量化策略日志。 |
| `GET` | `/api/v1/quant/strategies/{strategy_id}/events` | 单个量化策略事件台账，需操作令牌。 |

写接口：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/watchlist` | 新增自选股，也可标记为个人持仓。 |
| `DELETE` | `/api/v1/watchlist/{symbol}` | 删除自选股。 |
| `POST` | `/api/v1/portfolio/holdings/{symbol}/mark` | 标记持仓状态。 |
| `POST` | `/api/v1/portfolio/personal-holdings` | 手工新增或更新个人持仓。 |
| `POST` | `/api/v1/strategies/{strategy_id}/signals/{symbol}/confirm` | 确认策略信号。 |
| `POST` | `/api/v1/strategies/picks/export` | 保存选股导出动作。 |
| `POST` | `/api/v1/portfolio/rebalance-records` | 记录调仓动作。 |
| `POST` | `/api/v1/quant/strategies` | 网页端新增量化策略。 |
| `POST` | `/api/v1/quant/strategies/{strategy_id}/events` | 推荐的聚宽事件上报入口。 |
| `POST` | `/api/v1/quant/strategies/{strategy_id}/snapshot` | 旧快照兼容入口。 |
| `POST` | `/api/v1/joinquant/signals` | ETF/小盘股旧 webhook 兼容入口。 |

## 重新设计策略

核心原则：聚宽不再负责收益曲线计算，只负责告诉网站“发生了什么”。

新的主链路：

1. 网页端创建策略，生成稳定的 `strategy_id`。
2. 聚宽策略在真实下单成功或成交确认后，上报 `trade` 事件。
3. 聚宽可以额外上报 `signal` 或 `order` 事件解释买卖原因，但这些事件不改变持仓。
4. 网站把事件写入 `data/backend/performance/strategy-events.jsonl`，按 `strategy_id + event_id` 幂等覆盖。
5. 网站用本地现金、成交价格、费用、持仓数量和交易日收盘价计算每日净值。
6. `/api/v1/performance` 优先使用 `local-ledger` 曲线；如果没有事件台账，才回退到旧快照或静态种子曲线。
7. `/api/v1/portfolio/holdings` 的量化持仓优先从事件台账重建，同时继续兼容旧策略快照里的持仓字段。

收益计算口径：

- 买入：`cash -= quantity * price + commission + tax + slippage`。
- 卖出：`cash += quantity * price - commission - tax - slippage`。
- 持仓成本：买入时按加权成本更新，卖出时按平均成本减少成本额。
- 每日估值：`total_value = cash + sum(quantity * close)`。
- 策略净值：`net_value = total_value / initial_cash`。
- `signal`、`order`、日志和解释字段只用于审计和页面说明，不参与收益计算。

## 聚宽应该接入的 API

### 1. 创建策略

网页端创建即可；如需脚本创建：

```http
POST /api/v1/quant/strategies
X-Action-Token: <action-token>
Content-Type: application/json
```

```json
{
  "id": "new-alpha",
  "name": "新策略 Alpha",
  "category": "stock",
  "status": "running",
  "provider": "joinquant",
  "description": "聚宽事件台账策略"
}
```

### 2. 上报策略事件

```http
POST /api/v1/quant/strategies/{strategy_id}/events
X-Webhook-Token: <joinquant-webhook-token>
X-Action-Token: <action-token>
Content-Type: application/json
```

```json
{
  "strategy_name": "新策略 Alpha",
  "run_id": "jq-alpha-20260516-145500",
  "events": [
    {
      "event_id": "20260516-145502-300476-buy",
      "event_type": "trade",
      "trade_date": "2026-05-16",
      "time": "2026-05-16T14:55:02+08:00",
      "symbol": "300476.XSHE",
      "name": "胜宏科技",
      "side": "buy",
      "quantity": 1000,
      "price": 42.15,
      "commission": 5,
      "tax": 0,
      "slippage": 0,
      "initial_cash": 1000000,
      "reason": "动量突破且风险过滤通过"
    }
  ]
}
```

响应重点字段：

```json
{
  "data": {
    "strategy_id": "new-alpha",
    "event_count": 1,
    "trade_count": 1,
    "events_storage_path": "data/backend/performance/strategy-events.jsonl",
    "performance_url": "/performance.html?strategy=new-alpha",
    "holdings_url": "/holdings.html?type=quant&strategy_id=new-alpha"
  }
}
```

### 3. 查看事件台账

```http
GET /api/v1/quant/strategies/{strategy_id}/events?limit=200
X-Action-Token: <action-token>
```

### 4. 查看收益曲线

```http
GET /api/v1/performance?strategy={strategy_id}&benchmark=none&from=2026-01-01&to=2026-05-16
```

当事件台账生效时：

- `meta.source = local-ledger`
- `data.nav_source.source = local-ledger`
- `data.data_quality.frequency = daily`

### 5. 查看量化持仓

```http
GET /api/v1/portfolio/holdings?type=quant&strategy_id={strategy_id}
```

## 事件字段约定

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `event_id` | 建议 | 聚宽侧唯一事件 ID；重复上报同一 ID 不会重复入账。 |
| `event_type` | 是 | 推荐 `trade`、`signal`、`order`。只有 `trade` 改变持仓。 |
| `trade_date` | 是 | `YYYY-MM-DD`。 |
| `time` | 建议 | ISO 时间，建议带 `+08:00`。 |
| `symbol` | 是 | 聚宽代码，如 `300476.XSHE`、`600519.XSHG`、`159915.XSHE`。 |
| `side` | 成交必填 | `buy` 或 `sell`。也兼容 `action`。 |
| `quantity` | 成交必填 | 成交数量。 |
| `price` | 成交必填 | 成交价格。 |
| `commission` | 可选 | 手续费。 |
| `tax` | 可选 | 税费。 |
| `slippage` | 可选 | 滑点成本。 |
| `initial_cash` | 首次建议 | 策略初始资金，用于净值基准。 |
| `reason` | 建议 | 买入/卖出原因。 |

## 旧接口定位

`POST /api/v1/quant/strategies/{strategy_id}/snapshot` 和 `POST /api/v1/joinquant/signals` 继续兼容旧数据结构，包括 `summary`、`signals`、`holdings`、`logs` 和历史净值字段。但它们不再是推荐收益链路；新策略应接入 `events`。
