import { PAGE_MODULES } from "./pages/index.js";

const API_BASE = window.QUANT_API_BASE || "";

const PAGE_CONFIG = {
  overview: { endpoint: "/api/v1/dashboard/overview", refreshMs: 30_000, render: renderOverview },
  watchlist: { endpoint: "/api/v1/watchlist", refreshMs: 15_000, render: renderWatchlist },
  picks: { endpoint: "/api/v1/strategies/picks", refreshMs: 300_000, render: renderPicks },
  holdings: { endpoint: "/api/v1/portfolio/holdings", refreshMs: 30_000, render: renderHoldings },
  performance: { endpoint: buildPerformanceEndpoint, refreshMs: 30_000, render: renderPerformance },
  strategy: { endpoint: buildStrategyEndpoint, refreshMs: 300_000, render: renderStrategyHub },
  crypto: { endpoint: "/api/v1/strategies/crypto-funding", refreshMs: 30_000, render: renderCryptoFunding },
  etf: { endpoint: "/api/v1/strategies/etf", refreshMs: 300_000, render: renderEtf },
  "small-cap": { endpoint: "/api/v1/strategies/small-cap", refreshMs: 300_000, render: renderSmallCap },
  breadth: { endpoint: "/api/v1/market/breadth", refreshMs: 60_000, render: renderBreadth },
  sentiment: { endpoint: "/api/v1/market/sentiment", refreshMs: 60_000, render: renderSentiment },
  macro: { endpoint: "/api/v1/macro", refreshMs: 3_600_000, render: renderMacro },
};

const PAGE_LOADERS = {
  overview: () => import("./pages/overview.js"),
  watchlist: () => import("./pages/watchlist.js"),
  picks: () => import("./pages/picks.js"),
  holdings: () => import("./pages/holdings.js"),
  performance: () => import("./pages/performance.js"),
  strategy: () => import("./pages/strategy.js"),
  crypto: () => import("./pages/crypto.js"),
  breadth: () => import("./pages/breadth.js"),
  sentiment: () => import("./pages/sentiment.js"),
  macro: () => import("./pages/macro.js"),
};

Object.entries(PAGE_MODULES).forEach(([page, module]) => {
  if (!PAGE_CONFIG[page]) return;
  PAGE_CONFIG[page] = { ...module.config, ...PAGE_CONFIG[page] };
});

const PAGE_META = {
  overview: ["Market Overview", "市场总览"],
  watchlist: ["Watchlist", "自选股"],
  picks: ["Daily Picks", "今日选股"],
  holdings: ["Portfolio", "当前持仓"],
  performance: ["Performance", "历史收益"],
  strategy: ["Quant Strategy", "量化策略"],
  crypto: ["Crypto Funding", "加密货币策略"],
  etf: ["ETF Strategy", "ETF 策略"],
  "small-cap": ["Small Cap Strategy", "小盘股策略"],
  breadth: ["Market Breadth", "市场宽度"],
  sentiment: ["Retail Sentiment", "散户情绪"],
  macro: ["Macro Reference", "宏观指标"],
};

const initialQuery = new URLSearchParams(window.location.search);

const pageState = {
  picks: { strategy: initialQuery.get("strategy") || null, date: initialQuery.get("date") || null, latestDate: null },
  strategy: { strategyId: initialQuery.get("strategy_id") || "" },
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
const STRATEGY_LOG_DISPLAY_LIMIT = 1000;

const performanceState = { strategy: initialQuery.get("strategy") || "", benchmark: "CSI300", range: "1Y", from: "", to: "" };
let activePage = document.body.dataset.page || "overview";

function formatDateParam(date) {
  return date.toISOString().slice(0, 10);
}

function addMonths(date, months) {
  const next = new Date(date);
  next.setUTCMonth(next.getUTCMonth() + months);
  return next;
}

function syncPerformanceRange(range) {
  performanceState.range = range;
  const today = new Date();
  performanceState.to = formatDateParam(today);
  if (range === "3M") {
    performanceState.from = formatDateParam(addMonths(today, -3));
  } else if (range === "1Y") {
    performanceState.from = formatDateParam(addMonths(today, -12));
  } else {
    performanceState.from = "";
    performanceState.to = "";
  }
}

function buildPerformanceEndpoint() {
  const params = new URLSearchParams();
  if (performanceState.strategy) params.set("strategy", performanceState.strategy);
  if (performanceState.benchmark) params.set("benchmark", performanceState.benchmark);
  if (performanceState.from) params.set("from", performanceState.from);
  if (performanceState.to) params.set("to", performanceState.to);
  const query = params.toString();
  return `/api/v1/performance${query ? `?${query}` : ""}`;
}

function buildStrategyEndpoint() {
  return pageState.strategy.strategyId
    ? `/api/v1/quant/strategies/${encodeURIComponent(pageState.strategy.strategyId)}`
    : "/api/v1/quant/strategies";
}

async function refreshPerformance() {
  if (activePage !== "performance") return;
  showLoading();
  try {
    const { payload, mode } = await fetchPayload(PAGE_CONFIG.performance);
    renderPerformance(payload);
    updateShell(payload.meta || {}, mode);
  } catch (error) {
    if (!renderCachedFallback(PAGE_CONFIG.performance, error)) showError(error);
  }
}

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

function redirectToLogin() {
  if (window.location.pathname.endsWith("/login.html")) return;
  const next = `${window.location.pathname}${window.location.search}`;
  window.location.href = `login.html?next=${encodeURIComponent(next)}`;
}

async function requestJson(url) {
  const response = await fetch(withCacheBust(url), { cache: "no-store", credentials: "same-origin", headers: { Accept: "application/json" } });
  if (response.status === 401) {
    redirectToLogin();
    throw new Error("401 Unauthorized");
  }
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function queryString(params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== "") search.set(key, value);
  });
  const text = search.toString();
  return text ? `?${text}` : "";
}

function picksQueryParams() {
  return { strategy: pageState.picks.strategy, date: pageState.picks.date };
}

function pageEndpoint(config) {
  const endpoint = typeof config.endpoint === "function" ? config.endpoint() : config.endpoint;
  if (endpoint === "/api/v1/strategies/picks") return `${endpoint}${queryString(picksQueryParams())}`;
  return endpoint;
}

async function sendJson(path, options = {}) {
  const response = await fetch(joinUrl(API_BASE, path), {
    cache: "no-store",
    credentials: "same-origin",
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    if (response.status === 401) {
      redirectToLogin();
    }
    let detail = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      detail = payload.detail || detail;
    } catch (error) {
      // Keep the original HTTP status when the backend response is not JSON.
    }
    const requestError = new Error(detail);
    requestError.status = response.status;
    throw requestError;
  }
  return response.json();
}

function actionHeaders() {
  const token = window.localStorage?.getItem("quant_action_token") || window.QUANT_ACTION_TOKEN || "";
  return token ? { "X-Action-Token": token } : {};
}

function actionStatusText(error) {
  if (error?.status === 403 || String(error?.message || "").includes("权限不足")) return "权限不足：请配置操作令牌";
  return error?.message || "操作失败";
}

function apiErrorDetail(error) {
  const detail = error?.message || "";
  if (typeof detail === "string") return detail;
  try {
    return JSON.stringify(detail);
  } catch (stringifyError) {
    return "操作失败";
  }
}

function setActionState(button, state, message = "") {
  if (!button) return;
  const idleText = button.dataset.idleText || button.textContent.trim();
  button.dataset.idleText = idleText;
  const statusNode = button.closest(".action-cell, .signal-card, .strategy-toolbar")?.querySelector("[data-action-status]");
  button.disabled = state === "loading";
  button.classList.toggle("is-loading", state === "loading");
  if (state === "loading") button.textContent = "处理中...";
  if (state === "success") button.textContent = "已完成";
  if (state === "error" || state === "forbidden") button.textContent = state === "forbidden" ? "权限不足" : "失败";
  if (state === "idle") button.textContent = idleText;
  if (statusNode) {
    statusNode.textContent = message;
    statusNode.className = `action-status ${state}`;
  }
}

async function postAction(button, path, body = {}, successMessage = "操作成功") {
  setActionState(button, "loading", "正在提交...");
  try {
    const payload = await sendJson(path, { method: "POST", headers: actionHeaders(), body: JSON.stringify(body) });
    setActionState(button, "success", payload.data?.message || successMessage);
    return payload;
  } catch (error) {
    const state = error?.status === 403 ? "forbidden" : "error";
    setActionState(button, state, actionStatusText(error));
    return null;
  } finally {
    window.setTimeout(() => setActionState(button, "idle", ""), 3200);
  }
}

async function submitActionForm(form, path, body, successMessage = "操作成功") {
  const statusNode = form.querySelector("[data-action-status]");
  const button = form.querySelector("button[type='submit']");
  if (button) {
    button.disabled = true;
    button.dataset.idleText = button.dataset.idleText || button.textContent.trim();
    button.textContent = "提交中...";
  }
  if (statusNode) {
    statusNode.textContent = "正在提交...";
    statusNode.className = "action-status loading";
  }
  try {
    const payload = await sendJson(path, { method: "POST", headers: actionHeaders(), body: JSON.stringify(body) });
    if (statusNode) {
      statusNode.textContent = payload.data?.message || successMessage;
      statusNode.className = "action-status success";
    }
    return payload;
  } catch (error) {
    if (statusNode) {
      statusNode.textContent = actionStatusText(error);
      statusNode.className = `action-status ${error?.status === 403 ? "forbidden" : "error"}`;
    }
    return null;
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = button.dataset.idleText || "提交";
    }
  }
}

function readonlyNote(text = "只读展示") {
  return `<span class="readonly-note" title="该控件仅用于展示当前数据维度">${escapeHtml(text)}</span>`;
}

function queryParam(name) {
  return new URLSearchParams(window.location.search).get(name) || "";
}

function updateUrlQuery(params) {
  const url = new URL(window.location.href);
  Object.entries(params).forEach(([key, value]) => {
    if (value) url.searchParams.set(key, value);
    else url.searchParams.delete(key);
  });
  window.history.replaceState(null, "", url);
}

async function fetchPayload(config) {
  if (!config.endpoint) throw new Error("页面未配置数据接口");
  const payload = await requestJson(joinUrl(API_BASE, pageEndpoint(config)));
  const mode = payload.meta?.source === "cache" ? "cache" : "live";
  writeLastPayload(activePage, payload, mode);
  return { payload, mode };
}

function lastPayloadKey(page = activePage) {
  return `quant:lastPayload:${page}`;
}

function writeLastPayload(page, payload, mode) {
  try {
    window.localStorage?.setItem(lastPayloadKey(page), JSON.stringify({ payload, mode, savedAt: new Date().toISOString() }));
  } catch (error) {
    // localStorage can be unavailable in strict privacy modes; live rendering should continue.
  }
}

function readLastPayload(page = activePage) {
  try {
    const text = window.localStorage?.getItem(lastPayloadKey(page));
    if (!text) return null;
    const cached = JSON.parse(text);
    if (!cached?.payload || !cached.savedAt) return null;
    return cached;
  } catch (error) {
    try {
      window.localStorage?.removeItem(lastPayloadKey(page));
    } catch (removeError) {
      // Ignore cleanup failures and fall through to the normal error state.
    }
    return null;
  }
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

function secondsText(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const seconds = Math.max(0, Number(value));
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟`;
  return `${(seconds / 3600).toFixed(1)} 小时`;
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

function hkDateString(date = new Date()) {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function shiftDate(dateText, days) {
  const base = dateText && /^\d{4}-\d{2}-\d{2}$/.test(dateText) ? new Date(`${dateText}T00:00:00Z`) : new Date(`${hkDateString()}T00:00:00Z`);
  base.setUTCDate(base.getUTCDate() + days);
  return base.toISOString().slice(0, 10);
}

function pickStrategyValue(item) {
  if (item && typeof item === "object") return item.id || item.key || item.value || item.label || item.name || "";
  return item || "";
}

function pickStrategyLabel(item) {
  if (item && typeof item === "object") return item.label || item.name || item.id || item.key || "";
  return item || "";
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

function formatAxisDate(value, spanMs = 0) {
  if (!value && value !== 0) return "--";
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10);
  const options = spanMs > 370 * 24 * 60 * 60 * 1000
    ? { timeZone: "Asia/Hong_Kong", year: "2-digit", month: "2-digit" }
    : { timeZone: "Asia/Hong_Kong", month: "2-digit", day: "2-digit" };
  return new Intl.DateTimeFormat("zh-CN", options).format(date).replace(/\//g, "-");
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
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-4.2-4.2"/>',
    close: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    arrowLeft: '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    arrowRight: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
    download: '<path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/>',
    sector: '<path d="M4 6h7v7H4z"/><path d="M13 6h7v4h-7z"/><path d="M13 12h7v6h-7z"/><path d="M4 15h7v3H4z"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.chart}</svg>`;
}

function installShell() {
  const navItems = [
    ["overview", "index.html", "home", "市场总览"],
    ["watchlist", "watchlist.html", "star", "自选股"],
    ["picks", "picks.html", "picks", "今日选股"],
    ["strategy", "strategy.html", "bot", "量化策略"],
    ["holdings", "holdings.html", "portfolio", "持仓信息"],
    ["performance", "performance.html", "chart", "历史收益"],
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
      <span class="user-chip" id="userChip" hidden></span>
      <span class="connection-badge" id="connectionBadge">连接中</span>
      <div class="market-clock" aria-label="市场时间"><span id="marketDate">--</span><strong id="marketClock">--:--:--</strong></div>
      <button class="icon-button" id="refreshButton" type="button" title="刷新" aria-label="刷新">${icon("refresh")}</button>
      <button class="icon-button" id="logoutButton" type="button" title="退出登录" aria-label="退出登录">${icon("close")}</button>
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

async function installAuthShell() {
  try {
    const payload = await requestJson(joinUrl(API_BASE, "/api/v1/auth/session"));
    const data = payload.data || {};
    const userChip = document.querySelector("#userChip");
    if (userChip && data.authenticated && data.user) {
      userChip.hidden = false;
      userChip.textContent = data.user.display_name || data.user.username || "已登录";
    }
  } catch (error) {
    if (!String(error?.message || "").includes("401")) {
      console.warn("auth session check failed", error);
    }
  }
  document.querySelector("#logoutButton")?.addEventListener("click", async () => {
    try {
      await sendJson("/api/v1/auth/logout", { method: "POST", body: JSON.stringify({}) });
    } finally {
      window.location.href = "login.html";
    }
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
  if (Number(value) >= 75) return "rgba(40,121,90,0.16)";
  if (Number(value) >= 60) return "rgba(140,90,43,0.12)";
  if (Number(value) >= 45) return "rgba(176,109,24,0.13)";
  return "rgba(178,59,50,0.12)";
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

function pickRawMetrics(pick = {}) {
  const raw = pick.raw_metrics && typeof pick.raw_metrics === "object" ? pick.raw_metrics : {};
  const lowNear = Number(raw.low_near);
  const entry = Number(pick.entry_price ?? pick.entry);
  const maGapPct = Number.isFinite(Number(raw.ma_gap_pct))
    ? Number(raw.ma_gap_pct)
    : Number.isFinite(entry) && Number.isFinite(lowNear) && lowNear !== 0
    ? ((entry / lowNear) - 1) * 100
    : NaN;
  const thresholdPct = Number.isFinite(Number(raw.entry_threshold_pct))
    ? Number(raw.entry_threshold_pct)
    : 1.5 - Number(raw.index_ret_pct ?? NaN);
  const rows = [
    ["量比", Number.isFinite(Number(raw.vol_ratio)) ? `${fixedText(raw.vol_ratio, 2)}x` : "--"],
    ["个股涨幅", pctText(raw.ret_pct, 2)],
    ["沪深300", pctText(raw.index_ret_pct, 2)],
    ["入池阈值", Number.isFinite(thresholdPct) ? `>${fixedText(thresholdPct, 2)}%` : "--"],
    ["MA12", fixedText(raw.ma12, 2)],
    ["MA26", fixedText(raw.ma26, 2)],
    ["较低均线", fixedText(raw.low_near, 2)],
    ["均线偏离", Number.isFinite(maGapPct) ? pctText(maGapPct, 2) : "--"],
  ];
  return `<div class="raw-metric-grid">${rows.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>`;
}

function chartPoint(item, index) {
  const value = typeof item === "object" && item !== null
    ? Number(item.return_pct ?? item.value ?? item.net_value ?? item.equity)
    : Number(item);
  const nav = typeof item === "object" && item !== null
    ? Number(item.value ?? item.net_value ?? item.nav ?? item.equity)
    : NaN;
  const dateText = typeof item === "object" && item !== null ? item.date || item.trade_date || item.as_of || "" : "";
  const timestamp = dateText ? new Date(dateText).getTime() : NaN;
  return {
    value,
    nav: Number.isFinite(nav) ? nav : null,
    date: dateText ? String(dateText).slice(0, 10) : "",
    time: Number.isNaN(timestamp) ? null : timestamp,
    index,
    dayReturn: typeof item === "object" && item !== null ? Number(item.day_return_pct ?? item.daily_return_pct ?? item.period_return_pct) : NaN,
    totalValue: typeof item === "object" && item !== null ? Number(item.total_value) : NaN,
    cash: typeof item === "object" && item !== null ? Number(item.cash) : NaN,
    positionsMarketValue: typeof item === "object" && item !== null ? Number(item.positions_market_value) : NaN,
    source: typeof item === "object" && item !== null ? String(item.source || "") : "",
    frequency: typeof item === "object" && item !== null ? String(item.frequency || "") : "",
  };
}

function chartPointDayReturn(points, index) {
  const point = points[index];
  if (!point) return null;
  if (Number.isFinite(point.dayReturn)) return point.dayReturn;
  const previous = points[index - 1];
  if (!previous) return null;
  if (Number.isFinite(point.nav) && Number.isFinite(previous.nav) && previous.nav !== 0) return (point.nav / previous.nav - 1) * 100;
  if (Number.isFinite(point.value) && Number.isFinite(previous.value)) return point.value - previous.value;
  return null;
}

function chartMoneyText(value) {
  return Number.isFinite(value) ? `¥${intText(value)}` : "--";
}

function chartPointTooltip(point, points, index, seriesLabel) {
  const dayReturn = chartPointDayReturn(points, index);
  const dayReturnClass = dayReturn === null ? "tone-neutral" : toneClassByValue(dayReturn);
  const rows = [
    ["当日", dayReturn === null ? "--" : pctText(dayReturn), dayReturnClass],
    ["净值", point.nav === null ? "--" : valueText(point.nav, 4), ""],
    ["总资产", chartMoneyText(point.totalValue), ""],
    ["现金", chartMoneyText(point.cash), ""],
    ["持仓", chartMoneyText(point.positionsMarketValue), ""],
  ];
  return `
    <g class="chart-point-hit" tabindex="0" role="listitem" aria-label="${escapeHtml(point.date || `第 ${index + 1} 点`)} ${escapeHtml(seriesLabel)}累计收益 ${escapeHtml(pctText(point.value))}">
      <line class="chart-hover-line" x1="${point.x.toFixed(1)}" x2="${point.x.toFixed(1)}" y1="${point.chartTop.toFixed(1)}" y2="${point.chartBottom.toFixed(1)}"></line>
      <rect class="chart-point-target" x="${point.hitX.toFixed(1)}" y="${point.chartTop.toFixed(1)}" width="${point.hitWidth.toFixed(1)}" height="${(point.chartBottom - point.chartTop).toFixed(1)}" rx="0"></rect>
      <circle class="chart-point-dot" cx="${point.x.toFixed(1)}" cy="${point.y.toFixed(1)}" r="3.4"></circle>
      <foreignObject class="chart-tooltip-fo" x="${point.tooltipX.toFixed(1)}" y="${point.tooltipY.toFixed(1)}" width="190" height="146">
        <div class="chart-tooltip" xmlns="http://www.w3.org/1999/xhtml">
          <div class="chart-tooltip-head"><span>${escapeHtml(point.date || `第 ${index + 1} 点`)}</span><b>${escapeHtml(seriesLabel)}</b></div>
          <div class="chart-tooltip-main ${toneClassByValue(point.value)}">${escapeHtml(pctText(point.value))}<small>累计</small></div>
          ${rows.map(([label, value, className]) => `<div class="chart-tooltip-row"><span>${escapeHtml(label)}</span><b class="${escapeHtml(className || "")}">${escapeHtml(value)}</b></div>`).join("")}
        </div>
      </foreignObject>
    </g>
  `;
}

function niceDomain(values) {
  const valid = values.filter((value) => Number.isFinite(value));
  if (!valid.length) return { min: -5, max: 5, ticks: [-5, -2.5, 0, 2.5, 5] };
  const rawMin = Math.min(...valid, 0);
  const rawMax = Math.max(...valid, 0);
  const rawSpan = rawMax - rawMin || Math.max(Math.abs(rawMax), 1);
  const paddedMin = rawMin - rawSpan * 0.1;
  const paddedMax = rawMax + rawSpan * 0.1;
  const targetTicks = 5;
  const roughStep = (paddedMax - paddedMin) / Math.max(1, targetTicks - 1);
  const power = 10 ** Math.floor(Math.log10(Math.max(roughStep, 0.0001)));
  const step = [1, 2, 5, 10].map((unit) => unit * power).find((candidate) => roughStep <= candidate) || power * 10;
  const min = Math.floor(paddedMin / step) * step;
  const max = Math.ceil(paddedMax / step) * step;
  const tickCount = Math.round((max - min) / step);
  const ticks = Array.from({ length: tickCount + 1 }, (_, index) => Number((min + step * index).toFixed(6)));
  return { min, max, ticks };
}

function equityChart(series, benchmark = [], options = {}) {
  const points = Array.isArray(series) ? series.map(chartPoint).filter((point) => Number.isFinite(point.value)) : [];
  if (points.length < 2) return `<div class="empty-state">暂无曲线数据</div>`;
  const benchmarkPoints = Array.isArray(benchmark) ? benchmark.map(chartPoint).filter((point) => Number.isFinite(point.value)) : [];
  const activeBenchmark = benchmarkPoints.length > 1 ? benchmarkPoints : [];
  const width = 1040;
  const height = 340;
  const pad = { top: 28, right: 78, bottom: 50, left: 70 };
  const allPoints = [...points, ...activeBenchmark];
  const values = allPoints.map((point) => point.value);
  const { min, max, ticks } = niceDomain(values);
  const timeMode = allPoints.length > 1 && allPoints.every((point) => point.time !== null);
  const minTime = timeMode ? Math.min(...allPoints.map((point) => point.time)) : 0;
  const maxTime = timeMode ? Math.max(...allPoints.map((point) => point.time)) : points.length - 1;
  const spanTime = Math.max(1, maxTime - minTime);
  const tickPositions = timeMode
    ? [0, 0.25, 0.5, 0.75, 1].map((ratio) => minTime + spanTime * ratio)
    : [0, 0.25, 0.5, 0.75, 1].map((ratio) => Math.round((points.length - 1) * ratio));
  const toPoint = (point, fallbackIndex = 0, fallbackLength = points.length) => {
    const xRatio = timeMode
      ? ((point.time ?? minTime) - minTime) / spanTime
      : fallbackIndex / Math.max(1, fallbackLength - 1);
    const x = pad.left + xRatio * (width - pad.left - pad.right);
    const y = pad.top + (1 - (point.value - min) / (max - min || 1)) * (height - pad.top - pad.bottom);
    return [x, y];
  };
  const tooltipWidth = 190;
  const tooltipHeight = 146;
  const pointPositions = points.map((point, index) => {
    const [x, y] = toPoint(point, index, points.length);
    const previousX = index > 0 ? toPoint(points[index - 1], index - 1, points.length)[0] : pad.left;
    const nextX = index < points.length - 1 ? toPoint(points[index + 1], index + 1, points.length)[0] : width - pad.right;
    const hitX = index === 0 ? pad.left : (previousX + x) / 2;
    const hitRight = index === points.length - 1 ? width - pad.right : (x + nextX) / 2;
    const tooltipX = Math.min(Math.max(pad.left + 4, x + 14), width - pad.right - tooltipWidth);
    const tooltipY = Math.min(Math.max(pad.top, y - tooltipHeight - 10), height - pad.bottom - tooltipHeight);
    return { ...point, x, y, hitX, hitWidth: Math.max(3, hitRight - hitX), tooltipX, tooltipY, chartTop: pad.top, chartBottom: height - pad.bottom };
  });
  const path = (items) => items.map((point, index) => {
    const [x, y] = toPoint(point, index, items.length);
    return `${index ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");
  const lastPoint = points[points.length - 1];
  const firstPoint = points[0];
  const lastBenchmarkPoint = activeBenchmark[activeBenchmark.length - 1];
  const lastSeriesPosition = toPoint(lastPoint, points.length - 1, points.length);
  const area = `${path(points)} L${lastSeriesPosition[0].toFixed(1)} ${height - pad.bottom} L${pad.left} ${height - pad.bottom} Z`;
  const zeroY = toPoint({ value: 0, time: timeMode ? minTime : null }, 0, points.length)[1];
  const seriesLabel = options.seriesLabel || "策略";
  const benchmarkLabel = options.benchmarkLabel || "基准";
  const periodLabel = firstPoint.date && lastPoint.date ? `${firstPoint.date} - ${lastPoint.date}` : `${intText(points.length)} 点`;
  const yRangeLabel = `${pctText(min, 1)} 至 ${pctText(max, 1)}`;

  return `
    <div class="chart-panel">
      <div class="chart-summary-bar">
        <div><span>${escapeHtml(seriesLabel)}</span><strong class="${toneClassByValue(lastPoint.value)}">${pctText(lastPoint.value)}</strong><small>${escapeHtml(firstPoint.date || "起点")} → ${escapeHtml(lastPoint.date || "最新")}</small></div>
        ${activeBenchmark.length ? `<div><span>${escapeHtml(benchmarkLabel)}</span><strong class="${toneClassByValue(lastBenchmarkPoint.value)}">${pctText(lastBenchmarkPoint.value)}</strong><small>${intText(activeBenchmark.length)} 个基准点</small></div>` : ""}
        <div><span>横轴</span><strong>${escapeHtml(periodLabel)}</strong><small>日期范围</small></div>
        <div><span>纵轴</span><strong>${escapeHtml(yRangeLabel)}</strong><small>收益率区间</small></div>
      </div>
      <svg class="equity-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="历史收益曲线">
        <defs><linearGradient id="equityFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="rgba(140,90,43,.14)"/><stop offset="100%" stop-color="rgba(140,90,43,0)"/></linearGradient></defs>
        <line class="axis-line" x1="${pad.left}" x2="${pad.left}" y1="${pad.top}" y2="${height - pad.bottom}"></line>
        <line class="axis-line" x1="${pad.left}" x2="${width - pad.right}" y1="${height - pad.bottom}" y2="${height - pad.bottom}"></line>
        ${ticks.map((tick) => {
          const y = toPoint({ value: tick, time: timeMode ? minTime : null }, 0, points.length)[1];
          return `<line class="chart-grid-line" x1="${pad.left}" x2="${width - pad.right}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/><text class="axis-tick y-tick" x="${pad.left - 12}" y="${(y + 4).toFixed(1)}">${pctText(tick, Math.abs(tick) < 10 ? 1 : 0)}</text>`;
        }).join("")}
        ${tickPositions.map((tick) => {
          const ratio = timeMode ? (tick - minTime) / spanTime : tick / Math.max(1, points.length - 1);
          const x = pad.left + ratio * (width - pad.left - pad.right);
          const label = timeMode ? formatAxisDate(tick, spanTime) : intText(tick + 1);
          return `<line class="chart-grid-line x-grid" x1="${x.toFixed(1)}" x2="${x.toFixed(1)}" y1="${pad.top}" y2="${height - pad.bottom}"/><text class="axis-tick x-tick" x="${x.toFixed(1)}" y="${height - pad.bottom + 24}">${escapeHtml(label)}</text>`;
        }).join("")}
        <text class="axis-label chart-y-label" x="18" y="${pad.top + 4}">收益率</text>
        <text class="axis-label chart-x-label" x="${width - pad.right}" y="${height - 16}">日期</text>
        <line class="zero-line" x1="${pad.left}" x2="${width - pad.right}" y1="${zeroY}" y2="${zeroY}"></line>
        <path class="equity-area" d="${area}"></path>
        <path class="equity-line" d="${path(points)}"></path>
        ${activeBenchmark.length ? `<path class="benchmark-line" d="${path(activeBenchmark)}"></path>` : ""}
        <g class="chart-points" role="list" aria-label="${escapeHtml(seriesLabel)}每日收益点">
          ${pointPositions.map((point, index) => chartPointTooltip(point, pointPositions, index, seriesLabel)).join("")}
        </g>
        <circle class="chart-last-dot" cx="${lastSeriesPosition[0].toFixed(1)}" cy="${lastSeriesPosition[1].toFixed(1)}" r="3.8"></circle>
      </svg>
      <div class="chart-legend">
        <span><i class="legend-swatch strategy"></i>${escapeHtml(seriesLabel)}</span>
        ${activeBenchmark.length ? `<span><i class="legend-swatch benchmark"></i>${escapeHtml(benchmarkLabel)}</span>` : ""}
        <span>点数 ${intText(points.length)}${activeBenchmark.length ? ` / 基准 ${intText(activeBenchmark.length)}` : ""}</span>
      </div>
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
        <span>昨日 <strong class="${toneClassByValue(dayDiff)}">${dayDiff === null ? "--" : `${dayDiff > 0 ? "+" : "-"}${intText(Math.abs(dayDiff))}`}</strong></span>
        <span>上周 <strong class="${toneClassByValue(weekDiff)}">${weekDiff === null ? "--" : `${weekDiff > 0 ? "+" : "-"}${intText(Math.abs(weekDiff))}`}</strong></span>
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
          const cellColor = hasPeriodReturn ? heatmapScale(change) : "#8c877d";
          return `<div class="treemap-cell ${cellTone}" style="grid-column: span ${weight}; grid-row: span ${row}; --cell:${cellColor};" title="${escapeHtml(cell.market_label || "")} ${escapeHtml(cell.name)} / ${escapeHtml(activeTimeframe)} ${escapeHtml(changeLabel)} / volume ${intText(cell.volume)}"><span class="sector-float">${escapeHtml(cell.market_label || "")} · ${escapeHtml(cell.sector)}</span><strong>${escapeHtml(title)}</strong><small>${escapeHtml(subtitle || "")}</small><em>${escapeHtml(changeLabel)}</em></div>`;
        }).join("") : `<div class="empty-state treemap-empty">暂无热力图数据</div>`}
      </div>
    </section>
  `;
}

function heatmapScale(value) {
  const number = Number(value);
  if (number <= -2) return "#a33a31";
  if (number < 0) return "#b75b4f";
  if (number === 0) return "#8c877d";
  if (number < 2) return "#4f8a68";
  return "#28795a";
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
    tools: `<a class="panel-link" href="watchlist.html">管理</a>`,
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
      return `<article class="sector-card ${perf === best ? "best" : perf === worst ? "worst" : ""}"><span class="sector-icon">${icon("sector")}</span><small>${escapeHtml(item.name)}</small><strong class="${toneClassByValue(perf)}">${pctText(perf)}</strong>${rangeBar(50 + perf / 3 * 50, toneByValue(perf))}<div><span>上涨 ${intText(item.up_count)} stocks</span><span>下跌 ${intText(item.down_count)} stocks</span></div></article>`;
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
          <label class="search-input"><span>${icon("search")}</span><input type="search" placeholder="搜索股票 / ticker" data-watch-search /></label>
          <div class="toolbar"><select><option>全部分组</option></select><select><option>按涨跌幅</option></select><button class="primary-button" type="button" data-add-watch>添加股票</button></div>
        </div>
        <div class="watch-add-panel" data-watch-add-panel>
          <form class="watch-add-form" data-watch-add-form>
            <label class="span-2"><span>操作令牌</span><input name="action_token" type="password" autocomplete="off" placeholder="可选；填写后保存到本机浏览器" /></label>
            <label><span>市场</span><select name="market_region"><option value="cn">A股</option><option value="us">美股</option></select></label>
            <label><span>代码</span><input name="symbol" autocomplete="off" placeholder="600519 / NVDA" required /></label>
            <label><span>名称</span><input name="name" autocomplete="off" placeholder="可选" /></label>
            <label><span>分组</span><input name="sector" autocomplete="off" placeholder="例如 AI 链" /></label>
            <label class="checkbox-field"><input type="checkbox" name="is_personal_holding" value="true" data-watch-personal-toggle /><span>真实持有</span></label>
            <label data-watch-personal-field><span>持仓金额</span><input name="personal_amount" inputmode="decimal" placeholder="例如 50000" /></label>
            <label data-watch-personal-field><span>持仓数量</span><input name="quantity" inputmode="decimal" placeholder="可选" /></label>
            <button class="primary-button" type="submit">保存</button>
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
        <div class="inline-between"><div><p class="panel-kicker">Selected Stock</p><h2>${escapeHtml(selected.symbol)}</h2><span>${escapeHtml(selected.name)}</span></div><button class="icon-button" type="button" aria-label="关闭详情">${icon("close")}</button></div>
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

function watchlistRefreshMessage(payload, fallback = "已保存，行情稍后刷新") {
  const refreshError = payload?.data?.refresh_error || payload?.meta?.warning;
  if (payload?.data?.personal_holding) return payload.data.refresh_error ? fallback : "已保存到自选和个人持仓";
  return refreshError ? fallback : "";
}

function showWatchlistRefreshMessage(message, tone = "") {
  if (!message) return;
  const panel = document.querySelector("[data-watch-add-panel]");
  panel?.classList.add("open");
  setWatchlistStatus(message, tone);
}

function bindWatchlistInteractions() {
  const panelNode = document.querySelector("[data-watch-add-panel]");
  const personalToggle = document.querySelector("[data-watch-personal-toggle]");
  const syncPersonalFields = () => {
    const active = Boolean(personalToggle?.checked);
    document.querySelectorAll("[data-watch-personal-field]").forEach((node) => {
      node.classList.toggle("is-muted", !active);
      node.querySelector("input")?.toggleAttribute("disabled", !active);
    });
  };
  syncPersonalFields();
  personalToggle?.addEventListener("change", syncPersonalFields);
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
    const token = String(formData.get("action_token") || "").trim();
    const isPersonalHolding = formData.get("is_personal_holding") === "true";
    if (token) window.localStorage?.setItem("quant_action_token", token);
    if (isPersonalHolding) {
      body.is_personal_holding = true;
      body.personal_amount = String(formData.get("personal_amount") || "").trim();
      body.quantity = String(formData.get("quantity") || "").trim();
      body.portfolio_type = "personal";
    }
    if (!body.symbol) {
      setWatchlistStatus("请先输入股票代码", "negative");
      return;
    }
    if (isPersonalHolding && !body.personal_amount && !body.quantity) {
      setWatchlistStatus("真实持有至少需要填写持仓金额或持仓数量", "negative");
      return;
    }
    setWatchlistStatus("正在保存并获取行情...");
    form.querySelector("button[type='submit']")?.setAttribute("disabled", "disabled");
    try {
      const payload = await sendJson("/api/v1/watchlist", { method: "POST", headers: actionHeaders(), body: JSON.stringify(body) });
      const refreshMessage = watchlistRefreshMessage(payload, isPersonalHolding ? "已保存到自选和个人持仓，行情稍后刷新" : "已保存，行情稍后刷新");
      renderWatchlist(payload);
      updateShell(payload.meta || {}, payload.meta?.source === "cache" ? "cache" : "live");
      showWatchlistRefreshMessage(refreshMessage);
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
        const payload = await sendJson(`/api/v1/watchlist/${encodeURIComponent(symbol)}?market=${encodeURIComponent(market || "")}`, { method: "DELETE", headers: actionHeaders() });
        const refreshMessage = watchlistRefreshMessage(payload, "已删除，行情稍后刷新");
        renderWatchlist(payload);
        updateShell(payload.meta || {}, payload.meta?.source === "cache" ? "cache" : "live");
        showWatchlistRefreshMessage(refreshMessage);
      } catch (error) {
        button.textContent = "失败";
        button.removeAttribute("disabled");
      }
    });
  });
}

function picksEmptyMessage(data = {}) {
  const reason = data.empty_reason;
  if (reason === "api_no_data") return data.empty_message || "接口暂无可用选股数据";
  if (reason === "date_no_picks") return data.empty_message || "该日期无选股";
  if (reason === "filter_no_match") return data.empty_message || "筛选条件无匹配";
  return "暂无选股结果";
}

function bindPicksControls(payload) {
  const data = payload.data || {};
  document.querySelectorAll("[data-pick-strategy]").forEach((button) => {
    button.addEventListener("click", () => {
      pageState.picks.strategy = button.dataset.pickStrategy || null;
      updateUrlQuery(picksQueryParams());
      dom.refreshButton?.click();
    });
  });
  document.querySelector("[data-pick-date='prev']")?.addEventListener("click", () => {
    pageState.picks.date = shiftDate(pageState.picks.date || data.trade_date || pageState.picks.latestDate, -1);
    updateUrlQuery(picksQueryParams());
    dom.refreshButton?.click();
  });
  document.querySelector("[data-pick-date='today']")?.addEventListener("click", () => {
    pageState.picks.date = hkDateString();
    updateUrlQuery(picksQueryParams());
    dom.refreshButton?.click();
  });
  document.querySelector("[data-pick-export]")?.addEventListener("click", () => {
    const url = joinUrl(API_BASE, `/api/v1/strategies/picks/export${queryString(picksQueryParams())}`);
    window.location.href = url;
  });
}

function renderPicks(payload) {
  const data = payload.data || {};
  const { strategy = "", strategy_label = "", trade_date = "", strategies = [], items = [] } = data;
  pageState.picks.latestDate = payload.meta?.trade_date || trade_date || pageState.picks.latestDate;
  if (!pageState.picks.strategy && strategy) pageState.picks.strategy = strategy;
  if (!pageState.picks.date && trade_date) pageState.picks.date = trade_date;
  const activeStrategy = pageState.picks.strategy || strategy || strategy_label;
  const strategyTabs = strategies.length ? strategies : [strategy_label || strategy || "当前策略"];
  dom.app.innerHTML = `
    <section class="strategy-toolbar"><div class="mini-tabs">${strategyTabs.map((item) => {
      const value = pickStrategyValue(item);
      const label = pickStrategyLabel(item);
      const active = value === activeStrategy || label === strategy_label || label === activeStrategy;
      return `<button type="button" data-pick-strategy="${escapeHtml(value)}" class="${active ? "active" : ""}">${escapeHtml(label)}</button>`;
    }).join("")}</div><div class="toolbar"><button class="ghost-button icon-label" type="button" data-pick-date="prev">${icon("arrowLeft")}<span>昨日</span></button><button class="primary-button icon-label" type="button" data-pick-date="today"><span>今日</span>${icon("arrowRight")}</button><button class="ghost-button icon-label" type="button" data-pick-export>${icon("download")}<span>导出 CSV</span></button></div></section>
    <div class="section-heading"><h2>今日选股结果</h2><span>${escapeHtml(trade_date || pageState.picks.date || "--")} · 共 ${items.length} 只</span></div>
    <section class="pick-grid">
      ${items.length ? items.map((pick) => {
        const isFresh = pick.is_new ?? pick.fresh;
        const entry = pick.entry_price ?? pick.entry;
        const stop = pick.stop_loss ?? pick.stop;
        const target = pick.take_profit ?? pick.target;
        return `<article class="pick-card ${isFresh ? "fresh" : ""}"><div class="inline-between"><div><strong>${escapeHtml(pick.symbol)}</strong><span>${escapeHtml(pick.name)}</span></div><div class="pick-rank"><span>Rank</span><strong>${intText(pick.rank || pick.score)}</strong></div></div>${pickRawMetrics(pick)}<div class="trade-levels"><div><span>Entry</span><strong>${fixedText(entry, 2)}</strong></div><div><span>Stop</span><strong>${fixedText(stop, 2)}</strong></div><div><span>Target</span><strong>${fixedText(target, 2)}</strong></div></div></article>`;
      }).join("") : `<div class="empty-state">${escapeHtml(picksEmptyMessage(data))}</div>`}
    </section>
  `;
  bindPicksControls(payload);
}

function strategySignalTags(signals = []) {
  if (!signals.length) return `<span class="muted-text">--</span>`;
  return `<div class="holding-signal-tags">${signals.slice(0, 3).map((item) => tag(`${item.strategy_name || "策略"} · ${item.action_label || "--"}`, item.source === "holding" ? "positive" : actionTone(item.action))).join("")}</div>`;
}

function exitAlertCell(alerts = []) {
  if (!alerts.length) return `<span class="muted-text">--</span>`;
  return alerts.slice(0, 2).map((item) => {
    const tone = item.action === "reduce" || item.action === "trim" ? "warning" : "negative";
    return `<div class="holding-exit-alert">${tag(item.action_label || "卖出/风控", tone)}<small>${escapeHtml(item.strategy_name || "策略")} · ${escapeHtml(item.reason || "--")}</small></div>`;
  }).join("");
}

function positionStateTag(row = {}) {
  const state = row.portfolio_state || row.position_status || "actual";
  if (state === "target") return tag("目标持仓/待成交", "warning");
  if (row.portfolio_type === "personal") return tag("个人持仓", "blue");
  return tag("实际持仓", "positive");
}

function strategyOutputReason(row) {
  const parts = [];
  if (row.reason) parts.push(row.reason);
  if (row.suggested_weight_pct !== null && row.suggested_weight_pct !== undefined) parts.push(`目标 ${valueWithUnit(row.suggested_weight_pct, "%", 0)}`);
  if (row.score !== null && row.score !== undefined) parts.push(`分数 ${valueText(row.score, 0)}`);
  return parts.join(" · ") || "--";
}

function holdingsPageNote(data = {}) {
  const targetCount = (data.quant_holdings || []).filter((row) => row.portfolio_state === "target").length;
  if (!targetCount) return "";
  return `<div class="inline-note">${tag(`${targetCount} 个目标持仓`, "warning")} 策略买入信号已并入量化持仓；未收到成交回报前会标记为待成交。</div>`;
}

function strategySourceTone(source = "") {
  if (source === "manual") return "blue";
  if (source === "joinquant") return "positive";
  if (source.includes("backtest") || source === "static") return "neutral";
  return "warning";
}

function performanceStrategyTabs(strategies = [], activeStrategy = "") {
  if (!strategies.length) return `<div class="empty-state">暂无收益曲线</div>`;
  return strategies.map((item) => `<button type="button" data-strategy="${escapeHtml(item.id)}" class="${item.id === activeStrategy ? "active" : ""}"><span>${escapeHtml(item.label)}</span>${tag(item.source === "manual" ? "个人" : item.source === "joinquant" ? "量化" : "历史", strategySourceTone(item.source || ""))}</button>`).join("");
}

function currentStrategyLabel(strategies = [], activeStrategy = "") {
  const found = strategies.find((item) => item.id === activeStrategy);
  return found?.label || activeStrategy || "策略";
}

function compactSignalList(rows = []) {
  if (!rows.length) return `<div class="empty-state small">暂无策略信号</div>`;
  return `<div class="compact-action-list dense">${rows.slice(0, 5).map((row) => `
    <div class="compact-action-item">
      <div class="inline-between"><div><strong>${escapeHtml(row.symbol || "--")}</strong><span>${escapeHtml(row.name || row.reason || "")}</span></div>${tag(row.action_label || row.side_label || "--", actionTone(row.action || row.side))}</div>
      <div class="compact-action-meta"><span>${escapeHtml(strategyOutputReason(row))}</span><span>${formatDateTime(row.updated_at || row.received_at)}</span></div>
    </div>
  `).join("")}</div>`;
}

function strategyHoldingGroups(groups = [], fallbackRows = [], holdingTable) {
  const rows = groups.length
    ? groups
    : fallbackRows.length
      ? [{ strategy_id: "quant", strategy_name: "量化持仓", holdings: fallbackRows, signals: [], positions: [], sell_alerts: [], summary: {}, allocation: [] }]
      : [];
  if (!rows.length) return `<div class="empty-state">暂无量化持仓。策略上报成交或目标仓位后会出现在这里。</div>`;
  return `<div class="strategy-holding-groups">${rows.map((group) => {
    const holdings = Array.isArray(group.holdings) ? group.holdings : [];
    const actualCount = holdings.filter((row) => row.portfolio_state !== "target").length;
    const targetCount = holdings.filter((row) => row.portfolio_state === "target").length;
    const signals = Array.isArray(group.signals) ? group.signals : [];
    const alerts = Array.isArray(group.sell_alerts) ? group.sell_alerts : [];
    const summary = group.summary || {};
    return `
      <article class="strategy-holding-group">
        <div class="strategy-group-head">
          <div>
            <p class="panel-kicker">${escapeHtml(group.strategy_id || "strategy")}</p>
            <h3>${escapeHtml(group.strategy_name || group.strategy_id || "量化策略")}</h3>
            <small>${formatDateTime(group.updated_at) || "等待更新"} · ${escapeHtml(group.trade_date || "--")}</small>
          </div>
          <div class="strategy-group-actions">
            ${tag(`${intText(actualCount)} 持仓`, "blue")}
            ${targetCount ? tag(`${intText(targetCount)} 目标`, "warning") : ""}
            ${alerts.length ? tag(`${intText(alerts.length)} 风控`, "warning") : ""}
            <a class="panel-link" href="${escapeHtml(group.strategy_page || `strategy.html?strategy_id=${encodeURIComponent(group.strategy_id || "")}`)}">策略详情</a>
            <a class="panel-link" href="performance.html?strategy=${encodeURIComponent(group.strategy_id || "")}">收益曲线</a>
          </div>
        </div>
        <div class="strategy-group-metrics">
          <div><span>市值</span><strong>${summary.total_market_value === null || summary.total_market_value === undefined ? "--" : `¥${intText(summary.total_market_value)}`}</strong></div>
          <div><span>累计收益</span><strong class="${toneClassByValue(summary.total_return_pct)}">${pctText(summary.total_return_pct)}</strong></div>
          <div><span>仓位</span><strong>${valueWithUnit(summary.exposure_pct, "%", 1)}</strong></div>
          <div><span>信号</span><strong>${intText(signals.length)}</strong></div>
        </div>
        <div class="strategy-group-split">
          <div>
            <div class="subsection-label">策略持仓</div>
            ${holdingTable(holdings)}
          </div>
          <div>
            <div class="subsection-label">最新信号</div>
            ${compactSignalList(signals)}
          </div>
        </div>
      </article>
    `;
  }).join("")}</div>`;
}

function renderHoldings(payload) {
  const summary = payload.data?.summary || {};
  const source = payload.data?.holdings || [];
  const quantHoldings = payload.data?.quant_holdings || source.filter((row) => row.portfolio_type === "quant");
  const personalHoldings = payload.data?.personal_holdings || source.filter((row) => row.portfolio_type === "personal");
  const quantByStrategy = payload.data?.quant_by_strategy || [];
  const quantSummary = payload.data?.quant_summary || {};
  const personalSummary = payload.data?.personal_summary || {};
  const allocation = payload.data?.quant_allocation || payload.data?.allocation || [];
  const strategyOutputs = payload.data?.strategy_outputs || {};
  const outputSignals = strategyOutputs.signals || [];
  const sellAlerts = strategyOutputs.sell_alerts || [];
  const activeType = queryParam("type");
  const activeStrategy = queryParam("strategy_id");
  const holdingHeaders = ["股票", "策略信号", "卖出/风控", "持仓均价", "最新价", "持仓量", "市值", "盈亏额", "盈亏%", "仓位占比", "持有天数", "操作"];
  const totalPnl = source.reduce((sum, item) => sum + Number(item.pnl_pct || 0), 0);
  const holdingTable = (rows, options = {}) => table(
    holdingHeaders,
    rows.map((row) => {
      const avgCost = row.avg_cost ?? row.cost;
      const marketValue = row.market_value;
      const pnlAmount = row.pnl_amount ?? row.pnl_pct;
      const holdingDays = row.holding_days === null || row.holding_days === undefined || Number.isNaN(Number(row.holding_days)) ? "--" : `${intText(row.holding_days)} 天`;
      return `<tr class="holding-card-row ${Number(row.pnl_pct) >= 0 ? "profit-row" : "loss-row"}"><td class="holding-stock" data-label="股票"><strong>${escapeHtml(row.symbol)}</strong><br><small>${escapeHtml(row.name)}</small><div class="holding-state">${positionStateTag(row)}</div></td><td class="holding-strategy-signal" data-label="策略信号">${options.personal ? tag("个人持仓", "blue") : strategySignalTags(row.strategy_signals || [])}</td><td class="holding-exit-cell" data-label="卖出/风控">${options.personal || row.portfolio_state === "target" ? `<span class="muted-text">${escapeHtml(row.notes || "--")}</span>` : exitAlertCell(row.exit_alerts || [])}</td><td data-label="持仓均价">${valueText(avgCost, 2)}</td><td class="holding-price" data-label="最新价">${valueText(row.last_price, 2)}</td><td data-label="持仓量">${row.quantity === null || row.quantity === undefined ? "--" : intText(row.quantity)}</td><td class="holding-market-value" data-label="市值">${marketValue === null || marketValue === undefined ? "--" : `¥${intText(marketValue)}`}</td><td data-label="盈亏额" class="${toneClassByValue(pnlAmount)}">${pnlAmount === null || pnlAmount === undefined ? "--" : `${Number(pnlAmount) > 0 ? "+" : ""}¥${intText(pnlAmount)}`}</td><td data-label="盈亏%"><div class="pnl-bar ${toneByValue(row.pnl_pct)}"><i style="--bar:${Math.min(100, Math.abs(row.pnl_pct || 0) * 8)}%;"></i><span>${pctText(row.pnl_pct)}</span></div></td><td data-label="仓位占比"><div class="mini-donut" style="--score:${row.weight_pct || 0}%;"></div></td><td data-label="持有天数">${row.portfolio_state === "target" ? "--" : Number(row.holding_days) > 30 ? tag(holdingDays, "warning") : escapeHtml(holdingDays)}</td><td data-label="操作"><div class="action-cell"><button class="row-action" type="button" data-holding-mark="${escapeHtml(row.symbol)}">标记</button><button class="row-action" type="button" data-rebalance-record="${escapeHtml(row.symbol)}" data-weight="${escapeHtml(row.weight_pct || 0)}">调仓记录</button><span class="action-status" data-action-status></span></div></td></tr>`;
    }),
    1500,
  );
  dom.app.innerHTML = `
    <section class="strategy-toolbar">
      <div class="mini-tabs">
        <a class="${!activeType ? "active" : ""}" href="holdings.html">全部</a>
        <a class="${activeType === "quant" ? "active" : ""}" href="holdings.html?type=quant${activeStrategy ? `&strategy_id=${encodeURIComponent(activeStrategy)}` : ""}">量化持仓</a>
        <a class="${activeType === "personal" ? "active" : ""}" href="holdings.html?type=personal">个人持仓</a>
      </div>
      <div class="toolbar">${activeStrategy ? pill(`策略 ${activeStrategy}`, "blue") : ""}<a class="panel-link" href="strategy.html">量化策略</a></div>
    </section>
    ${summaryGrid([
      metricCard("总市值", summary.total_market_value === undefined ? "--" : `¥${intText(summary.total_market_value)}`, "Portfolio value"),
      metricCard("今日盈亏", summary.day_pnl_amount === undefined ? "--" : `${Number(summary.day_pnl_amount) > 0 ? "+" : ""}¥${intText(summary.day_pnl_amount)}`, pctText(summary.day_pnl_pct), toneByValue(summary.day_pnl_amount)),
      metricCard("累计收益", `${pctText(summary.total_return_pct)}`, "Total return", toneByValue(summary.total_return_pct ?? totalPnl)),
      metricCard("仓位使用", valueWithUnit(summary.exposure_pct, "%", 0), `${summary.position_count ?? source.length} 只持仓`),
      metricCard("持仓数量", `${intText(summary.position_count ?? source.length)} 只`, `Sector diversity ${summary.sector_diversity ?? allocation.length}`),
    ])}
    ${holdingsPageNote(payload.data || {})}
    ${panel({
      title: "量化持仓",
      kicker: "Quant Positions",
      span: "span-12",
      tools: `${pill(`${intText(quantSummary.position_count ?? quantHoldings.length)} 只`, "blue")}${quantByStrategy.length ? pill(`${intText(quantByStrategy.length)} 个策略`, "neutral") : ""}`,
      body: strategyHoldingGroups(quantByStrategy, quantHoldings, holdingTable),
    })}
    ${panel({
      title: "个人持仓",
      kicker: "Personal Positions",
      span: "span-12",
      tools: pill(`${intText(personalSummary.position_count ?? personalHoldings.length)} 只`, "blue"),
      body: holdingTable(personalHoldings, { personal: true }),
    })}
    ${panel({
      title: "聚宽策略输出",
      kicker: "JoinQuant Signals",
      span: "span-8",
      tools: pill(`${intText(outputSignals.length)} 条`, "blue"),
      body: table(
        ["策略", "股票", "动作", "理由", "更新时间"],
        outputSignals.map((row) => `<tr><td>${escapeHtml(row.strategy_name || "--")}</td><td><strong>${escapeHtml(row.symbol)}</strong><br><small>${escapeHtml(row.name || "")}</small></td><td>${tag(row.action_label || "--", actionTone(row.action))}</td><td>${escapeHtml(strategyOutputReason(row))}</td><td>${formatDateTime(row.updated_at)}</td></tr>`),
        880,
      ),
    })}
    ${panel({
      title: "实时卖出/风控",
      kicker: "Sell Alerts",
      span: "span-4",
      tools: pill(`${intText(sellAlerts.length)} 条`, sellAlerts.length ? "warning" : "blue"),
      body: sellAlerts.length ? `<div class="alert-list">${sellAlerts.slice(0, 8).map((row) => `<article class="alert-item"><div class="inline-between"><strong>${escapeHtml(row.symbol || row.strategy_name || "策略级风控")}</strong>${tag(row.action_label || "卖出/风控", row.level === "error" ? "negative" : "warning")}</div><span>${escapeHtml(row.strategy_name || "--")} · ${escapeHtml(row.reason || "--")}</span><small>${formatDateTime(row.time)}</small></article>`).join("")}</div>` : `<div class="empty-state">暂无卖出或风控提醒</div>`,
    })}
    ${panel({ title: "行业配置", kicker: "Allocation", span: "span-12", body: `<div class="allocation-panel"><div class="allocation-donut"></div>${barList(allocation.map((item) => ({ name: item.sector, value: item.weight_pct, unit: "%", detail: item.market_value ? `¥${intText(item.market_value)}` : "" })), { color: "var(--accent)" })}</div>` })}
  `;
  bindHoldingActions();
}

function bindHoldingActions() {
  document.querySelectorAll("[data-holding-mark]").forEach((button) => {
    button.addEventListener("click", () => {
      postAction(button, `/api/v1/portfolio/holdings/${encodeURIComponent(button.dataset.holdingMark)}/mark`, { mark: "reviewed", note: "前端持仓列表标记" }, "标记成功");
    });
  });
  document.querySelectorAll("[data-rebalance-record]").forEach((button) => {
    button.addEventListener("click", () => {
      postAction(button, "/api/v1/portfolio/rebalance-records", { symbol: button.dataset.rebalanceRecord, action: "review", weight_pct: button.dataset.weight, note: "前端持仓列表创建调仓记录" }, "调仓记录已保存");
    });
  });
}

function statusPill(status) {
  return pill(statusText(status), statusTone(status));
}

function strategySignals(payloadData = {}) {
  const signals = payloadData.signals || payloadData.recommendations || [];
  return Array.isArray(signals) ? signals : [];
}

function strategyExposure(summary = {}) {
  return summary.current_exposure_pct ?? summary.exposure_pct ?? 0;
}

function strategyTargetExposure(summary = {}) {
  return summary.target_exposure_pct ?? summary.exposure_pct ?? 0;
}

function strategyCreateForm() {
  return `
    <form class="strategy-create-form" data-strategy-create-form>
      <label class="span-2"><span>操作令牌</span><input name="action_token" type="password" autocomplete="off" placeholder="可选；填写后保存到本机浏览器" /></label>
      <label><span>策略 ID</span><input name="id" required pattern="[A-Za-z0-9_.-]{2,64}" placeholder="my-new-strategy" /></label>
      <label><span>策略名称</span><input name="name" required placeholder="我的新策略" /></label>
      <label><span>类型</span><select name="category"><option value="custom">自定义</option><option value="etf">ETF</option><option value="stock">股票</option><option value="futures">期货</option></select></label>
      <label><span>状态</span><select name="status"><option value="idle">未运行</option><option value="running">正在运行</option><option value="paused">暂停</option><option value="stopped">停用</option></select></label>
      <label class="span-2"><span>说明</span><input name="description" placeholder="策略用途、运行频率或 JoinQuant 说明" /></label>
      <div class="form-actions span-2">
        <button class="primary-button icon-label" type="submit">${icon("picks")}<span>添加策略</span></button>
        <span class="action-status" data-action-status></span>
      </div>
    </form>
  `;
}

function bindStrategyHubControls(payload) {
  document.querySelectorAll("[data-strategy-select]").forEach((button) => {
    button.addEventListener("click", () => {
      pageState.strategy.strategyId = button.dataset.strategySelect || "";
      updateUrlQuery({ strategy_id: pageState.strategy.strategyId });
      dom.refreshButton?.click();
    });
  });
  document.querySelector("[data-strategy-list]")?.addEventListener("click", () => {
    pageState.strategy.strategyId = "";
    updateUrlQuery({ strategy_id: "" });
    dom.refreshButton?.click();
  });
  document.querySelector("[data-strategy-create-form]")?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const body = Object.fromEntries(formData.entries());
    const token = String(body.action_token || "").trim();
    delete body.action_token;
    if (token) window.localStorage?.setItem("quant_action_token", token);
    const result = await submitActionForm(form, "/api/v1/quant/strategies", body, "策略已创建");
    const strategy = result?.data?.strategy;
    if (strategy?.id) {
      pageState.strategy.strategyId = strategy.id;
      updateUrlQuery({ strategy_id: strategy.id });
      dom.refreshButton?.click();
    }
  });
}

function strategyListRows(strategies = []) {
  if (!strategies.length) return `<div class="empty-state">暂无策略</div>`;
  return `<div class="strategy-card-grid">${strategies.map((row) => `
    <article class="strategy-overview-card ${row.status || "idle"}">
      <div class="inline-between">
        <div><span class="panel-kicker">${escapeHtml(row.category || "strategy")}</span><h3>${escapeHtml(row.name || row.id)}</h3><small class="mono">${escapeHtml(row.id)}</small></div>
        ${statusPill(row.status)}
      </div>
      <p>${escapeHtml(row.decision_title || row.description || "等待策略快照")}</p>
      <div class="strategy-card-metrics">
        <div><span>信号</span><strong>${intText(row.signal_count)}</strong></div>
        <div><span>持仓</span><strong>${intText(row.holding_count)}</strong></div>
        <div><span>仓位</span><strong>${valueWithUnit(row.current_exposure_pct, "%", 0)}</strong></div>
      </div>
      <div class="card-actions">
        <button class="ghost-button" type="button" data-strategy-select="${escapeHtml(row.id)}">查看策略</button>
        <a class="panel-link" href="holdings.html?type=quant&strategy_id=${encodeURIComponent(row.id)}">持仓信息</a>
      </div>
    </article>
  `).join("")}</div>`;
}

function renderStrategyDetail(payload) {
  const data = payload.data || {};
  const registry = data.registry || {};
  const strategy = data.strategy || {};
  if (strategy.id === "binance-listing-onchain" || registry.id === "binance-listing-onchain") {
    renderBinanceListing(payload);
    return;
  }
  if (strategy.id === "crypto-funding-rate" || registry.id === "crypto-funding-rate" || Array.isArray(data.instances)) {
    renderCryptoFunding(payload);
    return;
  }
  const summary = data.summary || {};
  const signals = strategySignals(data);
  const holdings = Array.isArray(data.holdings) ? data.holdings : [];
  const events = Array.isArray(data.events) ? data.events : [];
  const logs = Array.isArray(data.logs) ? data.logs : [];
  const strategyId = registry.id || strategy.id || pageState.strategy.strategyId;
  const signalCards = signals.map((item) => ({
    ...item,
    action: item.action || item.signal || "watch",
    action_label: item.action_label || item.signal_label || item.signal || item.action || "观察",
  }));
  dom.app.innerHTML = `
    <section class="strategy-toolbar">
      <button class="ghost-button icon-label" type="button" data-strategy-list>${icon("arrowLeft")}<span>策略列表</span></button>
      <div class="toolbar">${statusPill(strategy.status || registry.status)}<a class="panel-link" href="holdings.html?type=quant&strategy_id=${encodeURIComponent(strategyId)}">查看持仓信息</a></div>
    </section>
    ${pageDecisionBrief({
      kicker: strategy.name || registry.name || "Quant Strategy",
      title: strategy.decision_title || "等待策略结论",
      detail: strategy.decision_detail || "该策略还没有推送运行快照。",
      tone: strategy.decision_tone || (strategy.status === "running" ? "blue" : "warning"),
      metrics: [
        { label: "运行状态", value: statusText(strategy.status || registry.status) },
        { label: "目标仓位", value: valueWithUnit(strategyTargetExposure(summary), "%", 0) },
        { label: "当前仓位", value: valueWithUnit(strategyExposure(summary), "%", 0) },
        { label: "最近更新", value: formatDateTime(payload.meta?.as_of) },
      ],
    })}
    ${summaryGrid([
      metricCard("信号数量", `${intText(summary.signal_count ?? signals.length)} 条`, `${intText(summary.buy_count)} 条买入`),
      metricCard("持仓数量", `${intText(summary.hold_count ?? holdings.length)} 只`, `当前 ${valueWithUnit(strategyExposure(summary), "%", 0)}`),
      metricCard("当日盈亏", pctText(summary.day_pnl_pct), "JoinQuant snapshot", toneByValue(summary.day_pnl_pct)),
      metricCard("运行来源", registry.source || payload.meta?.source || "--", registry.storage_path || ""),
    ])}
    <section class="main-grid">
      ${panel({ title: "策略信号", kicker: "Signals", span: "span-8", body: compactInstrumentCards(signalCards, strategyId) })}
      ${panel({ title: "策略档案", kicker: "Registry", span: "span-4", body: detailGrid([{ label: "策略 ID", value: strategyId, detail: registry.builtin ? "内置策略" : "网页新增" }, { label: "类型", value: strategy.category || registry.category || "--", detail: strategy.provider || registry.provider || "--" }, { label: "快照接口", value: `/snapshot`, detail: registry.snapshot_endpoint || data.snapshot_endpoint || "" }, { label: "持仓链接", value: "量化持仓", detail: data.holdings_url || "" }]) })}
      ${panel({ title: "持仓详情", kicker: "Positions", span: "span-8", body: table(["代码", "名称", "仓位", "成本", "现价", "当日涨跌", "浮动盈亏"], holdings.map((row) => `<tr><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.name)}</td><td>${valueWithUnit(row.weight_pct, "%", 0)}</td><td>${valueText(row.cost ?? row.avg_cost, 3)}</td><td>${valueText(row.last_price, 3)}</td><td class="${toneClassByValue(row.day_change_pct)}">${pctText(row.day_change_pct)}</td><td class="${toneClassByValue(row.pnl_pct)}">${pctText(row.pnl_pct)}</td></tr>`), 780) })}
      ${panel({ title: "运行记录", kicker: "Events", span: "span-4", body: timeline(events) })}
      ${panel({ title: "完整日志", kicker: "Logs", span: "span-12", tools: pill(`${intText(Math.min(logs.length, STRATEGY_LOG_DISPLAY_LIMIT))} lines`, "blue"), body: strategyLogConsole(logs) })}
    </section>
  `;
  bindSignalActions();
  bindStrategyHubControls(payload);
}

function renderStrategyHub(payload) {
  if (payload.data?.strategy) {
    renderStrategyDetail(payload);
    return;
  }
  const strategies = payload.data?.strategies || [];
  const summary = payload.data?.summary || {};
  dom.app.innerHTML = `
    ${summaryGrid([
      metricCard("策略数量", `${intText(summary.strategy_count)} 个`, `${intText(summary.running_count)} 个运行中`),
      metricCard("正在运行", `${intText(summary.running_count)} 个`, "running"),
      metricCard("未运行", `${intText(summary.inactive_count)} 个`, "idle / pending"),
      metricCard("新增入口", "网页端", payload.data?.snapshot_endpoint_template || ""),
    ])}
    <section class="main-grid">
      ${panel({ title: "策略列表", kicker: "Quant Strategies", span: "span-8", body: strategyListRows(strategies) })}
      ${panel({ title: "添加策略", kicker: "Create Strategy", span: "span-4", description: "创建后即可获得统一 snapshot 接口，供 JoinQuant 推送。", body: strategyCreateForm() })}
    </section>
  `;
  bindStrategyHubControls(payload);
}

function renderPerformance(payload) {
  const data = payload.data || {};
  const metricsData = data.metrics || {};
  if (data.strategy && !performanceState.strategy) performanceState.strategy = data.strategy;
  if (data.benchmark_id && !performanceState.benchmark) performanceState.benchmark = data.benchmark_id;
  const equity = data.equity_curve?.length ? data.equity_curve : [];
  const benchmark = data.benchmark_curve?.length ? data.benchmark_curve : [];
  const monthly = data.monthly_returns || [];
  const strategies = data.strategies?.length ? data.strategies : [{ id: data.strategy || "momentum", label: data.strategy_label || "动量策略", source: data.nav_source?.source || "unknown" }];
  const benchmarks = data.benchmarks?.length ? data.benchmarks : [{ id: data.benchmark_id || "CSI300", label: data.benchmark || "沪深300" }];
  const navSource = data.nav_source || {};
  const benchmarkStatus = data.benchmark_status || {};
  const reconciliation = data.reconciliation || {};
  const dataQuality = data.data_quality || {};
  const lastEquityPoint = equity[equity.length - 1] || {};
  const firstEquityPoint = equity[0] || {};
  const lastBenchmarkPoint = benchmark[benchmark.length - 1] || {};
  const selectedStrategyLabel = data.strategy_label || currentStrategyLabel(strategies, data.strategy);
  const frequencyLabel = dataQuality.frequency_label || navSource.frequency_label || "频率未知";
  const syntheticCurve = Boolean(dataQuality.synthetic || navSource.synthetic);
  const sourceCards = [
    metricCard("累计收益", pctText(lastEquityPoint.return_pct), `${escapeHtml(firstEquityPoint.date || "--")} 起`, toneByValue(lastEquityPoint.return_pct)),
    metricCard("年化收益", pctText(metricsData.annual_return_pct), "Annualized", toneByValue(metricsData.annual_return_pct)),
    metricCard("最大回撤", pctText(metricsData.max_drawdown_pct), "Max drawdown", toneByValue(metricsData.max_drawdown_pct)),
    metricCard("夏普比率", valueText(metricsData.sharpe, 2), "Sharpe", toneByValue(metricsData.sharpe)),
    metricCard("曲线频率", frequencyLabel, `${intText(dataQuality.point_count ?? navSource.point_count ?? equity.length)} 点${syntheticCurve ? " · 代理" : ""}`, syntheticCurve ? "warning" : "positive"),
    metricCard("基准收益", benchmark.length ? pctText(lastBenchmarkPoint.return_pct) : "--", data.benchmark || "未选择基准", toneByValue(lastBenchmarkPoint.return_pct)),
  ];
  const statusItems = [
    ["策略", selectedStrategyLabel],
    ["来源", navSource.source || payload.meta?.source || "--"],
    ["频率", `${frequencyLabel}${dataQuality.average_gap_days ? ` / 间隔 ${valueText(dataQuality.average_gap_days, 1)} 天` : ""}`],
    ["点数", `${intText(navSource.point_count ?? equity.length)} 点`],
    ["最后上报", formatDateTime(navSource.last_seen || payload.meta?.last_seen)],
    ["延迟", secondsText(navSource.stale_seconds ?? payload.meta?.stale_seconds)],
    ["账户", reconciliation.total_value === null || reconciliation.total_value === undefined ? "--" : `¥${intText(reconciliation.total_value)}`],
    ["现金", reconciliation.cash === null || reconciliation.cash === undefined ? "--" : `¥${intText(reconciliation.cash)}`],
    ["差额", reconciliation.diff === null || reconciliation.diff === undefined ? "--" : `¥${intText(reconciliation.diff)}`],
  ];
  const ranges = [
    { id: "3M", label: "3M" },
    { id: "1Y", label: "1Y" },
    { id: "ALL", label: "全部" },
  ];
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
    <section class="strategy-toolbar">
      <div class="mini-tabs" data-performance-strategies>
        ${performanceStrategyTabs(strategies, data.strategy)}
      </div>
      <div class="toolbar">
        ${benchmarks.map((item) => `<label><input type="checkbox" data-benchmark="${escapeHtml(item.id)}" ${item.id === data.benchmark_id ? "checked" : ""} /> 对比 ${escapeHtml(item.label)}</label>`).join("")}
        <div class="mini-tabs" data-performance-ranges>
          ${ranges.map((item) => `<button type="button" data-range="${item.id}" class="${item.id === performanceState.range ? "active" : ""}">${item.label}</button>`).join("")}
        </div>
      </div>
    </section>
    ${summaryGrid(sourceCards)}
    <section class="performance-analysis-grid">
      ${panel({
        title: "历史收益曲线",
        kicker: "Historical Performance",
        span: "span-12 performance-chart-panel",
        tools: `${pill(frequencyLabel, syntheticCurve ? "warning" : "positive")}${pill(`${intText(equity.length)} 点`, "blue")}${benchmark.length ? pill(`基准 ${intText(benchmark.length)} 点`, "neutral") : ""}`,
        body: equityChart(equity, benchmark, { seriesLabel: selectedStrategyLabel, benchmarkLabel: data.benchmark || data.benchmark_id || "基准" }),
      })}
      ${syntheticCurve ? `<div class="inline-note performance-frequency-note">${tag("日频代理", "warning")} ${escapeHtml(dataQuality.message || "当前曲线由低频锚点插值生成，真实交易日波动需由 JoinQuant 上报每日净值。")}</div>` : ""}
      <section class="metric-strip performance-metrics-panel">${metrics.map(([label, value, delta, tone]) => `<article class="perf-metric"><span>${label}</span><strong class="tone-${tone}">${value}</strong><small>${delta}</small></article>`).join("")}</section>
      <div class="performance-status-strip" aria-label="数据链路状态">
        ${statusItems.map(([label, value]) => `<span><b>${escapeHtml(label)}</b>${escapeHtml(value)}</span>`).join("")}
      </div>
      ${panel({ title: "月度收益热力", kicker: "Monthly Return Heatmap", span: "span-12", body: monthly.length ? `<div class="monthly-heat">${monthly.map((item) => { const value = Number(item.return_pct || 0); return `<span class="${toneByValue(value)}" title="${item.year || ""}-${item.month || ""} ${pctText(value)}">${pctText(value, 1)}</span>`; }).join("")}</div>` : `<div class="empty-state">暂无月度收益数据</div>` })}
    </section>
    <details class="performance-technical-details">
      <summary>数据链路明细</summary>
      <div class="source-status-grid compact-source-status">
        <div><span>策略快照</span><strong>${escapeHtml(navSource.source || payload.meta?.source || "--")}</strong><small>${escapeHtml(navSource.snapshot_path || "--")}</small></div>
        <div><span>净值流水</span><strong>${intText(navSource.point_count)} 点</strong><small>${escapeHtml(navSource.storage_path || "--")}</small></div>
        <div><span>曲线频率</span><strong>${escapeHtml(frequencyLabel)}</strong><small>${escapeHtml(dataQuality.message || "--")}</small></div>
        <div><span>基准来源</span><strong>${escapeHtml(benchmarkStatus.source_name || benchmarkStatus.source || "--")}</strong><small>${escapeHtml(benchmarkStatus.trade_date || "--")} · ${secondsText(benchmarkStatus.stale_seconds)}</small></div>
        <div><span>当前请求</span><strong>${escapeHtml(data.strategy || "--")}</strong><small>${escapeHtml(data.benchmark_id || "无基准")}</small></div>
      </div>
    </details>
  `;
  dom.app.querySelectorAll("[data-strategy]").forEach((button) => {
    button.addEventListener("click", () => {
      performanceState.strategy = button.dataset.strategy || "";
      updateUrlQuery({ strategy: performanceState.strategy });
      refreshPerformance();
    });
  });
  dom.app.querySelectorAll("[data-benchmark]").forEach((input) => {
    input.addEventListener("change", () => {
      performanceState.benchmark = input.checked ? (input.dataset.benchmark || "") : "none";
      dom.app.querySelectorAll("[data-benchmark]").forEach((other) => {
        if (other !== input) other.checked = false;
      });
      refreshPerformance();
    });
  });
  dom.app.querySelectorAll("[data-range]").forEach((button) => {
    button.addEventListener("click", () => {
      syncPerformanceRange(button.dataset.range || "1Y");
      refreshPerformance();
    });
  });
}

function compactInstrumentCards(items, strategyId = "etf") {
  if (!items?.length) return `<div class="empty-state">暂无标的</div>`;
  return `<div class="signal-card-grid">${items.map((item) => `<article class="signal-card ${actionTone(item.action)}"><div class="signal-card-head"><div><span>${escapeHtml(item.symbol)} ${escapeHtml(item.market || "")}</span><strong>${escapeHtml(item.name)}</strong></div>${tag(item.action_label || item.action, actionTone(item.action))}</div>${sparkline(item.trend, item.change_pct)}<div class="signal-card-metrics"><div><span>信号分</span><strong>${intText(item.score)}</strong></div><div><span>仓位</span><strong>${valueWithUnit(item.suggested_weight_pct, "%", 0)}</strong></div><div><span>涨跌</span><strong class="${toneClassByValue(item.change_pct)}">${pctText(item.change_pct)}</strong></div></div><p class="note">${escapeHtml(item.reason || "")}</p><div class="card-actions"><button class="ghost-button" type="button" data-signal-confirm="${escapeHtml(item.symbol)}" data-strategy-id="${escapeHtml(strategyId)}" data-signal-action="${escapeHtml(item.action || "confirm")}">确认信号</button><span class="action-status" data-action-status></span></div></article>`).join("")}</div>`;
}

function bindSignalActions() {
  document.querySelectorAll("[data-signal-confirm]").forEach((button) => {
    button.addEventListener("click", () => {
      const strategyId = button.dataset.strategyId || "strategy";
      const symbol = button.dataset.signalConfirm;
      postAction(button, `/api/v1/strategies/${encodeURIComponent(strategyId)}/signals/${encodeURIComponent(symbol)}/confirm`, { action: button.dataset.signalAction || "confirm", note: "前端信号卡片确认" }, "信号已确认");
    });
  });
}

function strategyLogConsole(items = []) {
  if (!items?.length) return `<div class="empty-state">暂无策略日志</div>`;
  const rows = items.slice(-STRATEGY_LOG_DISPLAY_LIMIT).reverse();
  return `
    <div class="strategy-log-console">
      ${rows.map((item) => {
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
      ${panel({ title: "推荐标的", kicker: "Signal Cards", span: "span-8", body: compactInstrumentCards(recommendations, strategy.id || "etf") })}
      ${panel({ title: "风格环境", kicker: "Regime", span: "span-4", body: scoreBlock(regime.score, regime.label || "环境分", `风险预算 ${valueWithUnit(strategy.risk_budget_pct, "%", 0)}，现金 ${valueWithUnit(strategy.cash_weight_pct, "%", 0)}。`, (regime.factors || []).map((item) => ({ name: item.name, value: item.value, detail: item.detail }))) })}
      ${panel({ title: "当前持仓", kicker: "Positions", span: "span-8", body: table(["代码", "名称", "仓位", "成本", "现价", "当日涨跌", "浮动盈亏"], holdings.map((row) => `<tr><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.name)}</td><td>${valueWithUnit(row.weight_pct, "%", 0)}</td><td>${valueText(row.cost, 3)}</td><td>${valueText(row.last_price, 3)}</td><td class="${toneClassByValue(row.day_change_pct)}">${pctText(row.day_change_pct)}</td><td class="${toneClassByValue(row.pnl_pct)}">${pctText(row.pnl_pct)}</td></tr>`), 780) })}
      ${panel({ title: "运行记录", kicker: "Events", span: "span-4", body: timeline(events) })}
      ${panel({ title: "完整日志", kicker: "JoinQuant Logs", span: "span-12", tools: pill(`${intText(Math.min(logs.length, STRATEGY_LOG_DISPLAY_LIMIT))} lines`, "blue"), body: strategyLogConsole(logs) })}
    </section>
  `;
  bindSignalActions();
}

function renderCryptoFunding(payload) {
  const data = payload.data || {};
  const { strategy = {}, summary = {}, heartbeat = {}, positions = [], signals = [], trades = [], events = [], logs = [] } = data;
  const rawInstances = Array.isArray(data.instances) && data.instances.length
    ? data.instances
    : [{ strategy, summary, heartbeat, positions, pending_events: data.pending_events || [], signals, trades, events, logs }];
  const instances = rawInstances.map((item) => ({
    strategy: item.strategy || {},
    summary: item.summary || {},
    heartbeat: item.heartbeat || {},
    positions: Array.isArray(item.positions) ? item.positions : [],
    pending_events: Array.isArray(item.pending_events) ? item.pending_events : [],
    signals: Array.isArray(item.signals) ? item.signals : [],
    trades: Array.isArray(item.trades) ? item.trades : [],
    events: Array.isArray(item.events) ? item.events : [],
    logs: Array.isArray(item.logs) ? item.logs : [],
  }));
  const recentSignals = Array.isArray(signals) ? signals.slice(-30).reverse() : instances.flatMap((item) => item.signals).slice(-30).reverse();
  const recentTrades = Array.isArray(trades) ? trades.slice(-40).reverse() : instances.flatMap((item) => item.trades).slice(-40).reverse();
  const openPositions = Array.isArray(positions) ? positions : instances.flatMap((item) => item.positions);
  const runningInstances = instances.filter((item) => item.strategy?.status === "running").length;
  const cryptoPositionTable = (rows = []) => rows.length
    ? table(["标的", "方向", "资金费率", "入场", "名义本金", "杠杆", "止盈", "止损"], rows.map((row) => `<tr><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.side_label || row.side)}</td><td class="${toneClassByValue(row.funding_rate_pct)}">${pctText(row.funding_rate_pct)}</td><td>${valueText(row.entry_price, 6)}</td><td>$${valueText(row.order_notional_usd, 2)}</td><td>${valueWithUnit(row.leverage, "x", 1)}</td><td>${pctText(Number(row.take_profit || row.take_profit_pct || 0) * (Math.abs(Number(row.take_profit || row.take_profit_pct || 0)) < 1 ? 100 : 1))}</td><td>${pctText(Number(row.stop_loss || row.stop_loss_pct || 0) * (Math.abs(Number(row.stop_loss || row.stop_loss_pct || 0)) < 1 ? 100 : 1))}</td></tr>`), 980)
    : `<div class="empty-state">暂无实例持仓</div>`;
  const cryptoSignalList = (rows = []) => rows.length
    ? `<div class="signal-card-grid compact">${rows.slice(-8).reverse().map((row) => `<article class="signal-card ${row.action === "sell" ? "negative" : row.action === "buy" ? "positive" : "warning"}"><div class="signal-card-head"><div><span>${escapeHtml(row.market || "USDT-PERP")}</span><strong>${escapeHtml(row.symbol)}</strong></div>${tag(row.action_label || row.side_label || "观察", row.action === "sell" ? "negative" : row.action === "buy" ? "positive" : "warning")}</div><div class="signal-card-metrics"><div><span>费率</span><strong class="${toneClassByValue(row.funding_rate_pct)}">${pctText(row.funding_rate_pct)}</strong></div><div><span>入场</span><strong>${valueText(row.entry_price, 6)}</strong></div><div><span>本金</span><strong>$${valueText(row.order_notional_usd, 0)}</strong></div></div><p class="note">${escapeHtml(row.reason || row.event_key || "")}</p></article>`).join("")}</div>`
    : `<div class="empty-state">暂无实例信号</div>`;
  const instanceCards = instances.map((item) => {
    const itemStrategy = item.strategy || {};
    const itemSummary = item.summary || {};
    const itemHeartbeat = item.heartbeat || {};
    return `<article class="strategy-instance-panel ${escapeHtml(itemStrategy.status || "waiting")}">
      <div class="strategy-group-head">
        <div>
          <span class="panel-kicker">${escapeHtml(itemStrategy.profile || itemHeartbeat.strategy_profile || "funding")}</span>
          <h3>${escapeHtml(itemStrategy.name || itemHeartbeat.strategy_name || itemStrategy.id)}</h3>
          <small class="mono">${escapeHtml(itemStrategy.id || itemHeartbeat.strategy_id || "--")}</small>
        </div>
        ${statusPill(itemStrategy.status)}
      </div>
      <p class="instance-detail">${escapeHtml(itemStrategy.decision_detail || itemStrategy.description || "")}</p>
      <div class="strategy-card-metrics">
        <div><span>阈值</span><strong>${valueWithUnit(itemSummary.funding_threshold_pct, "%", 2)}</strong></div>
        <div><span>信号</span><strong>${intText(itemSummary.signal_count)}</strong></div>
        <div><span>持仓</span><strong>${intText(itemSummary.open_position_count)}</strong></div>
        <div><span>盈亏</span><strong class="${toneClassByValue(itemSummary.realized_pnl_usd)}">$${valueText(itemSummary.realized_pnl_usd, 2)}</strong></div>
        <div><span>本金</span><strong>$${valueText(itemSummary.equity_usd, 0)}</strong></div>
        <div><span>容量</span><strong>${valueWithUnit(itemSummary.capacity_participation_pct, "%", 2)}</strong></div>
        <div><span>杠杆</span><strong>${valueWithUnit(itemSummary.max_leverage, "x", 1)}</strong></div>
        <div><span>心跳</span><strong>${secondsText(itemHeartbeat.stale_seconds)}</strong></div>
      </div>
      <div class="strategy-group-split">
        <div><div class="subsection-label">实例持仓</div>${cryptoPositionTable(item.positions)}</div>
        <div><div class="subsection-label">实例信号</div>${cryptoSignalList(item.signals)}</div>
      </div>
    </article>`;
  }).join("");
  dom.app.innerHTML = `
    ${payload.data?.registry ? `<section class="strategy-toolbar"><button class="ghost-button icon-label" type="button" data-strategy-list>${icon("arrowLeft")}<span>策略列表</span></button><div class="toolbar">${statusPill(strategy.status)}</div></section>` : ""}
    ${pageDecisionBrief({
      kicker: strategy.name || "Crypto Funding",
      title: strategy.decision_title || "等待资金费率信号",
      detail: strategy.decision_detail || "策略正在监听 Binance USD-M Futures 资金费率事件。",
      tone: strategy.decision_tone || "blue",
      metrics: [
        { label: "模式", value: strategy.mode || heartbeat.mode || "DRY_RUN" },
        { label: "实例", value: `${intText(runningInstances)} / ${intText(instances.length)}` },
        { label: "扫描标的", value: `${intText(summary.symbol_count)} 个` },
        { label: "开仓数", value: `${intText(summary.open_position_count)} 笔` },
      ],
    })}
    ${summaryGrid([
      metricCard("权益", `$${valueText(summary.equity_usd, 0)}`, `可用模拟本金`),
      metricCard("已实现盈亏", `$${valueText(summary.realized_pnl_usd, 2)}`, pctText(summary.realized_return_pct), toneByValue(summary.realized_pnl_usd)),
      metricCard("交易笔数", `${intText(summary.trade_count)} 笔`, `胜率 ${valueWithUnit(summary.win_rate_pct, "%", 1)}`),
      metricCard("阈值/容量", `${valueWithUnit(summary.funding_threshold_pct, "%", 2)}`, `容量 ${valueWithUnit(summary.capacity_participation_pct, "%", 2)} / ${valueWithUnit(summary.max_leverage, "x", 1)}`),
    ])}
    <section class="main-grid">
      ${panel({ title: "策略实例", kicker: "Instances · Positions and Signals", span: "span-12", body: `<div class="strategy-instance-list">${instanceCards}</div>` })}
      ${panel({ title: "全部模拟持仓", kicker: "Open Positions", span: "span-7", body: table(["实例", "标的", "方向", "资金费率", "入场", "名义本金", "杠杆", "止盈", "止损"], openPositions.map((row) => `<tr><td>${escapeHtml(row.strategy_name || row.strategy_id || "--")}</td><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.side_label || row.side)}</td><td class="${toneClassByValue(row.funding_rate_pct)}">${pctText(row.funding_rate_pct)}</td><td>${valueText(row.entry_price, 6)}</td><td>$${valueText(row.order_notional_usd, 2)}</td><td>${valueWithUnit(row.leverage, "x", 1)}</td><td>${pctText(Number(row.take_profit || row.take_profit_pct || 0) * (Math.abs(Number(row.take_profit || row.take_profit_pct || 0)) < 1 ? 100 : 1))}</td><td>${pctText(Number(row.stop_loss || row.stop_loss_pct || 0) * (Math.abs(Number(row.stop_loss || row.stop_loss_pct || 0)) < 1 ? 100 : 1))}</td></tr>`), 1120) })}
      ${panel({ title: "全部信号", kicker: "Funding Signals", span: "span-5", body: recentSignals.length ? `<div class="signal-card-grid compact">${recentSignals.map((row) => `<article class="signal-card ${row.action === "sell" ? "negative" : row.action === "buy" ? "positive" : "warning"}"><div class="signal-card-head"><div><span>${escapeHtml(row.strategy_name || row.market || "USDT-PERP")}</span><strong>${escapeHtml(row.symbol)}</strong></div>${tag(row.action_label || row.side_label || "观察", row.action === "sell" ? "negative" : row.action === "buy" ? "positive" : "warning")}</div><div class="signal-card-metrics"><div><span>费率</span><strong class="${toneClassByValue(row.funding_rate_pct)}">${pctText(row.funding_rate_pct)}</strong></div><div><span>入场</span><strong>${valueText(row.entry_price, 6)}</strong></div><div><span>本金</span><strong>$${valueText(row.order_notional_usd, 0)}</strong></div></div><p class="note">${escapeHtml(row.reason || row.event_key || "")}</p></article>`).join("")}</div>` : `<div class="empty-state">暂无资金费率信号</div>` })}
      ${panel({ title: "交易盈亏", kicker: "Trades", span: "span-8", body: table(["时间", "实例", "标的", "方向", "状态", "入场", "出场", "名义本金", "盈亏", "原因"], recentTrades.map((row) => `<tr><td>${formatDateTime(row.received_at || row.closed_at || row.opened_at)}</td><td>${escapeHtml(row.strategy_name || row.strategy_id || "--")}</td><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.side_label || row.side)}</td><td>${escapeHtml(row.status || row.event_type)}</td><td>${valueText(row.entry_price, 6)}</td><td>${valueText(row.exit_price, 6)}</td><td>$${valueText(row.order_notional_usd, 2)}</td><td class="${toneClassByValue(row.pnl_usd)}">$${valueText(row.pnl_usd, 2)} / ${pctText(row.pnl_pct)}</td><td>${escapeHtml(row.exit_reason || row.rule || "--")}</td></tr>`), 1260) })}
      ${panel({ title: "心跳详情", kicker: "Heartbeat", span: "span-4", body: detailGrid([
        { label: "最近心跳", value: formatDateTime(heartbeat.received_at || payload.meta?.as_of), detail: `${secondsText(heartbeat.stale_seconds)} 前` },
        { label: "运行机器", value: heartbeat.host || heartbeat.hostname || "jp_vps", detail: heartbeat.mode || "DRY_RUN" },
        { label: "保证金", value: heartbeat.margin_type || "ISOLATED", detail: heartbeat.position_mode || "ONE_WAY" },
        { label: "文件", value: "JSONL", detail: heartbeat.files?.trades || "trades.jsonl" },
      ]) })}
      ${panel({ title: "事件记录", kicker: "Events", span: "span-4", body: timeline((events || []).slice(-20).reverse().map((row) => ({ time: formatDateTime(row.received_at || row.created_at), label: row.symbol || row.event_type || "event", detail: row.exit_reason || row.reason || row.message || row.event_key || "", status: row.status || "done" }))) })}
      ${panel({ title: "运行日志", kicker: "Crypto Logs", span: "span-8", tools: pill(`${intText(Math.min(logs.length, STRATEGY_LOG_DISPLAY_LIMIT))} lines`, "blue"), body: strategyLogConsole(logs) })}
    </section>
  `;
  bindStrategyHubControls(payload);
}

function renderBinanceListing(payload) {
  const data = payload.data || {};
  const { strategy = {}, summary = {}, heartbeat = {}, positions = [], signals = [], trades = [], events = [], logs = [] } = data;
  const recentSignals = Array.isArray(signals) ? signals.slice(-30).reverse() : [];
  const recentTrades = Array.isArray(trades) ? trades.slice(-40).reverse() : [];
  const openPositions = Array.isArray(positions) ? positions : [];
  const riskText = `${pctText(summary.stop_loss_pct, 0)} / ${pctText(summary.take_profit_1_pct, 0)} / ${pctText(summary.take_profit_2_pct, 0)}`;
  const signalCards = recentSignals.slice(0, 8).map((row) => `<article class="signal-card ${actionTone(row.action)}">
    <div class="signal-card-head">
      <div><span>${escapeHtml(row.market || row.chain || "on-chain")}</span><strong>${escapeHtml(row.symbol || "--")}</strong></div>
      ${tag(row.action_label || row.action || "观察", actionTone(row.action))}
    </div>
    <div class="signal-card-metrics">
      <div><span>交易对</span><strong>${escapeHtml(Array.isArray(row.binance_spot_pairs) ? row.binance_spot_pairs.slice(0, 2).join(", ") : "--")}</strong></div>
      <div><span>上线时间</span><strong>${formatDateTime(row.listing_time_utc)}</strong></div>
      <div><span>合约</span><strong class="mono">${escapeHtml((row.contract?.address || row.token_address || "--").slice(0, 12))}</strong></div>
    </div>
    <p class="note">${escapeHtml(row.title || row.reason || "")}</p>
  </article>`).join("");
  dom.app.innerHTML = `
    ${payload.data?.registry ? `<section class="strategy-toolbar"><button class="ghost-button icon-label" type="button" data-strategy-list>${icon("arrowLeft")}<span>策略列表</span></button><div class="toolbar">${statusPill(strategy.status)}${pill(strategy.mode || heartbeat.mode || "DRY_RUN", "blue")}</div></section>` : ""}
    ${pageDecisionBrief({
      kicker: strategy.name || "Binance Listing",
      title: strategy.decision_title || "等待 Binance 上新公告",
      detail: strategy.decision_detail || "策略正在监控 Binance 公告板，并只对正文中明确给出官方合约的标的做链上 DRY_RUN 验证。",
      tone: strategy.decision_tone || "blue",
      metrics: [
        { label: "运行模式", value: strategy.mode || heartbeat.mode || "DRY_RUN" },
        { label: "心跳延迟", value: secondsText(heartbeat.stale_seconds) },
        { label: "已见公告", value: `${intText(summary.seen_article_count)} 篇` },
        { label: "开放持仓", value: `${intText(summary.open_position_count)} 笔` },
      ],
    })}
    ${summaryGrid([
      metricCard("候选信号", `${intText(summary.signal_count)} 条`, `${intText(summary.validated_count)} 条通过验证`),
      metricCard("模拟交易", `${intText(summary.trade_count || summary.order_count)} 笔`, `持仓 ${intText(summary.open_position_count)} / 已平 ${intText(summary.closed_position_count)}`),
      metricCard("单笔预算", `$${valueText(summary.stake_usd, 0)}`, `退出 ${riskText}`),
      metricCard("错误事件", `${intText(summary.error_count)} 条`, heartbeat.host || heartbeat.hostname || "jp_vps", toneByValue(-Number(summary.error_count || 0))),
    ])}
    <section class="main-grid">
      ${panel({ title: "公告信号", kicker: "Announcement Signals", span: "span-5", body: signalCards ? `<div class="signal-card-grid compact">${signalCards}</div>` : `<div class="empty-state">暂无上新信号</div>` })}
      ${panel({ title: "模拟持仓", kicker: "Open Positions", span: "span-7", body: table(["标的", "链", "合约", "交易对", "入场预算", "剩余数量", "上线时间", "状态"], openPositions.map((row) => `<tr><td class="mono">${escapeHtml(row.symbol || "--")}</td><td>${escapeHtml(row.chain || row.contract?.chain || "--")}</td><td class="mono">${escapeHtml(row.token_address || row.contract?.address || "--")}</td><td>${escapeHtml(Array.isArray(row.binance_spot_pairs) ? row.binance_spot_pairs.join(", ") : row.spot_pair || "--")}</td><td>$${valueText(row.entry_cost_usd || row.amount_in_usd, 2)}</td><td>${valueText(row.remaining_amount_raw, 4)}</td><td>${formatDateTime(row.listing_time_utc)}</td><td>${escapeHtml(row.status || "open")}</td></tr>`), 1180) })}
      ${panel({ title: "模拟成交", kicker: "Dry-run Trades", span: "span-8", body: table(["时间", "标的", "方向", "状态", "链", "报价币", "投入", "产出", "盈亏", "原因"], recentTrades.map((row) => `<tr><td>${formatDateTime(row.received_at || row.created_at)}</td><td class="mono">${escapeHtml(row.symbol || "--")}</td><td>${escapeHtml(row.side_label || row.side || "--")}</td><td>${escapeHtml(row.status || "--")}</td><td>${escapeHtml(row.chain || row.market || "--")}</td><td>${escapeHtml(row.quote_token || "--")}</td><td>$${valueText(row.amount_in_usd, 2)}</td><td>$${valueText(row.amount_out_usd, 2)}</td><td class="${toneClassByValue(row.pnl_pct)}">${pctText(row.pnl_pct)}</td><td>${escapeHtml(row.exit_reason || row.reason || "--")}</td></tr>`), 1280) })}
      ${panel({ title: "心跳详情", kicker: "Heartbeat", span: "span-4", body: detailGrid([
        { label: "最近心跳", value: formatDateTime(heartbeat.received_at || payload.meta?.as_of), detail: `${secondsText(heartbeat.stale_seconds)} 前` },
        { label: "运行机器", value: heartbeat.host || heartbeat.hostname || "jp_vps", detail: heartbeat.run_id || payload.meta?.run_id || "" },
        { label: "公告栏目", value: `catalog ${summary.watched_catalog_id || heartbeat.catalog_id || 48}`, detail: heartbeat.list_url || "Binance announcements" },
        { label: "状态文件", value: "JSONL", detail: heartbeat.output_dir || heartbeat.state_path || "" },
      ]) })}
      ${panel({ title: "事件记录", kicker: "Events", span: "span-4", body: timeline((events || []).slice(-20).reverse().map((row) => ({ time: formatDateTime(row.received_at || row.created_at), label: row.symbol || row.event_type || "event", detail: row.message || row.reason || row.title || "", status: row.status || row.event_type || "done" }))) })}
      ${panel({ title: "运行日志", kicker: "Listing Logs", span: "span-8", tools: pill(`${intText(Math.min(logs.length, STRATEGY_LOG_DISPLAY_LIMIT))} lines`, "blue"), body: strategyLogConsole(logs) })}
    </section>
  `;
  bindStrategyHubControls(payload);
}

function renderSmallCap(payload) {
  const { strategy = {}, summary = {}, signals = [], holdings = [], themes = [], risk = {}, events = [], logs = [] } = payload.data || {};
  dom.app.innerHTML = `
    ${pageDecisionBrief({ kicker: strategy.name || "Small Cap Strategy", title: strategy.decision_title || "暂无策略结论", detail: strategy.decision_detail || `候选池 ${intText(strategy.candidate_count)} / ${intText(strategy.universe_size)}，当前仓位 ${valueWithUnit(summary.exposure_pct, "%", 0)}。`, tone: strategy.decision_tone || "blue", metrics: [{ label: "买入候选", value: summary.buy_count === undefined ? "--" : `${summary.buy_count} 只` }, { label: "仓位状态", value: valueWithUnit(summary.exposure_pct, "%", 0) }, { label: "单票上限", value: valueWithUnit(strategy.max_position_pct, "%", 0) }, { label: "止损条件", value: strategy.stop_policy || "--" }] })}
    ${summaryGrid([metricCard("今日信号", summary.signal_count === undefined ? "--" : `${summary.signal_count} 只`, `${summary.buy_count ?? "--"} 只买入`), metricCard("策略仓位", valueWithUnit(summary.exposure_pct, "%", 0), `换手 ${valueWithUnit(summary.turnover_pct, "%", 0)}`), metricCard("当日盈亏", pctText(summary.day_pnl_pct), `浮盈 ${pctText(summary.floating_pnl_pct)}`, toneByValue(summary.day_pnl_pct)), metricCard("候选池", `${intText(strategy.candidate_count)} / ${intText(strategy.universe_size)}`, `单票上限 ${valueWithUnit(strategy.max_position_pct, "%", 0)}`)])}
    <section class="main-grid">
      ${panel({ title: "今日信号", kicker: "Signal Cards", span: "span-8", body: signals.length ? `<div class="signal-card-grid">${signals.map((item) => `<article class="signal-card ${actionTone(item.signal)}"><div class="signal-card-head"><div><span>${escapeHtml(item.symbol)} / ${escapeHtml(item.theme)}</span><strong>${escapeHtml(item.name)}</strong></div>${tag(item.signal_label, actionTone(item.signal))}</div><div class="signal-card-metrics"><div><span>分数</span><strong>${intText(item.score)}</strong></div><div><span>风险</span><strong>${riskLabel(item.risk)}</strong></div><div><span>涨跌</span><strong class="${toneClassByValue(item.change_pct)}">${pctText(item.change_pct)}</strong></div></div><p class="note">执行：${escapeHtml(item.suggested_range || "--")}。失效：${escapeHtml(item.invalidation || strategy.stop_policy || "--")}</p><div class="card-actions"><button class="ghost-button" type="button" data-signal-confirm="${escapeHtml(item.symbol)}" data-strategy-id="small-cap" data-signal-action="${escapeHtml(item.signal || "confirm")}">确认信号</button><span class="action-status" data-action-status></span></div></article>`).join("")}</div>` : `<div class="empty-state">暂无今日信号</div>` })}
      ${panel({ title: "风控", kicker: "Risk", span: "span-4", body: `<div class="stack">${barList([{ name: "流动性通过率", value: risk.liquidity_pass_pct, detail: "候选池过滤" }, { name: "最大集中度", value: risk.concentration_pct, detail: "单一持仓" }, { name: "波动压力", value: risk.volatility_score, detail: "短期波动" }], { color: "var(--warning)" })}<p class="note">${escapeHtml(strategy.stop_policy || "")}</p></div>` })}
      ${panel({ title: "当前持仓", kicker: "Positions", span: "span-8", body: table(["代码", "名称", "主题", "仓位", "成本", "现价", "当日涨跌", "浮动盈亏", "天数"], holdings.map((row) => `<tr><td class="mono">${escapeHtml(row.symbol)}</td><td>${escapeHtml(row.name)}</td><td>${escapeHtml(row.theme)}</td><td>${valueWithUnit(row.weight_pct, "%", 0)}</td><td>${valueText(row.cost, 2)}</td><td>${valueText(row.last_price, 2)}</td><td class="${toneClassByValue(row.day_change_pct)}">${pctText(row.day_change_pct)}</td><td class="${toneClassByValue(row.pnl_pct)}">${pctText(row.pnl_pct)}</td><td>${intText(row.holding_days)}</td></tr>`), 980) })}
      ${panel({ title: "主题暴露", kicker: "Themes", span: "span-4", body: barList(themes.map((item) => ({ name: item.name, value: item.exposure_pct, detail: `宽度 ${valueWithUnit(item.breadth_pct, "%", 0)}`, unit: "%" }))) })}
      ${panel({ title: "运行记录", kicker: "Events", span: "span-4", body: timeline(events) })}
      ${panel({ title: "完整日志", kicker: "JoinQuant Logs", span: "span-8", tools: pill(`${intText(Math.min(logs.length, STRATEGY_LOG_DISPLAY_LIMIT))} lines`, "blue"), body: strategyLogConsole(logs) })}
    </section>
  `;
  bindSignalActions();
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
  const sourceQuality = payload.meta?.source_quality || source_algorithm.source_quality || brilliant_volatility.source_quality || summary.source_quality || "real";
  const sourceNotice = sourceQuality === "proxy" ? `<div class="alert-list proxy-source-notice"><article class="alert-item"><div class="inline-between"><strong>代理指标提示</strong>${pill("代理指标", "warning")}</div><span>真实散户情绪/耀眼波动率分钟源暂不可用，当前页面使用市场宽度代理指标，请勿按真实 1 分钟耀眼波动解读。</span></article></div>` : sourceQuality === "unavailable" ? `<div class="alert-list proxy-source-notice"><article class="alert-item"><div class="inline-between"><strong>真实分钟源不可用</strong>${pill("不可用", "warning")}</div><span>当前页面停止使用代理情绪，只展示真实分钟源缺失状态。</span></article></div>` : "";
  const gaugeInput = summary.temperature !== undefined ? summary.temperature : latest_snapshot.sentiment_value !== undefined ? Number(latest_snapshot.sentiment_value) * 100 : null;
  const sourcePill = sourceQuality === "real" ? pill("真实源", "positive") : sourceQuality === "proxy" ? pill("代理指标", "warning") : pill("不可用", "warning");
  dom.app.innerHTML = `${sourceNotice}${sentimentGauge(gaugeInput)}<section class="main-grid">${panel({ title: "情绪趋势图", kicker: "Trend", span: "span-8", body: renderSentimentLineChart(sentiment_trend, latest_snapshot.warning_line ?? .15) })}${panel({ title: "情绪状态", kicker: "Sentiment Score", span: "span-4", tools: sourcePill, body: scoreBlock(summary.score, summary.label || "情绪", "过热时降低追涨权重，低迷时优先等待宽度修复。", gauges, "var(--warning)") })}${panel({ title: "1 分钟耀眼波动", kicker: source_algorithm.name || "Brilliant Volatility", span: "span-4", tools: `${pill(brilliant_volatility.intraday_signal || "--", "warning")}${sourceQuality !== "real" ? pill(sourceQuality === "proxy" ? "代理" : "不可用", "warning") : ""}`, body: detailGrid([{ label: "跟踪标的", value: `${brilliant_volatility.name || "--"} ${brilliant_volatility.symbol || ""}`, detail: `收盘 ${valueText(brilliant_volatility.close, 3)}` }, { label: "日耀眼波动", value: valueWithUnit(brilliant_volatility.daily_brilliant_vol, "%", 2), detail: brilliant_volatility.signal_detail || "" }, { label: "激增次数", value: `${intText(brilliant_volatility.surge_count)} 次`, detail: `最后 ${brilliant_volatility.last_surge_time || "--"}` }, { label: "窗口", value: brilliant_volatility.window || source_algorithm.time_window || "--", detail: source_algorithm.surge_rule || "" }]) })}${panel({ title: "题材热度", kicker: "Topics", span: "span-8", body: heatmap(topics, "heat", "热度") })}${panel({ title: "激增事件", kicker: "Intraday Surge", span: "span-6", body: table(["时间", "量增倍数", "窗口波动", "价格变化"], surge_events.map((row) => `<tr><td class="mono">${escapeHtml(row.time)}</td><td>${valueText(row.volume_increase_ratio, 2)}x</td><td>${valueWithUnit(row.return_std, "%", 2)}</td><td class="${toneClassByValue(row.price_change_pct)}">${pctText(row.price_change_pct)}</td></tr>`), 620) })}${panel({ title: "资金流", kicker: "Flows", span: "span-6", body: table(["指标", "数值", "说明"], flows.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${valueWithUnit(row.value, row.unit, 2)}</td><td>${escapeHtml(row.detail)}</td></tr>`), 620) })}${panel({ title: "提醒", kicker: "Warnings", span: "span-6", body: alertList(warnings) })}</section>`;
}

function renderMacro(payload) {
  const { summary = {}, rates = [], fx = [], risk_assets = [], calendar = [], observations = [] } = payload.data || {};
  dom.app.innerHTML = `${pageDecisionBrief({ kicker: "Macro Regime", title: summary.title || `宏观环境 ${summary.label || "--"}`, detail: summary.detail || `中国 10Y ${valueWithUnit(summary.ten_year_yield_pct, "%")}，USD/CNH ${valueText(summary.usd_cnh, 2)}，股债利差 ${valueWithUnit(summary.equity_bond_spread_pct, "%")}。`, tone: summary.tone || "blue", metrics: [{ label: "风险偏好", value: valueWithUnit(summary.risk_preference_score, "/100", 0) }, { label: "中国 10Y", value: valueWithUnit(summary.ten_year_yield_pct, "%") }, { label: "USD/CNH", value: valueText(summary.usd_cnh, 2) }, { label: "股债利差", value: valueWithUnit(summary.equity_bond_spread_pct, "%") }] })}<section class="main-grid">${panel({ title: "利率", kicker: "Rates", span: "span-6", body: table(["指标", "数值", "变化"], rates.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${valueWithUnit(row.value, row.unit, 2)}</td><td class="${toneClassByValue(-row.change_bp)}">${Number(row.change_bp) > 0 ? "+" : ""}${valueText(row.change_bp, 1)}bp</td></tr>`), 620) })}${panel({ title: "风险资产", kicker: "Risk Assets", span: "span-6", body: table(["资产", "点位", "涨跌"], risk_assets.map((row) => `<tr><td>${escapeHtml(row.name)}</td><td>${valueText(row.value, 2)}</td><td class="${toneClassByValue(row.change_pct)}">${pctText(row.change_pct)}</td></tr>`), 620) })}${panel({ title: "外汇", kicker: "FX", span: "span-4", body: barList(fx.map((row) => ({ name: row.name, value: row.value, detail: `变化 ${pctText(row.change_pct)}` })), { max: 110 }) })}${panel({ title: "日历", kicker: "Calendar", span: "span-4", body: table(["日期", "事件", "重要性"], calendar.map((row) => `<tr><td>${escapeHtml(row.date)}</td><td>${escapeHtml(row.event)}</td><td>${tag(row.importance === "high" ? "高" : "中", row.importance === "high" ? "warning" : "blue")}</td></tr>`), 560) })}${panel({ title: "观察", kicker: "Observations", span: "span-4", body: alertList(observations) })}</section>`;
}

function updateShell(meta, mode, apiError = null) {
  const isStale = mode === "stale";
  const isCache = mode === "cache";
  const sourceText = isStale ? "Stale cache" : isCache ? "Cached API" : "Live API";
  dom.apiMode.textContent = sourceText;
  dom.connectionBadge.textContent = isStale ? "刷新失败 · 显示缓存" : sourceText;
  dom.connectionBadge.className = `connection-badge ${isStale ? "stale" : isCache ? "mock" : "live"}`;
  if (isStale) {
    const message = apiError?.error?.message || "接口请求失败";
    const savedAt = apiError?.cached?.savedAt;
    dom.runSummary.textContent = `${message} / 缓存 ${formatDateTime(savedAt)}`;
    dom.lastUpdated.textContent = `显示缓存 ${formatDateTime(savedAt)}`;
    return;
  }
  dom.runSummary.textContent = `${meta.run_id || "--"} / ${formatDateTime(meta.as_of)}`;
  dom.lastUpdated.textContent = `最近刷新 ${formatDateTime(new Date().toISOString())}`;
}

function staleBanner(error, cached) {
  const message = error?.message || "接口请求失败";
  const savedAt = formatDateTime(cached?.savedAt);
  return `
    <aside class="stale-banner" data-stale-banner role="alert">
      <div><strong>刷新失败，当前显示最近成功缓存</strong><span>错误：${escapeHtml(message)} · 缓存时间：${escapeHtml(savedAt)}</span></div>
      <button type="button" aria-label="关闭缓存提示" data-dismiss-stale>${icon("close")}</button>
    </aside>
  `;
}

function insertStaleBanner(error, cached) {
  dom.app.querySelector("[data-stale-banner]")?.remove();
  dom.app.insertAdjacentHTML("afterbegin", staleBanner(error, cached));
  dom.app.querySelector("[data-dismiss-stale]")?.addEventListener("click", (event) => {
    event.currentTarget.closest("[data-stale-banner]")?.remove();
  });
}

function renderCachedFallback(config, error) {
  const cached = readLastPayload(activePage);
  if (!cached) return false;
  config.render(cached.payload);
  updateShell(cached.payload?.meta || {}, "stale", { error, cached });
  insertStaleBanner(error, cached);
  return true;
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
  const pageModule = PAGE_LOADERS[activePage] ? await PAGE_LOADERS[activePage]() : null;
  installShell();
  await installAuthShell();
  const page = pageModule?.pageKey && PAGE_CONFIG[pageModule.pageKey] ? pageModule.pageKey : activePage;
  const config = PAGE_CONFIG[page] || PAGE_CONFIG.overview;
  if (page === "performance" && !performanceState.from && performanceState.range !== "ALL") syncPerformanceRange(performanceState.range);
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
      if (!renderCachedFallback(config, error)) showError(error);
    } finally {
      refreshing = false;
    }
  }

  dom.refreshButton.addEventListener("click", refresh);
  await refresh();
  setInterval(() => refresh({ background: true }), config.refreshMs || 60_000);
}

init();
