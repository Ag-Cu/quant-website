export const pageKey = "watchlist";
export const pageMeta = ["Watchlist", "自选股"];
export const state = { search: "", group: "all", sort: "change" };
export const config = { endpoint: "/api/v1/watchlist", refreshMs: 15_000 };

export function shouldPauseAutoRefresh() {
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
