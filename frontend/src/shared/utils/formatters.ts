/**
 * Shared timestamp and duration formatting utilities.
 */

/** Format an ISO string or epoch-seconds number as a locale string. */
export function formatTimestamp(value: string | number | null | undefined) {
  if (!value) return "无";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString();
}

/** Format a millisecond duration as human-readable text. */
export function formatDuration(value: number | undefined | null) {
  if (value == null || value <= 0) return "未记录";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(1)} s`;
}

/** Alias kept for call sites that prefer the shorter name. */
export const formatMs = formatDuration;
