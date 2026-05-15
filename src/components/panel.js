import { escapeHtml } from "../format.js";

export function panel({ title, kicker = "", description = "", tools = "", span = "span-6", body = "" }) {
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

export function inlineLoading(label = "加载中") {
  return `<div class="empty-state">${escapeHtml(label)}...</div>`;
}
