# Quant Dashboard Backend

这个后端是当前网站的数据边界：前端只请求 `/api/v1/...`，不再读取本地 mock 或静态 JSON fallback。

## 环境准备

在仓库根目录创建虚拟环境并安装 Python 依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

如果需要运行前端静态资源检查，可以安装 Node 依赖：

```bash
npm install
```

## 本地启动

标准本地启动命令：

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

同一个服务会同时提供：

- 静态页面：`/index.html`、`/watchlist.html` 等
- 数据接口：`/api/v1/...`
- 聚宽信号 Webhook：`POST /api/v1/joinquant/signals`
- 健康检查：`/api/v1/health`

写接口默认在未配置操作 token 时允许本地开发调用；如果配置了 `QUANT_ACTION_TOKEN`，调用自选股增删、持仓标记、策略确认、导出和调仓记录等写接口时必须带 `X-Action-Token` 或 `Authorization: Bearer ...`：

```bash
export QUANT_ACTION_TOKEN="replace-with-a-long-random-token"
```

## 数据文件

后端当前从 `data/backend/**/*.json` 读取业务数据。实时类接口可以优先读取 `data/live/*.json`，用于接入盘中行情更新任务。

如果接口对应的数据文件不存在，后端返回 `503`，前端显示“获取失败”，不会 fallback 到 mock。

## 刷新数据

标准刷新命令：

```bash
python scripts/update_live_data.py
```

脚本会从公开数据源拉取最新行情并原子写入 `data/live/*.json`。可以先查看脚本参数：

```bash
python scripts/update_live_data.py --help
```

## 运行检查

后端 API smoke tests 和数据契约测试：

```bash
python -m pytest
```

前端静态检查命令：

```bash
npm run lint:js
npm run format
npm run check:html
```

## 真实行情源

`scripts/update_live_data.py` 已接入当前可直接使用的真实行情源：

- 新浪实时行情：A 股和 ETF quote，写入自选股、ETF 排名、热力图。
- Yahoo Finance chart：美股、USD/CNH、美国 10Y 等跨市场 quote。
- 东方财富行业板块：优先用于行业宽度和板块表现；若公开接口断连，脚本会使用已经拉到的真实 quote 按监控分组生成代理宽度，不使用 mock。

当前脚本的数据源访问使用 Python 标准库 `urllib`，不需要额外行情 SDK。若后续配置 Tushare、AkShare 或自有行情库，请同步更新仓库根目录的 `requirements.txt`。

## 刷新频率

接口在 `backend/main.py` 的 `ENDPOINTS` 中登记刷新策略：

- `realtime`: 盘中实时或分钟级，比如首页、热力图、自选股、宽度、情绪。
- `portfolio`: 持仓盈亏盘中刷新，交易和账户同步任务写入。
- `strategy`: 策略运行态，通常 5 分钟或策略任务完成后刷新。
- `daily`: 收盘后更新，比如每日选股、历史绩效、宏观日频数据。

真实数据接入时，任务只需要把同结构 JSON 原子写入 `data/backend` 或 `data/live`，接口契约保持不变。

## 聚宽策略信号接入

启动后端前配置一个只给聚宽使用的 token：

```bash
export JOINQUANT_WEBHOOK_TOKEN="replace-with-a-long-random-token"
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

聚宽策略向 `POST /api/v1/joinquant/signals` 发送 JSON，鉴权可放在请求头
`X-Webhook-Token`，也可以放在 body 的 `token` 字段。后端会把信号转换为
ETF 策略页的数据结构并写入 `data/backend/strategies/etf.json`，同时把脱敏后的
原始请求追加到 `data/backend/strategies/joinquant-signals.jsonl` 便于排查。

如果 payload 带 `logs` / `log_lines` / `full_logs` 字段，后端会把完整日志追加到
`data/backend/strategies/joinquant-full-logs.jsonl`，并在 ETF 策略页展示最近日志。
也可以直接查询：

```text
GET /api/v1/strategies/etf/logs?limit=200
GET /api/v1/strategies/etf/logs?trade_date=2026-05-14
GET /api/v1/strategies/etf/logs?run_id=xxx
```

最小 payload：

```json
{
  "strategy_name": "五福闹新春 v4.3",
  "risk_state": "正常期",
  "current_filter": "正常期",
  "summary": {
    "target_exposure_pct": 100,
    "current_exposure_pct": 0,
    "day_pnl_pct": 0
  },
  "recommendations": [
    {
      "symbol": "518880.XSHG",
      "name": "黄金ETF",
      "action": "buy",
      "score": 4.2,
      "suggested_weight_pct": 100,
      "last_price": 5.12,
      "reason": "动量、R2、成交量和动态滤波均通过"
    }
  ],
  "holdings": [],
  "events": [
    { "time": "13:10", "label": "聚宽午后交易流水线完成", "status": "done" }
  ],
  "logs": [
    { "time": "2026-05-14 13:10:00", "level": "info", "stage": "rank", "message": "排名完成：159915.XSHE score=4.8" }
  ]
}
```

聚宽侧建议只在关键节点上报：晨间池更新完成、午后目标生成后、卖出/买入后、分钟级止损触发后。不要在 `every_bar` 无条件上报，避免请求过密。
