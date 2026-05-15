const DEFAULT_API_BASE = window.QUANT_API_BASE || "";

export function joinUrl(base, path) {
  if (!base) return path;
  return `${base.replace(/\/$/, "")}${path}`;
}

export function withCacheBust(url) {
  return `${url}${url.includes("?") ? "&" : "?"}_=${Date.now()}`;
}

export async function requestJson(url) {
  const response = await fetch(withCacheBust(url), {
    cache: "no-store",
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

export async function sendJson(path, options = {}, apiBase = DEFAULT_API_BASE) {
  const response = await fetch(joinUrl(apiBase, path), {
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
    const requestError = new Error(detail);
    requestError.status = response.status;
    throw requestError;
  }
  return response.json();
}

export function actionHeaders() {
  const token = window.localStorage?.getItem("quant_action_token") || window.QUANT_ACTION_TOKEN || "";
  return token ? { "X-Action-Token": token } : {};
}

export async function fetchPayload(config, { apiBase = DEFAULT_API_BASE, resolveEndpoint = null } = {}) {
  if (!config.endpoint) throw new Error("页面未配置数据接口");
  const endpoint = resolveEndpoint ? resolveEndpoint(config) : typeof config.endpoint === "function" ? config.endpoint() : config.endpoint;
  const payload = await requestJson(joinUrl(apiBase, endpoint));
  const mode = payload.meta?.source === "cache" ? "cache" : "live";
  return { payload, mode };
}
