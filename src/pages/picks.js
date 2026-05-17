export const pageKey = "picks";
export const pageMeta = ["Quant Picks", "量化选股"];
export const state = { strategy: null, date: null, latestDate: null };
export const config = { endpoint: "/api/v1/strategies/picks", refreshMs: 300_000 };
