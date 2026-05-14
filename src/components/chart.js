export function sparkline(points = [], { width = 240, height = 72, className = "sparkline" } = {}) {
  const values = points.map(Number).filter((value) => !Number.isNaN(value));
  if (!values.length) return `<div class="empty-state">暂无图表数据</div>`;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const path = values.map((value, index) => `${index === 0 ? "M" : "L"}${(index * step).toFixed(2)},${(height - ((value - min) / range) * height).toFixed(2)}`).join(" ");
  return `<svg class="${className}" viewBox="0 0 ${width} ${height}" role="img" aria-label="趋势图"><path d="${path}" /></svg>`;
}

export function rangeBar(value, className = "") {
  const normalized = Math.max(0, Math.min(100, Number(value) || 0));
  return `<div class="range-bar ${className}"><i style="--pos:${normalized}%;"></i></div>`;
}
