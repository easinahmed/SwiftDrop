const UNITS = ["B", "KB", "MB", "GB", "TB"];

export function formatBytes(bytes: number | null | undefined, digits = 1): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1000) return `${Math.round(bytes)} B`;
  let value = bytes;
  let unit = 0;
  while (value >= 1000 && unit < UNITS.length - 1) {
    value /= 1000;
    unit += 1;
  }
  return `${value.toFixed(value >= 100 ? 0 : digits)} ${UNITS[unit]}`;
}

export function formatSpeed(bytesPerSecond: number | null | undefined): string | null {
  if (bytesPerSecond == null || !Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return null;
  return `${formatBytes(bytesPerSecond)}/s`;
}

export function formatEta(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null;
  if (seconds < 1) return "almost done";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s left`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s left`;
  const h = Math.floor(m / 60);
  if (h > 48) return null; // not a meaningful estimate
  return `${h}h ${m % 60}m left`;
}

export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return null;
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

export function formatRelative(timestamp: number | null | undefined, now = Date.now()): string {
  if (!timestamp) return "";
  const diff = Math.max(0, now / 1000 - timestamp);
  if (diff < 45) return "just now";
  if (diff < 3600) return `${Math.round(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.round(diff / 3600)} h ago`;
  const date = new Date(timestamp * 1000);
  const sameYear = date.getFullYear() === new Date(now).getFullYear();
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

export function folderName(path: string): string {
  if (!path) return "";
  const trimmed = path.replace(/\/+$/, "");
  const name = trimmed.split("/").pop() || trimmed;
  return name;
}

export function shortPath(path: string, home?: string): string {
  if (!path) return "";
  const m = path.match(/^\/Users\/[^/]+/);
  const homeDir = home ?? (m ? m[0] : "");
  return homeDir && path.startsWith(homeDir) ? `~${path.slice(homeDir.length)}` : path;
}

export function pluralize(count: number, singular: string, plural = `${singular}s`): string {
  return `${count.toLocaleString()} ${count === 1 ? singular : plural}`;
}

const URL_RE = /\b(?:https?:\/\/|www\.)[^\s<>"'`{}|\\^]+|\b(?:[a-z0-9-]+\.)+[a-z]{2,24}\/[^\s<>"'`{}|\\^]*/gi;

/** Rough client-side count for the live counter; the engine does the real parsing. */
export function countLinks(text: string): number {
  if (!text) return 0;
  return (text.match(URL_RE) || []).length;
}
