export const pageKey = "performance";
export const pageMeta = ["Performance", "历史收益"];
export const state = { strategy: "", benchmark: "CSI300", range: "1Y", from: "", to: "" };

export function formatDateParam(date) {
  return date.toISOString().slice(0, 10);
}

export function addMonths(date, months) {
  const next = new Date(date);
  next.setUTCMonth(next.getUTCMonth() + months);
  return next;
}

export function syncRange(range, target = state) {
  target.range = range;
  const today = new Date();
  target.to = formatDateParam(today);
  if (range === "3M") {
    target.from = formatDateParam(addMonths(today, -3));
  } else if (range === "1Y") {
    target.from = formatDateParam(addMonths(today, -12));
  } else {
    target.from = "";
    target.to = "";
  }
}

export function buildEndpoint(target = state) {
  const params = new URLSearchParams();
  if (target.strategy) params.set("strategy", target.strategy);
  if (target.benchmark) params.set("benchmark", target.benchmark);
  if (target.from) params.set("from", target.from);
  if (target.to) params.set("to", target.to);
  const query = params.toString();
  return `/api/v1/performance${query ? `?${query}` : ""}`;
}

export const config = { endpoint: buildEndpoint, refreshMs: 30_000 };
