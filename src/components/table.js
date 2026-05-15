import { escapeHtml } from "../format.js";

export function table(headers, rows, minWidth = 760) {
  return `<div class="table-wrap" style="--min:${minWidth}px"><table><thead><tr>${headers.map((head) => `<th>${escapeHtml(head)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
