# 前端数据契约

前端按 FastAPI 同源接口读取数据。默认接口前缀为空，也就是同一个服务下的 `/api/v1/...`；如果要跨端口调试，可以在 HTML 加载 `app.js` 前设置：

```html
<script>
  window.QUANT_API_BASE = "http://127.0.0.1:8000";
</script>
```

## 响应包

所有接口统一返回：

```json
{
  "meta": {
    "version": "1.0",
    "source": "live",
    "as_of": "2026-05-12T14:56:00+08:00",
    "trade_date": "2026-05-12",
    "timezone": "Asia/Hong_Kong",
    "market_session": "open",
    "run_id": "intraday-20260512-1456",
    "stale_seconds": 18
  },
  "data": {}
}
```

`source` 建议取值：`live`、`cache`。  
`market_session` 建议取值：`preopen`、`open`、`lunch`、`closed`、`offline`。


## JSON Schema 单一来源

核心接口结构由 `backend/schemas.py` 的 Pydantic 模型定义，并导出到 [`docs/api-schema.json`](./api-schema.json)。本文档保留字段解释和业务语义；新增、删除或重命名字段时，必须先更新 Pydantic 模型，再运行 `python scripts/generate_api_schema.py` 重新生成 JSON Schema，避免文档和代码分叉。

当前已纳入 JSON Schema 的模型包括：`DashboardOverviewPayload`、`WatchlistPayload`、`StrategyPicksPayload`、`PortfolioHoldingsPayload`、`PerformancePayload`、`MarketHeatmapPayload`、`BreadthPayload`、`SentimentPayload`、`MacroPayload`。

## Endpoint

| 页面 | Endpoint | 刷新频率 | 后端数据文件 |
| --- | --- | --- | --- |
| 总览 | `/api/v1/dashboard/overview` | 盘中实时，约 30s | `data/backend/dashboard/overview.json`，可优先读 `data/live/overview.json` |
| 今日选股 | `/api/v1/strategies/picks` | 每日收盘后或策略任务完成后 | `data/backend/strategies/picks.json` |
| 量化策略 | `/api/v1/quant/strategies` | 策略任务刷新，约 5min | `data/config/strategies.json` + `data/backend/strategies/**/*.json` |
| 持仓信息 | `/api/v1/portfolio/holdings` | 盘中实时，约 30s | `data/backend/portfolio/holdings.json` + 策略快照 |
| 历史收益 | `/api/v1/performance` | 每日收盘后 | `data/backend/performance/strategy-events.jsonl` + `data/backend/performance/price-cache.json` |
| 自选股 | `/api/v1/watchlist` | 盘中实时，约 15s | `data/backend/watchlist/list.json` |
| 市场热力图 | `/api/v1/market/heatmap` | 盘中实时，约 30s | `data/backend/market/heatmap.json` |
| 板块表现 | `/api/v1/market/sectors` | 盘中实时，约 60s | `data/backend/market/sectors.json` |
| ETF 排名 | `/api/v1/market/etf-rankings` | 盘中实时，约 60s | `data/backend/market/etf-rankings.json` |
| ETF 策略 | `/api/v1/strategies/etf` | 策略任务刷新，约 5min | `data/backend/strategies/etf.json` |
| 小盘股策略 | `/api/v1/strategies/small-cap` | 策略任务刷新，约 5min | `data/backend/strategies/small-cap.json` |
| 市场宽度 | `/api/v1/market/breadth` | 盘中实时或分钟级 | `data/backend/market/breadth.json`，可优先读 `data/live/breadth.json` |
| 散户情绪 | `/api/v1/market/sentiment` | 盘中实时或分钟级 | `data/backend/market/sentiment.json`，可优先读 `data/live/sentiment.json` |
| 宏观指标 | `/api/v1/macro` | 小时级或日频 | `data/backend/macro.json`，可优先读 `data/live/macro.json` |

统一量化策略接口：

```text
GET  /api/v1/quant/strategies
POST /api/v1/quant/strategies
GET  /api/v1/quant/strategies/{strategy_id}
POST /api/v1/quant/strategies/{strategy_id}/events
GET  /api/v1/quant/strategies/{strategy_id}/events
POST /api/v1/quant/strategies/{strategy_id}/snapshot
GET  /api/v1/quant/strategies/{strategy_id}/logs
```

`POST /api/v1/quant/strategies` 用于网页端新增策略，写入 `data/config/strategies.json`，并在 `data/backend/strategies/custom/{strategy_id}.json` 创建等待上报的空快照。写接口需要 `X-Action-Token`。

`POST /api/v1/quant/strategies/{strategy_id}/events` 是 JoinQuant 推荐接入入口。聚宽只上报信号、成交、订单等动作事件；网站用本地事件台账、现金、持仓数量和交易日收盘价计算量化持仓与收益曲线。它要求策略先在网页端创建，鉴权同时支持 `X-Webhook-Token` 和 `X-Action-Token`。

`POST /api/v1/quant/strategies/{strategy_id}/snapshot` 是兼容入口，保留给旧策略上报摘要、信号、持仓快照。不要再把它作为收益计算的主链路。

前端按每个页面配置的频率刷新当前接口。接口不可用、返回非 2xx 或 JSON 解析失败时，前端只显示“获取失败”，不会 fallback 到 mock。

## 当前真实行情源

`scripts/update_live_data.py` 当前使用多类真实行情源写入 `data/live`：

- 新浪实时行情：A 股和 ETF quote，覆盖 `/api/v1/watchlist`、`/api/v1/market/heatmap`、`/api/v1/market/etf-rankings` 的相关字段。
- Yahoo Finance chart：美股 quote、USD/CNH、美国 10Y、恒生科技等跨市场指标。
- 财政部-中国国债收益率曲线/中债估值(CCDC)：覆盖 `/api/v1/macro` 的中国 1Y/10Y 国债收益率与日度 BP 变化。
- 东方财富行情中心：覆盖 `/api/v1/macro` 的沪深300/中证1000/创业板指点位、涨跌幅以及沪深300 PE(TTM)，用于 `risk_preference_score` 和 `equity_bond_spread_pct`。
- 东方财富行业板块：优先覆盖 `/api/v1/market/sectors` 和 `/api/v1/market/breadth`。如果东方财富公开接口断连，会用已经获取到的真实 quote 按监控分组生成代理宽度，仍然不读取 mock。

当前环境有 `tushare` 包，但没有 `TUSHARE_TOKEN`。后续配置 token 后，可以把 A 股日线、指数、行业和财务字段切换到 Tushare；接口响应结构无需改变。

### Tushare 量化选股任务

`scripts/generate_khan_picks.py` 用 Tushare 日线、沪深300指数和申万一级行业成分复刻 `git@github.com:JustinWu00/khan-quant-data.git` 中 `src/backtest/stategy/macd.py::before_market_open` 的入池逻辑，并写入“今日选股”接口。

运行环境必须通过 `TUSHARE_TOKEN` 注入 token，不要把 token 写入仓库：

```bash
TUSHARE_TOKEN=... python scripts/generate_khan_picks.py --user owner
```

输出策略 id 为 `khan-macd-volume`，展示名为 `Khan MA 量价选股`。公网部署建议用 systemd timer 在 A 股收盘后每日运行一次，写入 `data/backend/users/{username}/strategies/picks.json`，从而让用户登录后只看到自己名下的选股结果。

### `/api/v1/macro` 可复现派生指标

- `equity_bond_spread_pct = 100 / 沪深300 PE(TTM) - 中国 10Y 国债收益率`。其中 PE(TTM) 来自东方财富行情中心，中国 10Y 来自财政部-中国国债收益率曲线/中债估值(CCDC)。
- `risk_preference_score = clip(50 + 6*沪深300日涨跌幅 + 4*中证1000日涨跌幅 + 5*(股债利差-3.0) - 0.15*中国10Y日变化BP - 3*USD/CNH日涨跌幅, 0, 100)`。
- `rates[]`、`fx[]`、`risk_assets[]` 每行必须输出 `data_source` 与 `as_of`。当远端数据源不可用时，生成器才允许沿用上一期值，并在 `observations[]` 中追加 `level=warning` 的降级说明；正常情况下不得输出“暂沿用上一值”占位观察项。

## 后端最小实现

FastAPI 已在 `backend/main.py` 中实现上面的路径。字段可以先完整照着 `data/backend/**/*.json` 输出；后续新增字段不会影响前端，删除字段则需要同步前端渲染逻辑。

## 跨域与写接口鉴权

- CORS 来源必须通过环境变量 `QUANT_ALLOWED_ORIGINS` 显式配置白名单，多个来源用英文逗号分隔，例如 `https://quant.example.com,https://ops.example.com`；未配置时不向任意跨域来源开放。
- 公网部署应开启登录系统：`QUANT_AUTH_ENABLED=true`、`QUANT_AUTH_SECRET=<随机长密钥>`、`QUANT_AUTH_USERNAME=<用户名>`、`QUANT_AUTH_PASSWORD_HASH=<pbkdf2_sha256 哈希>`。登录成功后服务端只下发 `HttpOnly`、`SameSite=Lax` 的会话 cookie，前端不能读取密码或会话内容。
- 登录保护覆盖页面、`/api/v1/...` 读接口和 `/data/...` 原始 JSON 文件；`/login.html`、`/login.js`、`/styles.css` 公开。JoinQuant 与资金费率 webhook 路径不依赖网页登录态，但仍必须通过各自的机器 token。
- 用户私有数据优先从 `data/backend/users/{username}/...` 读取和写入，包括 `portfolio/`、`performance/`、`strategies/`、`watchlist/`、`actions/`、`exports/`，以及 `config/watchlist.json`、`config/strategies.json`。因此不同用户登录后看到的是各自目录下的数据。
- 所有会写入配置、动作日志、导出文件或策略数据的写接口都需要操作令牌。客户端可以任选以下一种方式传递同一个 `QUANT_ACTION_TOKEN`：
  - `X-Action-Token: <token>`
  - `Authorization: Bearer <token>`
- 生产或公网部署如需开启写操作，建议同时设置 `QUANT_ACTION_TOKEN` 和 `QUANT_REQUIRE_ACTION_TOKEN=true`。这样即使遗漏 `QUANT_ACTION_TOKEN`，服务端也会拒绝写请求，而不是无鉴权放行。
- 当前前端会从 `localStorage.quant_action_token` 或 `window.QUANT_ACTION_TOKEN` 读取令牌，并在自选股新增/删除、个人持仓保存、持仓标记、信号确认、导出和调仓记录等写请求中发送。

## 总览聚合字段

`/api/v1/dashboard/overview` 是前端首页的主接口。它应该由后端 API 聚合层组装，不建议让前端分别请求热力图、ETF 排名、板块表现和策略状态。

推荐字段：

- `decision`: 首页顶部结论，字段为 `tone`、`title`、`detail`、`action`。
- `market`: 核心市场状态，字段为 `breadth_score`、`sentiment_score`、`risk_preference_score`、`ten_year_yield_pct`、`usd_cnh`。
- `account`: 组合概览，字段为 `net_exposure_pct`、`cash_pct`、`position_count`、`day_pnl_pct`、`total_pnl_pct`。
- `sentiment_gauge`: 散户情绪仪表，字段为 `score`、`label`、`previous_day_score`、`previous_week_score`、`trend_30d[]`。
- `heatmap`: 市场热力图，字段为 `timeframe`、`group_by`、`updated_at`、`cells[]`。
- `top_etfs[]`: ETF 排名。
- `sectors[]`: 板块表现。
- `strategy_status[]`: 策略状态摘要。
- `alerts[]`: 风险提醒。

`heatmap.cells[]` 字段：

```json
{
  "symbol": "NVDA",
  "name": "NVIDIA",
  "sector": "科技",
  "price": 1084.6,
  "change_pct": 2.8,
  "volume": 53820000,
  "market_cap": 2670000000000,
  "weight": 24
}
```

`weight` 用于 treemap 面积，`change_pct` 用于颜色，`sector` 用于分组。

`top_etfs[]` 字段：

```json
{
  "rank": 1,
  "symbol": "512100",
  "name": "中证1000ETF",
  "return_pct": 1.18,
  "aum": 12400000000,
  "volume": 82000000,
  "turnover": 194800000,
  "sparkline": [2.21, 2.25, 2.24, 2.28, 2.31, 2.34, 2.376]
}
```

`sectors[]` 字段：

```json
{
  "id": "tech",
  "name": "科技",
  "icon": "⌁",
  "performance_pct": 2.4,
  "up_count": 23,
  "down_count": 7,
  "flat_count": 2,
  "market_cap": 12000000000000,
  "turnover": 92000000000,
  "rank": 1
}
```

旧 `/api/v1/overview` 可继续保留为兼容接口，但新前端首页默认请求 `/api/v1/dashboard/overview`。

## 量化选股字段

`/api/v1/strategies/picks` 用于“量化选股”页面。建议支持查询参数：

```text
GET /api/v1/strategies/picks?strategy=khan-macd-volume&date=2026-05-15
```

推荐字段：

- `strategy`: 策略 id。
- `strategy_label`: 策略展示名。
- `trade_date`: 交易日。
- `status`: `preopen`、`ready`、`running`、`closed`。
- `strategies[]`: 可切换策略名。
- `source.method_summary`: 策略核心选股方法，用于前端策略说明。
- `items[]`: 选股结果。

`items[]` 字段：

```json
{
  "symbol": "300476",
  "name": "胜宏科技",
  "score": 87,
  "confidence": 0.82,
  "is_new": true,
  "in_portfolio": false,
  "factors": [
    { "name": "动量信号", "value": 82, "weight": 0.4 },
    { "name": "成交量异常", "value": 61, "weight": 0.25 }
  ],
  "entry_price": 42.8,
  "stop_loss": 40.3,
  "take_profit": 48.6,
  "tags": ["突破型", "放量", "AI PCB"],
  "explanation": "价格突破短期平台，成交量放大。",
  "invalidation": "跌回突破平台且成交量无法维持。"
}
```

这个接口是后端策略框架的核心输出之一。前端不应自行计算选股结果，只展示策略服务返回的结果。

## 当前持仓字段

`/api/v1/portfolio/holdings` 用于“持仓信息”页面。页面会拆成两个板块：

- `quant_holdings[]`: 量化持仓，来自 JoinQuant/统一策略快照。若策略给出 `buy/add/hold` 信号但尚未上报成交持仓，会以 `portfolio_state=target` 进入列表，标记为目标持仓/待成交。
- `personal_holdings[]`: 个人持仓，来自 `data/backend/portfolio/holdings.json` 中 `portfolio_type=personal` 或未标注类型的手动/导入持仓。服务端会清理个人持仓中的 `strategy_id`，避免和量化策略混淆。

支持查询：

```text
GET /api/v1/portfolio/holdings?type=quant
GET /api/v1/portfolio/holdings?type=personal
GET /api/v1/portfolio/holdings?type=quant&strategy_id=joinquant-wufu-etf-v43
POST /api/v1/portfolio/personal-holdings
```

也可以在 `POST /api/v1/watchlist` 时传入 `is_personal_holding=true` 和 `personal_amount`，同时加入自选股和个人持仓。

推荐字段：

- `summary.total_market_value`: 账户总市值。
- `summary.day_pnl_amount`: 当日盈亏金额。
- `summary.day_pnl_pct`: 当日盈亏百分比。
- `summary.total_return_pct`: 累计收益率。
- `summary.exposure_pct`: 仓位使用率。
- `summary.position_count`: 持仓数量。
- `summary.sector_diversity`: 行业分散度。
- `holdings[]`: 当前查询视角下的持仓明细。
- `quant_holdings[]`: 全部量化持仓。
- `personal_holdings[]`: 全部个人持仓。
- `allocation[]`: 行业配置。

`holdings[]` 字段：

```json
{
  "symbol": "002463",
  "name": "沪电股份",
  "strategy_id": "small-cap-momentum",
  "portfolio_type": "quant",
  "portfolio_state": "actual",
  "sector": "AI PCB",
  "avg_cost": 36.42,
  "last_price": 39.18,
  "quantity": 18000,
  "market_value": 705240,
  "pnl_amount": 49680,
  "pnl_pct": 7.58,
  "weight_pct": 18,
  "holding_days": 12,
  "entry_date": "2026-04-24",
  "notes": "趋势保持强势"
}
```

个人持仓示例：

```json
{
  "symbol": "600519",
  "name": "贵州茅台",
  "portfolio_type": "personal",
  "portfolio_state": "actual",
  "sector": "消费",
  "market_value": 12345,
  "quantity": 10,
  "notes": "从自选股标记为真实持仓"
}
```

`allocation[]` 字段：

```json
{
  "sector": "AI PCB",
  "weight_pct": 34,
  "market_value": 822120
}
```

## 历史收益字段

`/api/v1/performance` 用于“历史收益”页面。建议支持查询参数：

```text
GET /api/v1/performance?strategy=joinquant-wufu-etf-v43&from=2025-01-01&to=2026-05-12&benchmark=CSI300
```

收益曲线来源分四类：

- JoinQuant 上报的策略事件台账：推荐主链路。聚宽只上报买入、卖出、信号等动作，网站本地按现金、成本、持仓数量和交易日收盘价计算每日净值。
- JoinQuant 旧账户快照：兼容链路。只用于旧策略尚未改造时的低频展示。

收益页默认只展示已运行或有真实台账/快照的量化策略；静态回测种子、未运行的小盘股策略和个人持仓不再作为收益曲线入口展示。

推荐的聚宽上报格式：

```text
POST /api/v1/quant/strategies/{strategy_id}/events
```

示例：

```json
{
  "strategy_name": "新策略 Alpha",
  "run_id": "jq-alpha-20260516-150000",
  "events": [
    {
      "event_id": "order-20260516-0001",
      "event_type": "trade",
      "trade_date": "2026-05-16",
      "time": "2026-05-16T14:55:02+08:00",
      "symbol": "300476.XSHE",
      "name": "胜宏科技",
      "side": "buy",
      "quantity": 1000,
      "price": 42.15,
      "commission": 5,
      "initial_cash": 1000000,
      "reason": "动量突破且风险过滤通过"
    }
  ]
}
```

收益计算规则：

- 成交事件 `event_type=trade` 且 `side=buy/sell` 才会改变本地持仓和现金。
- `signal`、`order` 等事件只用于解释，不直接改变收益。
- 买入：现金减少 `quantity * price + commission + tax + slippage`，持仓数量增加，平均成本按加权成本更新。
- 卖出：现金增加 `quantity * price - commission - tax - slippage`，持仓数量减少。
- 每个交易日收盘后，网站用本地价格缓存/公开日线行情给持仓估值：`total_value = cash + sum(quantity * close)`，`net_value = total_value / initial_cash`。
- 旧快照入口仍可识别 `nav`、`net_values`、`equity_curve`、`performance_curve`、`daily_nav`、`daily_net_values`，但这不再是推荐收益链路。

推荐字段：

- `strategy`: 策略 id。
- `strategy_label`: 策略展示名。
- `benchmark`: 基准展示名。
- `equity_curve[]`: 策略收益曲线。
- `benchmark_curve[]`: 基准收益曲线。
- `drawdowns[]`: 回撤区间。
- `metrics`: 绩效指标。
- `monthly_returns[]`: 月度收益热力图。
- `annotations[]`: 图表备注。
- `nav_source.source`: `local-ledger`、`joinquant`、`static` 或 `manual`。
- `data_quality.frequency`: `daily`、`daily-proxy`、`monthly`、`snapshot` 等。
- `data_quality.synthetic`: 是否为低频锚点插值得到的代理曲线。

`equity_curve[]` / `benchmark_curve[]` 字段：

```json
{
  "date": "2026-01-01",
  "value": 101.2,
  "return_pct": 1.2
}
```

`metrics` 字段：

```json
{
  "annual_return_pct": 31.8,
  "max_drawdown_pct": -8.6,
  "sharpe": 1.84,
  "calmar": 3.7,
  "win_rate_pct": 58.4,
  "profit_loss_ratio": 1.62,
  "avg_holding_days": 11.8,
  "beta": 0.82,
  "alpha_pct": 12.4
}
```

`monthly_returns[]` 字段：

```json
{
  "year": 2026,
  "month": 5,
  "return_pct": 3.2
}
```

## 自选股字段

`/api/v1/watchlist` 用于“自选股”页面。后续增删改可扩展：

```text
POST /api/v1/watchlist
DELETE /api/v1/watchlist/{symbol}
GET /api/v1/watchlist/{symbol}
```

其中 `POST` 和 `DELETE` 属于写接口，必须携带 `X-Action-Token` 或 `Authorization: Bearer ...`。

`POST /api/v1/watchlist` 可选写入个人持仓字段：

```json
{
  "symbol": "600519",
  "market_region": "cn",
  "name": "贵州茅台",
  "sector": "消费",
  "is_personal_holding": true,
  "personal_amount": 12345,
  "quantity": 10
}
```

列表字段：

```json
{
  "groups": [
    {
      "name": "科技股",
      "items": [
        {
          "symbol": "NVDA",
          "name": "NVIDIA Corp",
          "logo": "N",
          "price": 1084.6,
          "change_pct": 2.34,
          "intraday_high": 1096.2,
          "intraday_low": 1058.4,
          "intraday_current": 1084.6,
          "volume": 53820000,
          "volume_ratio": 92,
          "market_cap": "2.67T",
          "week52_low": 410.1,
          "week52_high": 1120.4,
          "week52_current": 1084.6
        }
      ]
    }
  ]
}
```

## 市场热力图字段

`/api/v1/market/heatmap?timeframe=1D&group_by=sector` 返回独立热力图数据。字段和 `/api/v1/dashboard/overview` 的 `heatmap` 一致：

- `timeframe`
- `group_by`
- `updated_at`
- `cells[]`

## 板块表现字段

`/api/v1/market/sectors?period=1D` 返回独立板块数据。字段和 `/api/v1/dashboard/overview` 的 `sectors[]` 一致。

## ETF 排名字段

`/api/v1/market/etf-rankings?period=1D` 返回独立 ETF 排名数据。字段：

- `period`
- `items[]`

`items[]` 字段和 `/api/v1/dashboard/overview` 的 `top_etfs[]` 一致。

## 市场宽度字段

`/api/v1/market/breadth` 已按 `/home/yt/quant/market_width.zip` 的逻辑设计字段：

- `source_algorithm`: 算法来源与口径说明，前端会展示来源文件、股票池、行业标准、MA 窗口和公式。
- `summary.market_width_pct`: 全市场 `close > MA20` 的股票比例。
- `summary.industry_sum_score`: 行业宽度合计/归一化值。
- `metrics[]`: 核心宽度指标。
- `industry_width[]`: 行业宽度明细，建议字段为 `industry_code`、`name`、`width_pct`、`prev_width_pct`、`delta_pct`、`above_ma20_count`、`total_count`。
- `heatmap_history`: 近 10 日行业热力矩阵，结构为 `{ "columns": string[], "rows": [{ "date": "05-12", "values": number[] }] }`，`values` 顺序必须与 `columns` 一致。

对应原始逻辑：

```text
df_ma20 = close.rolling(20).mean()
df_bias = close > df_ma20
全市场宽度 = df_bias.sum() / df_bias.count() * 100
行业宽度 = df_bias.groupby(industry).sum() / df_bias.groupby(industry).count() * 100
```

## 散户情绪字段

`/api/v1/market/sentiment` 已接入 `/home/yt/quant/yy1min.txt` 的 1 分钟成交量激增与耀眼波动率口径：

- `source_algorithm`: 算法来源与口径说明。
- `summary.daily_brilliant_vol`: 当日耀眼波动率。
- `summary.surge_count`: 成交量激增次数。
- `brilliant_volatility`: 当前跟踪标的的核心结果。
- `latest_snapshot`: 顶部“最新情绪数据”卡片，字段为 `updated_at`、`update_frequency`、`symbol`、`name`、`sentiment_value`、`status`、`last_count`、`warning_line`。
- `sentiment_trend[]`: 情绪趋势图序列，字段为 `date`、`value`。
- `brilliant_series[]`: 多日 `close`、`daily_brilliant_vol`、`surge_count`。
- `surge_events[]`: 盘中关键激增事件，建议字段为 `time`、`volume_increase_ratio`、`return_std`、`price_change_pct`。

对应原始逻辑：

```text
volume_increase = volume.diff()
is_surge = volume_increase > mean(volume_increase) + std(volume_increase)
排除 13:01
is_brilliant = is_surge 以及后续 4 分钟
return_rate = close.pct_change() * 100
daily_brilliant_vol = mean(std(return_rate in surge 5-minute windows))
```
