export const integerFormat = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 });

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#039;" })[char]);
}

export function valueText(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(Number(value));
}

export function fixedText(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return Number(value).toFixed(digits);
}

export function intText(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  return integerFormat.format(Number(value));
}

export function pctText(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}%`;
}

export function valueWithUnit(value, unit = "", digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "--";
  const decimals = Math.abs(Number(value)) >= 100 ? 0 : digits;
  return `${valueText(value, decimals)}${escapeHtml(unit)}`;
}

export function toneByValue(value) {
  if (Number(value) > 0) return "positive";
  if (Number(value) < 0) return "negative";
  return "neutral";
}

export function toneClassByValue(value) {
  if (Number(value) > 0) return "positive-text";
  if (Number(value) < 0) return "negative-text";
  return "muted-text";
}

export function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Hong_Kong",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatFullDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day} ${values.hour}:${values.minute}:${values.second}`;
}
