const API_BASE = window.QUANT_API_BASE || "";

const PAGE_CONFIG = {
  overview: { endpoint: "/api/v1/dashboard/overview", refreshMs: 30_000, render: renderOverview },
  watchlist: { endpoint: "/api/v1/watchlist", refreshMs: 15_000, render: renderWatchlist },
  picks: { endpoint: "/api/v1/strategies/picks", refreshMs: 300_000, render: renderPicks },
  holdings: { endpoint: "/api/v1/portfolio/holdings", refreshMs: 30_000, render: renderHoldings },
  performance: { endpoint: "/api/v1/performance", refreshMs: 300_000, render: renderPerformance },
  etf: { endpoint: "/api/v1/strategies/etf", refreshMs: 300_000, render: renderEtf },
  "small-cap": { endpoint: "/api/v1/strategies/small-cap", refreshMs: 300_000, render: renderSmallCap },
  breadth: { endpoint: "/api/v1/market/breadth", refreshMs: 60_000, render: renderBreadth },
  sentiment: { endpoint: "/api/v1/market/sentiment", refreshMs: 60_000, render: renderSentiment },
  macro: { endpoint: "/api/v1/macro", refreshMs: 3_600_000, render: renderMacro },
};

const PAGE_META = {
  overview: ["Market Overview", "市场总览"],
  watchlist: ["Watchlist", "自选股"],
  picks: ["Daily Picks", "今日选股"],
  holdings: ["Portfolio", "当前持仓"],
  performance: ["Performance", "历史收益"],
  etf: ["ETF Strategy", "ETF 策略"],
  "small-cap": ["Small Cap Strategy", "小盘股策略"],
  breadth: ["Market Breadth", "市场宽度"],
  sentiment: ["Retail Sentiment", "散户情绪"],
  macro: ["Macro Reference", "宏观指标"],
};

const dom = {
  app: document.querySelector("#app"),
  apiMode: document.querySelector("#apiMode"),
  runSummary: document.querySelector("#runSummary"),
  connectionBadge: document.querySelector("#connectionBadge"),
  refreshButton: document.querySelector("#refreshButton"),
  marketDate: document.querySelector("#marketDate"),
  marketClock: document.querySelector("#marketClock"),
  lastUpdated: document.querySelector("#lastUpdated"),
};

const integerFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;" })[char]);
}

function joinUrl(base, path) {
  if (!base) return path;
  return `${base.replace(/\/$/, "")}${path}`;
}

function withCacheBust(url) {
  return `${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`;
}

async function requestJson(url) {
  const response = await fetch(withCacheBust(url), { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function sendJson(path, options = {}) {
  const response = await fetch(joinUrl(API_BASE, path), {
    cache: "no-store",
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      // Keep the original HTTP status when the backend response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

async function fetchPayload(config) {
  if (!config.endpoint) throw new Error("页面未配置数据接口");
  const payload = await requestJson(joinUrl(API_BASE, config.endpoint));
  const mode = payload.meta?.source === "cache" ? "cache" : "live";
  return { payload, mode };
}

function valueText(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(Number(value));
}

function fixedText(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

function intText(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return integerFormat.format(Number(value));
}

function pctText(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}%`;
}

function valueWithUnit(value, unit = "", digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const decimals = Math.abs(Number(value)) >= 100 ? 0 : digits;
  return `${valueText(value, decimals)}${escapeHtml(unit)}`;
}

function toneByValue(value) {
  if (Number(value) > 0) return "positive";
  if (Number(value) < 0) return "negative";
  return "neutral";
}

function toneClassByValue(value) {
  if (Number(value) > 0) return "tone-positive";
  if (Number(value) < 0) return "tone-negative";
  return "tone-neutral";
}

function actionTone(action) {
  if (["buy", "add", "hold"].includes(action)) return "positive";
  if (["reduce", "trim", "watch"].includes(action)) return "warning";
  if (["sell", "stop"].includes(action)) return "negative";
  return "blue";
}

function riskLabel(risk) {
  return ({ low: "低", mid: "中", high: "高" })[risk] || risk || "--";
}

function riskTone(risk) {
  return ({ low: "positive", mid: "warning", high: "negative" })[risk] || "blue";
}

function statusTone(status) {
  return ({ running: "blue", success: "positive", done: "positive", pending: "warning", failed: "negative", offline: "negative" })[status] || "blue";
}

function statusText(status) {
  return ({ running: "运行中", success: "成功", done: "完成", pending: "等待", failed: "失败", offline: "离线" })[status] || status || "--";
}

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Hong_Kong", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date);
}

function formatFullDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second}`;
}

function icon(name) {
  const paths = {
    home: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5 10.5V20h14v-9.5"/><path d="M9 20v-6h6v6"/>',
    star: '<path d="m12 3 2.7 5.6 6.2.9-4.5 4.3 1.1 6.1-5.5-2.9-5.5 2.9 1.1-6.1-4.5-4.3 6.2-.9L12 3z"/>',
    bot: '<rect x="5" y="7" width="14" height="11" rx="3"/><path d="M12 7V4"/><path d="M8.5 12h.01"/><path d="M15.5 12h.01"/><path d="M9 16h6"/>',
    bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 7h18s-3 0-3-7"/><path d="M10 19a2 2 0 0 0 4 0"/>',
    settings: '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7z"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2 3.4-.2-.1a1.8 1.8 0 0 0-2 .1 8 8 0 0 1-1.6.7 1.8 1.8 0 0 0-1.1 1.5V23H9v-.3a1.8 1.8 0 0 0-1.1-1.5 8 8 0 0 1-1.6-.7 1.8 1.8 0 0 0-2-.1l-.2.1-2-3.4.1-.1a1.7 1.7 0 0 0 .3-1.9 8 8 0 0 1 0-2 1.7 1.7 0 0 0-.3-1.9l-.1-.1 2-3.4.2.1a1.8 1.8 0 0 0 2-.1A8 8 0 0 1 8 7a1.8 1.8 0 0 0 1.1-1.5V5h4v.5A1.8 1.8 0 0 0 14.2 7a8 8 0 0 1 1.6.7 1.8 1.8 0 0 0 2 .1l.2-.1 2 3.4-.1.1a1.7 1.7 0 0 0-.3 1.9 8 8 0 0 1-.2 1.9z"/>',
    chart: '<path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 3-3 3 2 5-7"/>',
    portfolio: '<path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/><rect x="4" y="7" width="16" height="12" rx="2"/><path d="M4 12h16"/>',
    picks: '<path d="M4 5h16"/><path d="M4 12h10"/><path d="M4 19h7"/><path d="m15 18 2 2 4-5"/>',
    chevron: '<path d="m9 18 6-6-6-6"/>',
    refresh: '<path d="M21 12a9 9 0 0 1-15.3 6.4"/><path d="M3 12A9 9 0 0 1 18.3 5.6"/><path d="M18 2v4h4"/><path d="M6 22v-4H2"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.chart}</svg>`;
}

function installShell() {
  const navItems = [
    ["overview", "index.html", "home", "市场总览"],
    ["watchlist", "watchlist.html", "star", "自选股"],
    ["picks", "picks.html", "picks", "今日选股"],
    ["holdings", "holdings.html", "portfolio", "当前持仓"],
    ["performance", "performance.html", "chart", "历史收益"],
    ["etf", "etf.html", "bot", "ETF 策略"],
    ["small-cap", "small-cap.html", "bot", "小盘策略"],
    ["breadth", "breadth.html", "chart", "市场宽度"],
    ["sentiment", "sentiment.html", "bell", "散户情绪"],
    ["macro", "macro.html", "settings", "宏观指标"],
  ];

  document.querySelector(".sidebar").innerHTML = `
    <a class="brand" href="index.html" aria-label="Quant Desk">
      <span class="brand-mark">QD</span>
      <span class="brand-copy"><strong>Quant Desk</strong><small>Signal Console</small></span>
    </a>
    <nav class="side-nav" aria-label="主导航">
      ${navItems.map(([key, href, iconName, label]) => `<a href="${href}" data-nav="${key}">${icon(iconName)}<span>${label}</span></a>`).join("")}
    </nav>
    <section class="side-status" aria-label="服务状态">
      <span>DATA SOURCE</span>
      <strong id="apiMode">--</strong>
      <small id="runSummary">等待首次刷新</small>
    </section>
    <button class="sidebar-toggle" type="button" aria-label="折叠侧栏">${icon("chevron")}</button>
  `;

  document.querySelector(".topbar").innerHTML = `
    <div class="page-heading">
      <p class="eyebrow">--</p>
      <h1>--</h1>
    </div>
    <div class="topbar-actions">
      <span class="connection-badge" id="connectionBadge">连接中</span>
      <div class="market-clock" aria-label="市场时间"><span id="marketDate">--</span><strong id="marketClock">--:--:--</strong></div>
      <button class="icon-button" id="refreshButton" type="button" title="刷新" aria-label="刷新">${icon("refresh")}</button>
    </div>
  `;

  dom.apiMode = document.querySelector("#apiMode");
  dom.runSummary = document.querySelector("#runSummary");
  dom.connectionBadge = document.querySelector("#connectionBadge");
  dom.refreshButton = document.querySelector("#refreshButton");
  dom.marketDate = document.querySelector("#marketDate");
  dom.marketClock = document.querySelector("#marketClock");

  document.querySelector(".sidebar-toggle").addEventListener("click", () => {
    document.body.classList.toggle("sidebar-collapsed");
  });
}

function updatePageHeading(page) {
  const [eyebrow, title] = PAGE_META[page] || PAGE_META.overview;
  const eyebrowNode = document.querySelector(".page-heading .eyebrow");
  const titleNode = document.querySelector(".page-heading h1");
  if (eyebrowNode) eyebrowNode.textContent = eyebrow;
  if (titleNode) titleNode.textContent = title;
}

function pill(text, tone = "") {
  return `<span class="pill ${tone}">${escapeHtml(text)}</span>`;
}

function tag(text, tone = "") {
  return `<span class="tag ${tone}">${escapeHtml(text)}</span>`;
}

function panel({ title, kicker = "", description = "", tools = "", span = "span-6", body = "" }) {
  return `
    <section class="panel ${span}">
      <div class="panel-header">
        <div class="panel-title">
          ${kicker ? `<p class="panel-kicker">${escapeHtml(kicker)}</p>` : ""}
          <h2>${escapeHtml(title)}</h2>
          ${description ? `<p>${escapeHtml(description)}</p>` : ""}
        </div>
        ${tools ? `<div class="toolbar">${tools}</div>` : ""}
      </div>
      ${body}
    </section>
  `;
}

function inlineLoading(label = "加载中") {
  return `<div class="empty-state">${escapeHtml(label)}...</div>`;
}

function metricCard(label, value, foot = "", tone = "") {
  return `<article class="metric-card"><span>${escapeHtml(label)}</span><strong class="${tone ? `tone-${tone}` : ""}">${escapeHtml(value)}</strong><small>${escapeHtml(foot)}</small></article>`;
}

function summaryGrid(cards) {
  return `<section class="summary-grid" aria-label="核心指标">${cards.join("")}</section>`;
}

function table(headers, rows, minWidth = 880) {
  if (!rows?.length) return `<div class="empty-state">暂无数据</div>`;
  return `
    <div class="table-wrap">
      <table class="data-table" style="min-width: ${minWidth}px;">
        <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
        <tbody>${rows.join("")}</tbody>
      </table>
    </div>
  `;
}

function sparkPath(values, width = 140, height = 48, pad = 4) {
  const source = Array.isArray(values) && values.length > 1 ? values : null;
  if (!source) return "";
  const min = Math.min(...source);
  const max = Math.max(...source);
  const span = max - min || 1;
  return source.map((value, index) => {
    const x = pad + (index / (source.length - 1)) * (width - pad * 2);
    const y = height - pad - ((value - min) / span) * (height - pad * 2);
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
}

function smoothSparkPath(values, width = 140, height = 48, pad = 4) {
  const source = Array.isArray(values) && values.length > 1 ? values : null;
  if (!source) return "";
  const min = Math.min(...source);
  const max = Math.max(...source);
  const span = max - min || 1;
  const points = source.map((value, index) => ({
    x: pad + (index / (source.length - 1)) * (width - pad * 2),
    y: height - pad - ((value - min) / span) * (height - pad * 2),
  }));
  return points.map((point, index) => {
    if (index === 0) return `M${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
    const prev = points[index - 1];
    const controlX = (prev.x + point.x) / 2;
    return `C${controlX.toFixed(1)} ${prev.y.toFixed(1)} ${controlX.toFixed(1)} ${point.y.toFixed(1)} ${point.x.toFixed(1)} ${point.y.toFixed(1)}`;
  }).join(" ");
}

function sparkline(values, valueForTone = 0, width = 140, height = 48, options = {}) {
  if (!Array.isArray(values) || values.length < 2) return `<div class="empty-sparkline">暂无走势</div>`;
  const path = options.smooth ? smoothSparkPath(values, width, height) : sparkPath(values, width, height);
  return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" role="img" aria-label="走势"><path d="${path}"></path></svg>`;
}

function barList(items, options = {}) {
  const max = options.max ?? 100;
  const color = options.color ?? "var(--accent)";
  if (!items?.length) return `<div class="empty-state">暂无数据</div>`;
  return `
    <div class="bar-list">
      ${items.map((item) => {
        const value = Number(item.value ?? 0);
        const width = Math.max(0, Math.min(100, (value / max) * 100));
        return `
          <div class="bar-row">
            <div class="bar-label"><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.detail || "")}</span></div>
            <span class="bar-value">${valueWithUnit(value, item.unit ?? options.unit ?? "")}</span>
            <div class="bar-track" aria-hidden="true"><div class="bar-fill" style="--bar: ${width}%; --bar-color: ${color};"></div></div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function detailGrid(items) {
  if (!items?.length) return `<div class="empty-state">暂无明细</div>`;
  return `<div class="split-detail">${items.map((item) => `<div class="detail-box"><span>${escapeHtml(item.label)}</span><strong class="${item.tone ? `tone-${item.tone}` : ""}">${escapeHtml(item.value)}</strong><small>${escapeHtml(item.detail || "")}</small></div>`).join("")}</div>`;
}

function timeline(items) {
  if (!items?.length) return `<div class="empty-state">暂无运行记录</div>`;
  return `<div class="timeline">${items.map((item) => `<article class="timeline-item"><span class="timeline-time">${escapeHtml(item.time || "")}</span><div><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.detail || "")}</span></div>${pill(statusText(item.status), statusTone(item.status))}</article>`).join("")}</div>`;
}

function alertList(items) {
  if (!items?.length) return `<div class="empty-state">暂无提醒</div>`;
  return `<div class="alert-list">${items.map((item) => `<article class="alert-item"><div class="inline-between"><strong>${escapeHtml(item.title)}</strong>${pill(item.level === "warning" ? "关注" : "信息", item.level === "warning" ? "warning" : "blue")}</div><span>${escapeHtml(item.detail || "")}</span></article>`).join("")}</div>`;
}

function scoreBlock(score, label, detail, bars = [], color = "var(--accent)") {
  const safe = Math.max(0, Math.min(100, Number(score || 0)));
  return `<div class="score-block"><div class="score-ring" style="--score: ${safe}%; --score-color: ${color};"><div><strong>${intText(safe)}</strong><span>${escapeHtml(label)}</span></div></div><div class="stack">${detail ? `<p class="note">${escapeHtml(detail)}</p>` : ""}${barList(bars, { color })}</div></div>`;
}

function heatColor(value) {
  if (Number(value) >= 75) return "rgba(0,200,150,0.18)";
  if (Number(value) >= 60) return "rgba(0,212,255,0.14)";
  if (Number(value) >= 45) return "rgba(255,181,71,0.15)";
  return "rgba(255,77,106,0.16)";
}

function heatmap(items, valueKey, label = "热度") {
  if (!items?.length) return `<div class="empty-state">暂无数据</div>`;
  return `<div class="heatmap-grid">${items.map((item) => {
    const value = item[valueKey];
    const change = item.change_pct ?? item.delta_pct ?? item.change;
    return `<article class="heat-cell" style="background: ${heatColor(value)};"><strong>${escapeHtml(item.name)}</strong><span class="${toneClassByValue(change)}">${label} ${valueWithUnit(value, "%", 0)}${change !== undefined ? ` / ${pctText(change, 0)}` : ""}</span></article>`;
  }).join("")}</div>`;
}

function pageDecisionBrief({ kicker = "Strategy Brief", title, detail, tone = "blue", metrics = [] }) {
  return `
    <section class="decision-hero ${tone}">
      <div class="decision-copy"><p class="panel-kicker">${escapeHtml(kicker)}</p><h2>${escapeHtml(title || "--")}</h2><p>${escapeHtml(detail || "")}</p></div>
      <div class="decision-metrics" aria-label="页面关键判断">${metrics.map((item) => `<div class="decision-metric"><span>${escapeHtml(item.label)}</span><strong>${escapeHtml(item.value)}</strong></div>`).join("")}</div>
    </section>
  `;
}

function scoreLabel(score, kind = "risk") {
  const value = Number(score);
  if (Number.isNaN(value)) return "--";
  if (kind === "sentiment") return value >= 78 ? "情绪偏热" : value >= 60 ? "情绪活跃" : value >= 45 ? "情绪中性" : "情绪低迷";
  if (kind === "breadth") return value >= 70 ? "扩散充分" : value >= 55 ? "扩散修复" : value >= 45 ? "宽度中性" : "宽度偏窄";
  return value >= 70 ? "偏强" : value >= 55 ? "中性偏强" : value >= 45 ? "中性" : value >= 30 ? "偏弱" : "低迷";
}

function weightDeltaText(target, current) {
  const diff = Number(target) - Number(current);
  if (Number.isNaN(diff)) return "--";
  if (Math.abs(diff) < 0.5) return "维持";
  return `${diff > 0 ? "+" : ""}${valueWithUnit(diff, "%", 0)}`;
}

function rangeBar(value, extraClass = "") {
  const safe = Math.max(0, Math.min(100, Number(value || 0)));
  return `<div class="range-bar ${extraClass}"><span style="--pos: ${safe}%;"></span></div>`;
}

function factorBars(factors = []) {
  return `<div class="factor-bars">${factors.map((factor, index) => {
    const name = Array.isArray(factor) ? factor[0] : factor.name;
    const value = Array.isArray(factor) ? factor[1] : factor.value;
    return `<div class="factor-row"><span>${escapeHtml(name)}</span><div class="factor-track"><i style="--bar:${value}%; --factor-color: var(--factor-${index + 1});"></i></div><strong>${intText(value)}%</strong></div>`;
  }).join("")}</div>`;
}

function equityChart(series, benchmark = []) {
  if (!Array.isArray(series) || series.length < 2) return `<div class="empty-state">暂无曲线数据</div>`;
  const width = 960;
  const height = 360;
  const pad = { top: 28, right: 36, bottom: 38, left: 34 };
  const benchmarkSeries = Array.isArray(benchmark) && benchmark.length > 1 ? benchmark : [];
  const all = [...series, ...benchmarkSeries];
  const min = Math.min(...all, -8);
  const max = Math.max(...all, 10);
  const toPoint = (value, index, length) => {
    const x = pad.left + (index / Math.max(1, length - 1)) * (width - pad.left - pad.right);
    const y = pad.top + (1 - (value - min) / (max - min || 1)) * (height - pad.top - pad.bottom);
    return [x, y];
  };
  const path = (items) => items.map((value, index) => {
    const [x, y] = toPoint(value, index, items.length);
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  const lastSeriesValue = series[series.length - 1];
  const area = `${path(series)} L${toPoint(lastSeriesValue, series.length - 1, series.length)[0].toFixed(1)} ${height - pad.bottom} L${pad.left} ${height - pad.bottom} Z`;
  const zeroY = toPoint(0, 0, series.length)[1];

  return `
    <div class="chart-panel">
      <svg class="equity-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="历史收益曲线">
        <defs><linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="rgba(0,212,255,.32)"/><stop offset="100%" stop-color="rgba(0,212,255,0)"/></linearGradient></defs>
        ${[0.2, 0.4, 0.6, 0.8].map((ratio) => `<line class="chart-grid-line" x1="${pad.left}" x2="${width - pad.right}" y1="${pad.top + ratio * (height - pad.top - pad.bottom)}" y2="${pad.top + ratio * (height - pad.top - pad.bottom)}"/>`).join("")}
        <rect class="drawdown-zone" x="430" y="${pad.top}" width="112" height="${height - pad.top - pad.bottom}"></rect>
        <line class="zero-line" x1="${pad.left}" x2="${width - pad.right}" y1="${zeroY}" y2="${zeroY}"></line>
        <path class="equity-area" d="${area}"></path>
        <path class="equity-line" d="${path(series)}"></path>
        ${benchmarkSeries.length ? `<path class="benchmark-line" d="${path(benchmarkSeries)}"></path>` : ""}
      </svg>
    </div>
  `;
}

function sentimentGauge(input) {
  if (input === null || input === undefined) return `<div class="empty-state">暂无情绪数据</div>`;
  const data = typeof input === "object" && input !== null ? input : { score: input };
  const score = data.score;
  const previousDay = data.previous_day_score;
  const previousWeek = data.previous_week_score;
  const safe = Math.max(0, Math.min(100, Number(score || 0)));
  const angle = -180 + safe * 1.8;
  const dotX = 120 + Math.cos((angle * Math.PI) / 180) * 82;
  const dotY = 120 + Math.sin((angle * Math.PI) / 180) * 82;
  const zone = data.label
    ? [data.label, safe >= 60 ? "positive" : safe < 40 ? "negative" : "neutral"]
    : safe < 20 ? ["极度恐惧", "negative"] : safe < 40 ? ["恐惧", "negative"] : safe < 60 ? ["中性", "neutral"] : safe < 80 ? ["贪婪", "positive"] : ["极度贪婪", "positive"];
  const trendRows = data.trend_6m?.length ? data.trend_6m : data.trend_30d || [];
  const spark = trendRows.map((item) => Number(item.value));
  const dayDiff = previousDay === null || previousDay === undefined ? null : safe - Number(previousDay);
  const weekDiff = previousWeek === null || previousWeek === undefined ? null : safe - Number(previousWeek);
  const firstDate = trendRows[0]?.date?.slice(5) || "6M";
  const lastDate = trendRows[trendRows.length - 1]?.date?.slice(5) || "Now";
  const note = data.calculation_note || "当前情绪值由市场宽度、强势行业数量和行业平均涨跌合成，归一化到 0-100；数值越高代表短线风险偏好越热。";
  const trendSource = data.trend_source ? ` · ${data.trend_source}` : "";
  return `
    <section class="sentiment-card">
      <div class="module-header"><div><span class="live-dot"></span><p class="panel-kicker">Live Data</p><h2>散户情绪 <span class="info-tip" tabindex="0" aria-label="散户情绪说明">?<span>${escapeHtml(note)}</span></span></h2></div><span class="mono">${formatDateTime(new Date().toISOString())}</span></div>
      <div class="gauge-wrap">
        <svg class="sentiment-gauge" viewBox="0 0 240 150" role="img" aria-label="散户情绪仪表">
          <path class="gauge-zone z1" d="M30 120 A90 90 0 0 1 58 54"></path>
          <path class="gauge-zone z2" d="M58 54 A90 90 0 0 1 102 31"></path>
          <path class="gauge-zone z3" d="M102 31 A90 90 0 0 1 148 31"></path>
          <path class="gauge-zone z4" d="M148 31 A90 90 0 0 1 188 56"></path>
          <path class="gauge-zone z5" d="M188 56 A90 90 0 0 1 210 120"></path>
          <circle class="gauge-dot" cx="${dotX.toFixed(1)}" cy="${dotY.toFixed(1)}" r="4.5"></circle>
        </svg>
        <div class="gauge-score"><strong class="tone-${zone[1]}">${intText(safe)}</strong><span>${zone[0]}</span></div>
      </div>
      <div class="sentiment-compare">
        <span>昨日 <strong class="${toneClassByValue(dayDiff)}">${dayDiff === null ? "--" : `${dayDiff > 0 ? "↑" : "↓"} ${intText(Math.abs(dayDiff))}`}</strong></span>
        <span>上周 <strong class="${toneClassByValue(weekDiff)}">${weekDiff === null ? "--" : `${weekDiff > 0 ? "↑" : "↓"} ${intText(Math.abs(weekDiff))}`}</strong></span>
      </div>
      <div class="sentiment-trend-wide">
        ${sparkline(spark, safe, 640, 76, { smooth: true })}
        <div class="trend-axis"><span>${escapeHtml(firstDate)}</span><span>近半年日频${escapeHtml(trendSource)}</span><span>${escapeHtml(lastDate)}</span></div>
      </div>
    </section>
  `;
}

function marketHeatmapTreemap(heatmap = {}, activeTimeframe = "1D", activeGroupBy = "sector", activeMarket = "all") {
  const cells = heatmap.cells || [];
  const groupLabels = { sector: "按板块", size: "按市值", index: "按指数" };
  const marketTabs = [
    ["all", "全部"],
    ["us", "美股"],
    ["cn", "A股"],
  ];
  return `
    <section class="panel span-12 heatmap-panel" data-market-heatmap>
      <div class="panel-header">
        <div class="panel-title"><p class="panel-kicker">Treemap · ${escapeHtml(activeTimeframe)} · ${activeMarket === "cn" ? "A股" : activeMarket === "us" ? "美股" : "全部市场"}</p><h2>市场热力图</h2><p>最后更新: ${formatDateTime(heatmap.updated_at) || "--"}</p></div>
        <div class="heatmap-toolbar">
          <div class="mini-tabs market-tabs" data-heatmap-market-tabs>
            ${marketTabs.map(([value, label]) => `<button type="button" data-heatmap-market="${value}" class="${value === activeMarket ? "active" : ""}">${label}</button>`).join("")}
          </div>
          <div class="toolbar segmented" data-heatmap-controls>
            ${["1D", "5D", "1M", "3M"].map((period) => `<button type="button" data-heatmap-period="${period}" class="${period === activeTimeframe ? "active" : ""}">${period}</button>`).join("")}
            <select data-heatmap-group aria-label="热力图分组">
              ${Object.entries(groupLabels).map(([value, label]) => `<option value="${value}" ${value === activeGroupBy ? "selected" : ""}>${label}</option>`).join("")}
            </select>
          </div>
        </div>
      </div>
      <div class="treemap-grid" data-heatmap-body>
        ${cells.length ? cells.map((cell) => {
          const weight = Math.max(10, Math.min(28, Number(cell.weight || cell.market_cap_weight || 14)));
          const row = Math.max(14, Math.min(26, Math.round(weight * 0.9)));
          const returns = cell.returns && typeof cell.returns === "object" ? cell.returns : {};
          const hasPeriodReturn = Object.prototype.hasOwnProperty.call(returns, activeTimeframe) && returns[activeTimeframe] !== null && returns[activeTimeframe] !== undefined;
          const change = hasPeriodReturn ? Number(returns[activeTimeframe]) : null;
          const isCn = cell.market === "cn";
          const title = isCn ? (cell.display_name || cell.name || cell.symbol) : (cell.symbol || cell.name);
          const subtitle = isCn ? cell.symbol : (cell.display_name || cell.name);
          const changeLabel = hasPeriodReturn ? pctText(change) : "无历史数据";
          const cellTone = hasPeriodReturn ? toneByValue(change) : "neutral";
          const cellColor = hasPeriodReturn ? heatmapScale(change) : "#2A2F3C";
          return `<div class="treemap-cell ${cellTone}" style="grid-column: span ${weight}; grid-row: span ${row}; --cell:${cellColor};" title="${escapeHtml(cell.market_label || "")} ${escapeHtml(cell.name)} / ${escapeHtml(activeTimeframe)} ${escapeHtml(changeLabel)} / volume ${intText(cell.volume)}"><span class="sector-float">${escapeHtml(cell.market_label || "")} · ${escapeHtml(cell.sector)}</span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(subtitle || "")}</small><em>${escapeHtml(changeLabel)}</em></div>`;
        }).join("") : `<div class="empty-state treemap-empty">暂无热力图数据</div>`}
      </div>
    </section>
  `;
}

function heatmapScale(value) {
  const number = Number(value);
  if (number <= -2) return "#C0392B";
  if (number < 0) return "#FF4D6A";
  if (number === 0) return "#2A2F3C";
  if (number < 2) return "#00C896";
  return "#00875A";
}

function flattenWatchlistGroups(watchlist = {}) {
  return (watchlist.groups || []).flatMap((group) => (group.items || []).map((item) => ({ ...item, group: group.name })));
}

function watchlistOverviewPanel(watchlist = {}) {
  const rows = flattenWatchlistGroups(watchlist).slice(0, 7);
  return panel({
    title: "自选股",
    kicker: "Watchlist",
    span: "span-4",
    tools: `<a class="panel-link" href="watchlist.html">管理 →</a>`,
    body: rows.length ? `
      <div class="overview-watchlist">
        ${rows.map((row) => {
          const change = row.change_pct ?? row.change;
          return `
            <a class="overview-watch-row" href="watchlist.html">
              <div class="stock-cell">
                <span class="stock-logo">${escapeHtml(row.logo || row.symbol?.slice(0, 1) || "?")}</span>
                <div><strong>${escapeHtml(row.name || row.symbol)}</strong><small>${escapeHtml(row.symbol)} · ${escapeHtml(row.group || "--")}</small></div>
              </div>
              <span class="mono">${valueText(row.price, 2)}</span>
              <em class="${toneClassByValue(change)}">${pctText(change)}</em>
            </a>
          `;
        }).join("")}
      </div>
    ` : `<div class="empty-state">暂无自选股，去自选页添加</div>`,
  });
}

function sectorOverview(input = []) {
  const sectors = input || [];
  const best = sectors.length ? Math.max(...sectors.map((item) => Number(item.performance_pct || 0))) : null;
  const worst = sectors.length ? Math.min(...sectors.map((item) => Number(item.performance_pct || 0))) : null;
  return panel({
    title: "板块表现",
    kicker: "Sector Performance",
    span: "span-12",
    tools: `<div class="mini-tabs"><button class="active">按涨幅</button><button>按跌幅</button><button>按市值</button></div>`,
    body: sectors.length ? `<div class="sector-strip">${sectors.map((item) => {
      const perf = Number(item.performance_pct || 0);
      return `<article class="sector-card ${perf === best ? "best" : perf === worst ? "worst" : ""}"><span class="sector-icon">${escapeHtml(item.icon || "◇")}</span><small>${escapeHtml(item.name)}</small><strong class="${toneClassByValue(perf)}">${pctText(perf)}</strong>${rangeBar(50 + perf / 3 * 50, toneByValue(perf))}<div><span>↑ ${intText(item.up_count)} stocks</span><span>↓ ${intText(item.down_count)} stocks</span></div></article>`;
    }).join("")}</div>` : `<div class="empty-state">暂无板块表现数据</div>`,
  });
}

async function loadHeatmap(timeframe, groupBy, market = "all") {
  const panelNode = document.querySelector("[data-market-heatmap]");
  const body = document.querySelector("[data-heatmap-body]");
  if (!panelNode || !body) return;
  document.querySelectorAll("[data-heatmap-period]").forEach((node) => node.classList.toggle("active", node.dataset.heatmapPeriod === timeframe));
  document.querySelectorAll("[data-heatmap-market]").forEach((node) => node.classList.toggle("active", node.dataset.heatmapMarket === market));
  body.innerHTML = `<div class="empty-state treemap-empty">热力图获取中...</div>`;
  try {
    const payload = await requestJson(joinUrl(API_BASE, `/api/v1/market/heatmap?timeframe=${encodeURIComponent(timeframe)}&group_by=${encodeURIComponent(groupBy)}&market=${encodeURIComponent(market)}`));
    panelNode.outerHTML = marketHeatmapTreemap(payload.data || {}, timeframe, groupBy, market);
    bindOverviewInteractions();
    updateShell(payload.meta || {}, payload.meta?.source === "cache" ? "cache" : "live");
  } catch (error) {
    body.innerHTML = `<div class="empty-state treemap-empty">热力图获取失败：${escapeHtml(error.message)}</div>`;
  }
}

function bindOverviewInteractions() {
  document.querySelectorAll("[data-heatmap-period]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = document.querySelector("[data-heatmap-group]")?.value || "sector";
      const market = document.querySelector("[data-heatmap-market].active")?.dataset.heatmapMarket || "all";
      loadHeatmap(button.dataset.heatmapPeriod, group, market);
    });
  });
  document.querySelectorAll("[data-heatmap-market]").forEach((button) => {
    button.addEventListener("click", () => {
      const group = document.querySelector("[data-heatmap-group]")?.value || "sector";
      const period = document.querySelector("[data-heatmap-period].active")?.dataset.heatmapPeriod || "1D";
      loadHeatmap(period, group, button.dataset.heatmapMarket);
    });
  });
  document.querySelector("[data-heatmap-group]")?.addEventListener("change", (event) => {
    const active = document.querySelector("[data-heatmap-period].active")?.dataset.heatmapPeriod || "1D";
    const market = document.querySelector("[data-heatmap-market].active")?.dataset.heatmapMarket || "all";
    loadHeatmap(active, event.target.value, market);
  });
}

function renderOverview(payload) {
  const {
    account = {},
    market = {},
    strategy_status = [],
    alerts = [],
    decision = null,
    sentiment_gauge = null,
    heatmap = {},
    sectors = [],
    watchlist = {},
  } = payload.data || {};

  dom.app.innerHTML = `
    ${pageDecisionBrief({
      kicker: "Market Command",
      title: decision?.title || "暂无市场结论",
      detail: decision?.detail || "后端暂未返回首页决策摘要。",
      tone: decision?.tone || "blue",
      metrics: [
        { label: "执行动作", value: decision?.action || "--" },
        { label: "市场宽度", value: valueWithUnit(market.breadth_score, "/100", 0) },
        { label: "情绪温度", value: valueWithUnit(market.sentiment_score, "/100", 0) },
        { label: "首要提醒", value: alerts[0]?.title || "--" },
      ],
    })}
    <section class="overview-grid">
      ${sentimentGauge(sentiment_gauge || market.sentiment_score)}
      ${watchlistOverviewPanel(watchlist)}
      ${panel({
        title: "策略状态",
        kicker: "Strategy Hub",
        span: "span-12 strategy-status-panel",
        body: strategy_status.length ? `<div class="compact-action-list">${strategy_status.map((row) => `<a class="compact-action-item" href="${escapeHtml(row.page)}"><div class="inline-between"><div><strong>${escapeHtml(row.name)}</strong><span>${escapeHtml(row.signal)}</span></div>${pill(statusText(row.status), statusTone(row.status))}</div><div class="compact-action-meta"><span>目标 ${valueWithUnit(row.target_exposure_pct, "%", 0)}</span><span>${intText(row.active_positions)} 持仓</span><span class="${toneClassByValue(row.day_pnl_pct)}">${pctText(row.day_pnl_pct)}</span></div></a>`).join("")}</div>` : `<div class="empty-state">暂无策略状态数据</div>`,
      })}
      ${marketHeatmapTreemap(heatmap)}
      ${sectorOverview(sectors)}
    </section>
  `;
  bindOverviewInteractions();
}

function renderWatchlist(payload) {
  const groupsSource = payload.data?.groups || [];
  const selected = groupsSource[0]?.items?.[0] || null;
  dom.app.innerHTML = `
    <section class="watchlist-layout">
      <div class="watchlist-main">
        <div class="watch-toolbar">
          <label class="search-input"><span>⌕</span><input type="search" placeholder="搜索股票 / ticker" data-watch-search /></label>
          <div class="toolbar"><select><option>全部分组</option></select><select><option>按涨跌幅</option></select><button class="primary-button" type="button" data-add-watch>+ 添加股票</button></div>
        </div>
        <div class="watch-add-panel" data-watch-add-panel>
          <form class="watch-add-form" data-watch-add-form>
            <label><span>市场</span><select name="market_region"><option value="cn">A股</option><option value="us">美股</option></select></label>
            <label><span>代码</span><input name="symbol" autocomplete="off" placeholder="600519 / NVDA" required /></label>
            <label><span>名称</span><input name="name" autocomplete="off" placeholder="可选" /></label>
            <label><span>分组</span><input name="sector" autocomplete="off" placeholder="例如 AI 链" /></label>
            <button class="primary-button" type="submit">保存并获取行情</button>
          </form>
          <p class="form-status" data-watch-status></p>
        </div>
        <div class="watch-table">
          ${groupsSource.length ? groupsSource.map((group) => `<div class="group-header">${escapeHtml(group.name)} · ${group.items.length}只</div>${group.items.map((row, index) => {
            const change = row.change_pct ?? row.change;
            const intradayLow = row.intraday_low ?? row.price * 0.98;
            const intradayHigh = row.intraday_high ?? row.price * 1.02;
            const intradayCurrent = row.intraday_current ?? row.price;
            const amplitudePosition = ((intradayCurrent - intradayLow) / Math.max(0.01, intradayHigh - intradayLow)) * 100;
            const weekPosition = row.week52_current !== undefined ? ((row.week52_current - row.week52_low) / Math.max(0.01, row.week52_high - row.week52_low)) * 100 : row.range;
            const market = row.market_region || row.market || (String(row.symbol).match(/^\\d+$/) ? "cn" : "us");
            return `<article class="watch-row ${index === 0 ? "selected" : ""}" data-watch-symbol="${escapeHtml(row.symbol)}" data-watch-market="${escapeHtml(market)}"><div class="stock-cell"><span class="stock-logo">${escapeHtml(row.logo || row.symbol.slice(0, 1))}</span><div><strong>${escapeHtml(row.symbol)}</strong><small>${escapeHtml(row.name)}</small></div></div><span class="mono price">${valueText(row.price, 2)}</span><span class="change-badge ${toneByValue(change)}">${pctText(change)}</span><div>${rangeBar(amplitudePosition, "range")}</div><div class="volume-bar"><i style="--bar:${row.volume_ratio ?? 0}%;"></i><span>${intText(row.volume_ratio)}%</span></div><span>${escapeHtml(row.market_cap || row.marketCap || "--")}</span>${rangeBar(weekPosition, "week")}<button class="row-action danger" type="button" data-watch-delete="${escapeHtml(row.symbol)}" data-watch-market="${escapeHtml(market)}">删除</button></article>`;
          }).join("")}`).join("") : `<div class="empty-state">暂无自选股数据</div>`}
        </div>
      </div>
      <aside class="stock-detail">
        ${selected ? `
        <div class="inline-between"><div><p class="panel-kicker">Selected Stock</p><h2>${escapeHtml(selected.symbol)}</h2><span>${escapeHtml(selected.name)}</span></div><button class="icon-button">×</button></div>
        ${equityChart((selected.price_series || selected.trend || []).map((item) => Number(item.return_pct ?? item.value ?? item)), (selected.benchmark_series || []).map((item) => Number(item.return_pct ?? item.value ?? item)))}
        ${detailGrid([
          { label: "最新价", value: valueText(selected.price, 2), detail: "Last" },
          { label: "涨跌幅", value: pctText(selected.change_pct ?? selected.change), tone: toneByValue(selected.change_pct ?? selected.change), detail: "Today" },
          { label: "成交量", value: `${intText(selected.volume_ratio ?? selected.volume)}%`, detail: "Relative" },
          { label: "市值", value: selected.market_cap || selected.marketCap, detail: "Market cap" },
        ])}
        <div class="news-list"><strong>Recent News</strong>${(selected.news || []).length ? selected.news.map((item) => `<span>${escapeHtml(item.title || item)}</span>`).join("") : `<span>暂无新闻数据</span>`}</div>
        ` : `<div class="empty-state">请选择一只股票</div>`}
      </aside>
    </section>
  `;
  bindWatchlistInteractions();
}

function setWatchlistStatus(message, tone = "") {
  const node = document.querySelector("[data-watch-status]");
  if (!node) return;
  node.textContent = message || "";
  node.className = `form-status ${tone}`;
}

function bindWatchlistInteractions() {
  const panelNode = document.querySelector("[data-watch-add-panel]");
  document.querySelector("[data-add-watch]")?.addEventListener("click", () => {
    panelNode?.classList.toggle("open");
    panelNode?.querySelector("input[name='symbol']")?.focus();
  });
  document.querySelector("[data-watch-search]")?.addEventListener("input", (event) => {
    const query = event.target.value.trim().toLowerCase();
    document.querySelectorAll(".watch-row").forEach((row) => {
      row.hidden = query && !row.textContent.toLowerCase().includes(query);
    });
  });
  document.querySelector("[data-watch-add-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const body = {
      market_region: String(formData.get("market_region") || "cn"),
      symbol: String(formData.get("symbol") || "").trim(),
      name: String(formData.get("name") || "").trim(),
      sector: String(formData.get("sector") || "").trim(),
    };
    if (!body.symbol) {
      setWatchlistStatus("请先输入股票代码", "negative");
      return;
    }
    setWatchlistStatus("正在保存并获取行情...");
    form.querySelector("button[type='submit']")?.setAttribute("disabled", "disabled");
    try {
      const payload = await sendJson("/api/v1/watchlist", { method: "POST", body: JSON.stringify(body) });
      renderWatchlist(payload);
      updateShell(payload.meta || {}, payload.meta?.source === "cache" ? "cache" : "live");
    } catch (error) {
      setWatchlistStatus(`保存失败：${error.message}`, "negative");
      form.querySelector("button[type='submit']")?.removeAttribute("disabled");
    }
  });
  document.querySelectorAll("[data-watch-delete]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const symbol = button.dataset.watchDelete;
      const market = button.dataset.watchMarket;
      if (!symbol) return;
      button.textContent = "删除中";
      button.setAttribute("disabled", "disabled");
      try {
        const payload = await sendJson(`/api/v1/watchlist/${encodeURIComponent(symbol)}?market=${encodeURIComponent(market || "")}`, { method: "DELETE" });
        renderWatchlist(payload);
        updateShell(payload.meta || {}, payload.meta?.source === "cache" ? "cache" : "live");
      } catch (error) {
        button.textContent = "失败";
        button.removeAttribute("disabled");
      }
    });
  });
}

function renderPicks(payload) {
  const { strategy_label = "", trade_date = "", strategies = [], items = [] } = payload.data || {};
  dom.app.innerHTML = `
    <section class="strategy-toolbar"><div class="mini-tabs">${strategies.map((name) => `<button class="${name === strategy_label ? "active" : ""}">${escapeHtml(name)}</button>`).join("")}</div><div class="toolbar"><button class="ghost-button">← 昨日</button><button class="primary-button">今日 →</button><button class="ghost-button">导出 CSV ↓</button></div></section>
    <div class="section-heading"><h2>今日选股结果</h2><span>${escapeHtml(trade_date)} · 共 ${items.length} 只</span></div>
    <section class="pick-grid">
      ${items.length ? items.map((pick) => {
        const isFresh = pick.is_new ?? pick.fresh;
        const entry = pick.entry_price ?? pick.entry;
        const stop = pick.stop_loss ?? pick.stop;
        const target = pick.take_profit ?? pick.target;
        const tags = pick.tags || [];
        return `<article class="pick-card ${isFresh ? "fresh" : ""}"><div class="inline-between"><div><strong>${escapeHtml(pick.symbol)}</strong><span>${escapeHtml(pick.name)}</span></div><div class="mini-ring" style="--score:${pick.score}%;"><span>${intText(pick.score)}</span></div></div>${factorBars(pick.factors)}<div class="trade-levels"><div><span>Entry</span><strong>${fixedText(entry, 2)}</strong></div><div><span>Stop</span><strong>${fixedText(stop, 2)}</strong></div><div><span>Target</span><strong>${fixedText(target, 2)}</strong></div></div><div class="tag-row">${tags.map((item) => tag(item, item === "持仓中" || pick.in_portfolio ? "positive" : "blue")).join("")}</div></article>`;
      }).join("") : `<div class="empty-state">暂无选股结果</div>`}
    </section>
  `;
}

function renderHoldings(payload) {
  const summary = payload.data?.summary || {};
  const source = payload.data?.holdings || [];
  const allocation = payload.data?.allocation || [];
  const totalPnl = source.reduce((sum, item) => sum + Number(item.pnl_pct || 0), 0);
  dom.app.innerHTML = `
    ${summaryGrid([
      metricCard("总市值", summary.total_market_value === undefined ? "--" : `¥${intText(summary.total_market_value)}`, "Portfolio value"),
      metricCard("今日盈亏", summary.day_pnl_amount === undefined ? "--" : `${Number(summary.day_pnl_amount) > 0 ? "+" : ""}¥${intText(summary.day_pnl_amount)}`, pctText(summary.day_pnl_pct), toneByValue(summary.day_pnl_amount)),
      metricCard("累计收益", `${pctText(summary.total_return_pct)}`, "Total return", toneByValue(summary.total_return_pct ?? totalPnl)),
      metricCard("仓位使用", valueWithUnit(summary.exposure_pct, "%", 0), `${summary.position_count ?? source.length} 只持仓`),
      metricCard("持仓数量", `${intText(summary.position_count ?? source.length)} 只`, `Sector diversity ${summary.sector_diversity ?? allocation.length}`),
    ])}
    ${panel({
      title: "当前持仓",
      kicker: "Current Holdings",
      span: "span-12",
      body: table(
        ["股票", "持仓均价", "最新价", "持仓量", "市值", "盈亏额", "盈亏%", "仓位占比", "持有天数", "操作"],
        source.map((row) => {
          const avgCost = row.avg_cost ?? row.cost;
          const marketValue = row.market_value ?? row.weight_pct * 24800;
          const pnlAmount = row.pnl_amount ?? row.pnl_pct;
          return `<tr class="${Number(row.pnl_pct) >= 0 ? "profit-row" : "loss-row"}"><td><strong>${escapeHtml(row.symbol)}</strong><br><small>${escapeHtml(row.name)}</small></td><td>${valueText(avgCost, 2)}</td><td>${valueText(row.last_price, 2)}</td><td>${intText(row.quantity ?? row.weight_pct * 1000)}</td><td>¥${intText(marketValue)}</td><td class="${toneClassByValue(pnlAmount)}">${Number(pnlAmount) > 0 ? "+" : ""}¥${intText(pnlAmount)}</td><td><div class="pnl-bar ${toneByValue(row.pnl_pct)}"><i style="--bar:${Math.min(100, Math.abs(row.pnl_pct) * 8)}%;"></i><span>${pctText(row.pnl_pct)}</span></div></td><td><div class="mini-donut" style="--score:${row.weight_pct}%;"></div></td><td>${row.holding_days > 30 ? tag(`${row.holding_days} 天`, "warning") : `${row.holding_days} 天`}</td><td>${icon("chart")}</td></tr>`;
        }),
        1100,
      ),
    })}
    ${panel({ title: "行业配置", kicker: "Allocation", span: "span-12", body: `<div class="allocation-panel"><div class="allocation-donut"></div>${barList(allocation.map((item) => ({ name: item.sector, value: item.weight_pct, unit: "%", detail: item.market_value ? `¥${intText(item.market_value)}` : "" })), { color: "var(--accent)" })}</div>` })}
  `;
}

function renderPerformance(payload) {
  const data = payload.data || {};
  const metricsData = data.metrics || {};
  const equity = data.equity_curve?.length ? data.equity_curve.map((item) => Number(item.return_pct)) : [];
  const benchmark = data.benchmark_curve?.length ? data.benchmark_curve.map((item) => Number(item.return_pct)) : [];
  const monthly = data.monthly_returns || [];
  const metrics = [
    ["年化收益率", pctText(metricsData.annual_return_pct), "Annualized", toneByValue(metricsData.annual_return_pct)],
    ["最大回撤", pctText(metricsData.max_drawdown_pct), "Max drawdown", toneByValue(metricsData.max_drawdown_pct)],
    ["夏普比率", valueText(metricsData.sharpe, 2), "Sharpe", toneByValue(metricsData.sharpe)],
    ["卡玛比率", valueText(metricsData.calmar, 2), "Calmar", toneByValue(metricsData.calmar)],
    ["胜率", pctText(metricsData.win_rate_pct), "Win rate", "neutral"],
    ["盈亏比", valueText(metricsData.profit_loss_ratio, 2), "P/L ratio", toneByValue(metricsData.profit_loss_ratio)],
    ["Beta", valueText(metricsData.beta, 2), "Beta", "neutral"],
    ["Alpha", pctText(metricsData.alpha_pct), `vs ${data.benchmark || "基准"}`, toneByValue(metricsData.alpha_pct)],
  ];
  dom.app.innerHTML = `
    <section class="strategy-toolbar"><div class="mini-tabs"><button class="active">${escapeHtml(data.strategy_label || "动量策略")}</button><button>ETF 轮动</button><button>小盘股</button></div><div class="toolbar"><label><input type="checkbox" checked /> 对比 ${escapeHtml(data.benchmark || "沪深300")}</label><label><input type="checkbox" /> 标普500</label><div class="mini-tabs"><button>3M</button><button class="active">1Y</button><button>全部</button></div></div></section>
    ${panel({ title: "历史收益曲线", kicker: "Historical Performance", span: "span-12", body: equityChart(equity, benchmark) })}
    <section class="metric-strip">${metrics.map(([label, value, delta, tone]) => `<article class="perf-metric"><span>${label}</span><strong class="tone-${tone}">${value}</strong><small>${delta}</small></article>`).join("")}</section>
    ${panel({ title: "月度收益热力", kicker: "Monthly Return Heatmap", span: "span-12", body: monthly.length ? `<div class="monthly-heat">${monthly.map((item) => { const value = Number(item.return_pct || 0); return `<span class="${toneByValue(value)}" title="${item.year || ""}-${item.month || ""} ${pctText(value)}">${pctText(value, 1)}</span>`; }).join("")}</div>` : `<div class="empty-state">暂无月度收益数据</div>` })}
  `;
}

function compactInstrumentCards(items) {
  if (!items?.length) return `<div class="empty-state">暂无标的</div>`;
  return `<div class="signal-card-grid">${items.map((item) => `<article class="signal-card ${actionTone(item.action)}"><div class="signal-card-head"><div><span>${escapeHtml(item.symbol)} ${escapeHtml(item.market || "")}</span><strong>${escapeHtml(item.name)}</strong></div>${tag(item.action_label || item.action, actionTone(item.action))}</div>${sparkline(item.trend, item.change_pct)}<div class="signal-card-metrics"><div><span>信号分</span><strong>${intText(item.score)}</strong></div><div><span>仓位</span><strong>${valueWithUnit(item.suggested_weight_pct, "%", 0)}</strong></div><div><span>涨跌</span><strong class="${toneClassByValue(item.change_pct)}">${pctText(item.change_pct)}</strong></div></div><p class="note">${escapeHtml(item.reason || "")}</p></article>`).join("")}</div>`;
}

function strategyLogConsole(items = []) {
  if (!items?.length) return `<div class="empty-state">暂无策略日志</div>`;
  return `
    <div class="strategy-log-console">
      ${items.slice(-80).reverse().map((item) => {
        const level = String(item.level || "info").toLowerCase();
        const tone = level === "error" ? "negative" : level === "warning" ? "warning" : level === "debug" ? "blue" : "positive";
        const stamp = item.time || item.received_at || "";
        const timeText = stamp.includes("T") ? formatFullDateTime(stamp) : stamp;
        return `
          <article class="strategy-log-line ${tone}">
            <span class="log-time">${escapeHtml(timeText || "--")}</span>
            <span class="log-level">${escapeHtml(level.toUpperCase())}</span>
            <span class="log-stage">${escapeHtml(item.stage || item.trade_date || "--")}</span>
            <p>${escapeHtml(item.message || "")}</p>
          </article>
        `;
      }).join("")}
    </div>
  `;
}

function renderEtf(payload) {
  const { strategy = {}, summary = {}, recommendations = [], holdings = [], regime = {}, events = [], logs = [] } = payload.data || {};
  dom.app.innerHTML = `
    ${pageDecisionBrief({ kicker: strategy.name || "ETF Strategy", title: strategy.decision_title || `目标仓位 ${valueWithUnit(summary.target_exposure_pct, "%", 0)}`, detail: strategy.decision_detail || `当前仓位 ${valueWithUnit(summary.current_exposure_pct, "%", 0)}，风格环境 ${regime.label || "--"}。`, tone: strategy.decision_tone || "blue", metrics: [{ label: "仓位差异", value: weightDeltaText(summary.target_exposure_pct, summary.current_exposure_pct) }, { label: "买入信号", value: summary.buy_count === undefined ? "--" : `${summary.buy_count} 个` }, { label: "风控状态", value: strategy.drawdown_guard || "--" }, { label: "再平衡", value: strategy.rebalance_time || "--" }] })}
    ${summaryGrid([metricCard("目标仓位", valueWithUnit(summary.target_exposure_pct, "%", 0), `当前 ${valueWithUnit(summary.current_exposure_pct, "%", 0)}`), metricCard("买入信号", summary.buy_count === undefined ? "--" : `${summary.buy_count} 个`, `${summary.watch_count ?? "--"} 个观察`), metricCard("当日盈亏", pctText(summary.day_pnl_pct), `本周 ${pctText(summary.week_pnl_pct)}`, toneByValue(summary.day_pnl_pct)), metricCard("最大回撤", pctText(summary.max_drawdown_pct), `风控 ${strategy.drawdown_guard || "--"}`, toneByValue(summary.max_drawdown_pct))])}
    <section class="main-grid">
      ${panel({ title: "推荐标的", kicker: "Signal Cards", span: "span-8", body: compactInstrumentCards(recommendations) })}
      ${panel({ title: "风格环境", kicker: "Regime", span: "span-4", body: scoreBlock(regime.score, regime.label || "环境分", `风险预算 ${valueWithUnit(strategy.risk_budget_pct, "%", 0)}，现金 ${valueWithUnit(strategy.cash_weight_pct, "%", 0)}。`, (regime.factors || []).map((item) => ({ name: item.name, value: item.value, detail: item.detail }))) })}
      ${panel({ title: "当前持仓", kicker: "Positions", span: "span-8", body: table(["代码", "名称", "仓位", "成本", "现价", "当日涨跌", "浮动盈亏"], holdings.map((row) => `<tr><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.name)}</td><td>${valueWithUnit(row.weight_pct, "%", 0)}</td><td>${valueText(row.cost, 3)}</td><td>${valueText(row.last_price, 3)}</td><td class="${toneClassByValue(row.day_change_pct)}">${pctText(row.day_change_pct)}</td><td class="${toneClassByValue(row.pnl_pct)}">${pctText(row.pnl_pct)}</td></tr>`), 780) })}
      ${panel({ title: "运行记录", kicker: "Events", span: "span-4", body: timeline(events) })}
      ${panel({ title: "完整日志", kicker: "JoinQuant Logs", span: "span-12", tools: pill(`${intText(logs.length)} lines`, "blue"), body: strategyLogConsole(logs) })}
    </section>
  `;
}

function renderSmallCap(payload) {
  const { strategy = {}, summary = {}, signals = [], holdings = [], themes = [], risk = {} } = payload.data || {};
  dom.app.innerHTML = `
    ${pageDecisionBrief({ kicker: strategy.name || "Small Cap Strategy", title: strategy.decision_title || "暂无策略结论", detail: strategy.decision_detail || `候选池 ${intText(strategy.candidate_count)} / ${intText(strategy.universe_size)}，当前仓位 ${valueWithUnit(summary.exposure_pct, "%", 0)}。`, tone: strategy.decision_tone || "blue", metrics: [{ label: "买入候选", value: summary.buy_count === undefined ? "--" : `${summary.buy_count} 只` }, { label: "仓位状态", value: valueWithUnit(summary.exposure_pct, "%", 0) }, { label: "单票上限", value: valueWithUnit(strategy.max_position_pct, "%", 0) }, { label: "止损条件", value: strategy.stop_policy || "--" }] })}
    ${summaryGrid([metricCard("今日信号", summary.signal_count === undefined ? "--" : `${summary.signal_count} 只`, `${summary.buy_count ?? "--"} 只买入`), metricCard("策略仓位", valueWithUnit(summary.exposure_pct, "%", 0), `换手 ${valueWithUnit(summary.turnover_pct, "%", 0)}`), metricCard("当日盈亏", pctText(summary.day_pnl_pct), `浮盈 ${pctText(summary.floating_pnl_pct)}`, toneByValue(summary.day_pnl_pct)), metricCard("候选池", `${intText(strategy.candidate_count)} / ${intText(strategy.universe_size)}`, `单票上限 ${valueWithUnit(strategy.max_position_pct, "%", 0)}`)])}
    <section class="main-grid">
      ${panel({ title: "今日信号", kicker: "Signal Cards", span: "span-8", body: signals.length ? `<div class="signal-card-grid">${signals.map((item) => `<article class="signal-card ${actionTone(item.signal)}"><div class="signal-card-head"><div><span>${escapeHtml(item.symbol)} / ${escapeHtml(item.theme)}</span><strong>${escapeHtml(item.name)}</strong></div>${tag(item.signal_label, actionTone(item.signal))}</div><div class="signal-card-metrics"><div><span>分数</span><strong>${intText(item.score)}</strong></div><div><span>风险</span><strong>${riskLabel(item.risk)}</strong></div><div><span>涨跌</span><strong class="${toneClassByValue(item.change_pct)}">${pctText(item.change_pct)}</strong></div></div><p class="note">执行：${escapeHtml(item.suggested_range || "--")}。失效：${escapeHtml(item.invalidation || strategy.stop_policy || "--")}</p></article>`).join("")}</div>` : `<div class="empty-state">暂无今日信号</div>` })}
      ${panel({ title: "风控", kicker: "Risk", span: "span-4", body: `<div class="stack">${barList([{ name: "流动性通过率", value: risk.liquidity_pass_pct, detail: "候选池过滤" }, { name: "最大集中度", value: risk.concentration_pct, detail: "单一持仓" }, { name: "波动压力", value: risk.volatility_score, detail: "短期波动" }], { color: "var(--warning)" })}<p class="note">${escapeHtml(strategy.stop_policy || "")}</p></div>` })}
      ${panel({ title: "当前持仓", kicker: "Positions", span: "span-8", body: table(["代码", "名称", "主题", "仓位", "成本", "现价", "当日涨跌", "浮动盈亏", "天数"], holdings.map((row) => `<tr><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.theme)}</td><td>${valueWithUnit(row.weight_pct, "%", 0)}</td><td>${valueText(row.cost, 2)}</td><td>${valueText(row.last_price, 2)}</td><td class="${toneClassByValue(row.day_change_pct)}">${pctText(row.day_change_pct)}</td><td class="${toneClassByValue(row.pnl_pct)}">${pctText(row.pnl_pct)}</td><td>${intText(row.holding_days)}</td></tr>`), 980) })}
      ${panel({ title: "主题暴露", kicker: "Themes", span: "span-4", body: barList(themes.map((item) => ({ name: item.name, value: item.exposure_pct, detail: `宽度 ${valueWithUnit(item.breadth_pct, "%", 0)}`, unit: "%" }))) })}
    </section>
  `;
}

function marketHeatmapCard(history = {}) {
  const columns = history.columns || [];
  const rows = history.rows || [];
  if (!columns.length || !rows.length) return `<div class="empty-state">暂无热力数据</div>`;
  return `<section class="market-heat-section"><div class="market-heat-title"><span class="heat-title-icon" aria-hidden="true"></span><h2>${escapeHtml(history.title || "近10日市场热力图")}</h2></div><div class="market-heat-scroll"><div class="market-heat-grid" style="--heat-cols: ${columns.length};"><div class="heat-corner"></div>${columns.map((column, index) => `<div class="heat-head${index === 0 ? " total-head" : ""}"><span>${escapeHtml(column).replace(/I$/, "")}</span></div>`).join("")}${rows.map((row) => `<div class="heat-date">${escapeHtml(row.date)}</div>${(row.values || []).map((value, index) => `<div class="heat-value${index === 0 ? " total-cell" : ""}" style="background:${heatColor(value)};">${intText(value)}</div>`).join("")}`).join("")}</div></div></section>`;
}

function renderBreadth(payload) {
  const { summary = {}, metrics = [], industry_width = [], sectors = [], style = [], distribution = [], source_algorithm = {}, heatmap_history = {} } = payload.data || {};
  const industries = industry_width.length ? industry_width : sectors.map((item) => ({ name: item.name, width_pct: item.participation_pct, delta_pct: item.change_pct }));
  const maxCount = Math.max(...distribution.map((item) => item.count), 1);
  dom.app.innerHTML = `${summaryGrid([metricCard("宽度分", valueWithUnit(summary.score, "/100", 0), summary.label || "--"), metricCard("全市场宽度", valueWithUnit(summary.market_width_pct ?? summary.above_ma20_pct, "%", 0), source_algorithm.ma_window_days ? `MA${source_algorithm.ma_window_days} 线上方` : "--"), metricCard("行业合计", valueText(summary.industry_sum_score, 0), `${summary.industry_count ?? industries.length} 个行业`), metricCard("涨跌停", `${intText(summary.limit_up_count)} / ${intText(summary.limit_down_count)}`, "涨停 / 跌停")])}${marketHeatmapCard(heatmap_history)}<section class="main-grid">${panel({ title: "宽度状态", kicker: "Breadth Score", span: "span-4", body: scoreBlock(summary.score, summary.label || "宽度", "宽度越高，说明行情扩散越充分；低宽度上涨更依赖少数权重或主题。", metrics.map((item) => ({ name: item.name, value: item.value, unit: item.unit, detail: item.detail })), "var(--positive)") })}${panel({ title: "算法口径", kicker: "Source Logic", span: "span-4", body: detailGrid([{ label: "来源", value: source_algorithm.name || "--", detail: source_algorithm.source_file || "" }, { label: "股票池", value: source_algorithm.universe || "--", detail: source_algorithm.industry_standard || "" }, { label: "公式", value: source_algorithm.formula || "--", detail: source_algorithm.ma_window_days ? `MA${source_algorithm.ma_window_days}` : "" }, { label: "输出", value: source_algorithm.output_table || "--", detail: `回看 ${source_algorithm.lookback_days || "--"} 个交易日` }]) })}${panel({ title: "涨跌分布", kicker: "Distribution", span: "span-4", body: barList(distribution.map((item) => ({ name: item.bucket, value: item.count, unit: "", detail: "股票数" })), { max: maxCount }) })}${panel({ title: "行业宽度热力", kicker: "Industry Width", span: "span-8", body: heatmap(industries, "width_pct", "宽度") })}${panel({ title: "风格扩散", kicker: "Style", span: "span-4", body: barList(style) })}</section>`;
}

function renderSentimentLineChart(series = [], warningLine = 0.15) {
  if (!series.length) return `<div class="empty-state">暂无趋势数据</div>`;
  const values = series.map((item) => Number(item.value || 0));
  return `<div class="chart-shell">${sparkline(values, values[values.length - 1], 1120, 320)}</div>`;
}

function renderSentiment(payload) {
  const { summary = {}, gauges = [], topics = [], flows = [], warnings = [], brilliant_volatility = {}, brilliant_series = [], surge_events = [], source_algorithm = {}, latest_snapshot = {}, sentiment_trend = [] } = payload.data || {};
  const gaugeInput = summary.temperature !== undefined ? summary.temperature : latest_snapshot.sentiment_value !== undefined ? Number(latest_snapshot.sentiment_value) * 100 : null;
  dom.app.innerHTML = `${sentimentGauge(gaugeInput)}<section class="main-grid">${panel({ title: "情绪趋势图", kicker: "Trend", span: "span-8", body: renderSentimentLineChart(sentiment_trend, latest_snapshot.warning_line ?? .15) })}${panel({ title: "情绪状态", kicker: "Sentiment Score", span: "span-4", body: scoreBlock(summary.score, summary.label || "情绪", "过热时降低追涨权重，低迷时优先等待宽度修复。", gauges, "var(--warning)") })}${panel({ title: "1 分钟耀眼波动", kicker: source_algorithm.name || "Brilliant Volatility", span: "span-4", tools: pill(brilliant_volatility.intraday_signal || "--", "warning"), body: detailGrid([{ label: "跟踪标的", value: `${brilliant_volatility.name || "--"} ${brilliant_volatility.symbol || ""}`, detail: `收盘 ${valueText(brilliant_volatility.close, 3)}` }, { label: "日耀眼波动", value: valueWithUnit(brilliant_volatility.daily_brilliant_vol, "%", 2), detail: brilliant_volatility.signal_detail || "" }, { label: "激增次数", value: `${intText(brilliant_volatility.surge_count)} 次`, detail: `最后 ${brilliant_volatility.last_surge_time || "--"}` }, { label: "窗口", value: brilliant_volatility.window || source_algorithm.time_window || "--", detail: source_algorithm.surge_rule || "" }]) })}${panel({ title: "题材热度", kicker: "Topics", span: "span-8", body: heatmap(topics, "heat", "热度") })}${panel({ title: "激增事件", kicker: "Intraday Surge", span: "span-6", body: table(["时间", "量增倍数", "窗口波动", "价格变化"], surge_events.map((row) => `<tr><td class="mono">${escapeHtml(row.time)}</td><td>${valueText(row.volume_increase_ratio, 2)}x</td><td>${valueWithUnit(row.return_std, "%", 2)}</td><td class="${toneClassByValue(row.price_change_pct)}">${pctText(row.price_change_pct)}</td></tr>`), 620) })}${panel({ title: "资金流", kicker: "Flows", span: "span-6", body: table(["指标", "数值", "说明"], flows.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${valueWithUnit(row.value, row.unit, 2)}</td><td>${escapeHtml(row.detail)}</td></tr>`), 620) })}${panel({ title: "提醒", kicker: "Warnings", span: "span-6", body: alertList(warnings) })}</section>`;
}

function renderMacro(payload) {
  const { summary = {}, rates = [], fx = [], risk_assets = [], calendar = [], observations = [] } = payload.data || {};
  dom.app.innerHTML = `${pageDecisionBrief({ kicker: "Macro Regime", title: summary.title || `宏观环境 ${summary.label || "--"}`, detail: summary.detail || `中国 10Y ${valueWithUnit(summary.ten_year_yield_pct, "%")}，USD/CNH ${valueText(summary.usd_cnh, 2)}，股债利差 ${valueWithUnit(summary.equity_bond_spread_pct, "%")}。`, tone: summary.tone || "blue", metrics: [{ label: "风险偏好", value: valueWithUnit(summary.risk_preference_score, "/100", 0) }, { label: "中国 10Y", value: valueWithUnit(summary.ten_year_yield_pct, "%") }, { label: "USD/CNH", value: valueText(summary.usd_cnh, 2) }, { label: "股债利差", value: valueWithUnit(summary.equity_bond_spread_pct, "%") }] })}<section class="main-grid">${panel({ title: "利率", kicker: "Rates", span: "span-6", body: table(["指标", "数值", "变化"], rates.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${valueWithUnit(row.value, row.unit, 2)}</td><td class="${toneClassByValue(-row.change_bp)}">${Number(row.change_bp) > 0 ? "+" : ""}${valueText(row.change_bp, 1)}bp</td></tr>`), 620) })}${panel({ title: "风险资产", kicker: "Risk Assets", span: "span-6", body: table(["资产", "点位", "涨跌"], risk_assets.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${valueText(row.value, 2)}</td><td class="${toneClassByValue(row.change_pct)}">${pctText(row.change_pct)}</td></tr>`), 620) })}${panel({ title: "外汇", kicker: "FX", span: "span-4", body: barList(fx.map((row) => ({ name: row.name, value: row.value, detail: `变化 ${pctText(row.change_pct)}` })), { max: 110 }) })}${panel({ title: "日历", kicker: "Calendar", span: "span-4", body: table(["日期", "事件", "重要性"], calendar.map((row) => `<tr><td>${escapeHtml(row.date)}</td><td>${escapeHtml(row.event)}</td><td>${tag(row.importance === "high" ? "高" : "中", row.importance === "high" ? "warning" : "blue")}</td></tr>`), 560) })}${panel({ title: "观察", kicker: "Observations", span: "span-4", body: alertList(observations) })}</section>`;
}

function updateShell(meta, mode, apiError = null) {
  const sourceText = mode === "cache" ? "Cached API" : "Live API";
  dom.apiMode.textContent = sourceText;
  dom.connectionBadge.textContent = sourceText;
  dom.connectionBadge.className = `connection-badge live`;
  dom.runSummary.textContent = `${meta.run_id || "--"} / ${formatDateTime(meta.as_of)}`;
  dom.lastUpdated.textContent = `最近刷新 ${formatDateTime(new Date().toISOString())}`;
}

function showError(error) {
  const message = error?.message || "接口请求失败";
  dom.connectionBadge.textContent = "获取失败";
  dom.connectionBadge.className = "connection-badge error";
  dom.apiMode.textContent = "Error";
  dom.runSummary.textContent = message;
  dom.app.innerHTML = `<div class="error-state"><strong>获取失败</strong><span>${escapeHtml(message)}</span><button class="ghost-button" type="button" data-retry>重新获取</button></div>`;
  dom.app.querySelector("[data-retry]")?.addEventListener("click", () => dom.refreshButton?.click());
}

function hongKongTimeParts(date) {
  const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Hong_Kong", weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  const weekdayMap = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  return { day: weekdayMap[values.weekday], hour: Number(values.hour), minute: Number(values.minute) };
}

function marketSessionLabel(date) {
  const { day, hour, minute } = hongKongTimeParts(date);
  const minutes = hour * 60 + minute;
  const isWeekday = day >= 1 && day <= 5;
  const morning = minutes >= 9 * 60 + 30 && minutes <= 11 * 60 + 30;
  const afternoon = minutes >= 13 * 60 && minutes <= 15 * 60;
  if (!isWeekday) return "休市";
  if (morning || afternoon) return "盘中";
  if (minutes > 11 * 60 + 30 && minutes < 13 * 60) return "午间";
  if (minutes > 15 * 60) return "已收盘";
  return "待开盘";
}

function updateClock() {
  const now = new Date();
  dom.marketDate.textContent = `${marketSessionLabel(now)} ${new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Hong_Kong", month: "2-digit", day: "2-digit", weekday: "short" }).format(now)}`;
  dom.marketClock.textContent = new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Hong_Kong", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(now);
}

function setActiveNav(page) {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    const active = link.dataset.nav === page;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
  });
}

function showLoading() {
  dom.connectionBadge.textContent = "刷新中";
  dom.connectionBadge.className = "connection-badge";
}

function shouldPauseAutoRefresh(page) {
  if (page !== "watchlist") return false;
  const active = document.activeElement;
  const addPanel = document.querySelector("[data-watch-add-panel]");
  const addForm = document.querySelector("[data-watch-add-form]");
  const search = document.querySelector("[data-watch-search]");
  return Boolean(
    addPanel?.classList.contains("open")
      || addForm?.contains(active)
      || (search && search.value.trim())
  );
}

async function init() {
  installShell();
  const page = document.body.dataset.page || "overview";
  const config = PAGE_CONFIG[page] || PAGE_CONFIG.overview;
  let refreshing = false;

  updatePageHeading(page);
  setActiveNav(page);
  updateClock();
  setInterval(updateClock, 1000);

  async function refresh(options = {}) {
    if (refreshing) return;
    if (options.background && shouldPauseAutoRefresh(page)) return;
    refreshing = true;
    showLoading();
    try {
      const { payload, mode } = await fetchPayload(config);
      config.render(payload);
      updateShell(payload.meta || {}, mode);
    } catch (error) {
      showError(error);
    } finally {
      refreshing = false;
    }
  }

  dom.refreshButton.addEventListener("click", refresh);
  await refresh();
  setInterval(() => refresh({ background: true }), config.refreshMs || 60_000);
}

init();
