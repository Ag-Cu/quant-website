import { escapeHtml } from "../format.js";

export function metricCard(label, value, foot = "", tone = "") {
  return `<article class="metric-card ${tone}"><span>${escapeHtml(label)}</span><strong>${value ?? "--"}</strong>${foot ? `<small>${escapeHtml(foot)}</small>` : ""}</article>`;
}

export function summaryGrid(items = []) {
  return `<div class="summary-grid">${items.map((item) => metricCard(item.label, item.value, item.foot, item.tone)).join("")}</div>`;
}
