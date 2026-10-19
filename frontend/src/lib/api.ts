// Typed client for the Python bridge exposed via pywebview (`window.pywebview.api`).
// Every call returns an envelope {ok, data} | {ok: false, error}; errors become ApiError.

import type {
  AnalyzeResult,
  Bootstrap,
  Diagnostics,
  HistoryEntry,
  PlaylistEntry,
  PushPayload,
  Settings,
  StartResult,
  StorageInfo,
  DownloadOptions,
} from "./types";

type Envelope<T> = { ok: true; data: T } | { ok: false; error: string; name?: string };
type Bridge = Record<string, (...args: unknown[]) => Promise<Envelope<unknown>>>;

declare global {
  interface Window {
    pywebview?: { api: Bridge };
    __SD_PUSH__?: (payload: PushPayload) => void;
  }
}

export class ApiError extends Error {
  /** File name the engine wants confirmation for (error "confirm_open"). */
  fileName?: string;
}

export const CONFIRM_OPEN = "confirm_open";

let bridgePromise: Promise<Bridge> | null = null;

function waitForBridge(): Promise<Bridge> {
  if (bridgePromise) return bridgePromise;
  bridgePromise = new Promise((resolve, reject) => {
    if (__DEMO__) {
      // The hosted web demo has no engine at all: use the simulated one straight away.
      import("./mock").then((m) => resolve(m.createMockBridge()));
      return;
    }
    const tryResolve = () => {
      const api = window.pywebview?.api;
      if (api && typeof api.get_bootstrap === "function") {
        resolve(api);
        return true;
      }
      return false;
    };
    if (tryResolve()) return;
    window.addEventListener("pywebviewready", () => tryResolve());
    const started = Date.now();
    // In a plain browser during UI development there is no engine; fall back to the
    // clearly labelled preview bridge. Production builds never include it.
    const giveUpAfter = import.meta.env.DEV ? 1500 : 20000;
    const poll = window.setInterval(() => {
      if (tryResolve()) {
        window.clearInterval(poll);
      } else if (Date.now() - started > giveUpAfter) {
        window.clearInterval(poll);
        if (import.meta.env.DEV) {
          import("./mock").then((m) => resolve(m.createMockBridge()));
        } else {
          reject(new ApiError("The download engine didn't start. Please restart the app."));
        }
      }
    }, 40);
  });
  return bridgePromise;
}

async function call<T>(name: string, ...args: unknown[]): Promise<T> {
  const bridge = await waitForBridge();
  const fn = bridge[name];
  if (typeof fn !== "function") throw new ApiError(`Missing bridge function ${name}`);
  const result = (await fn(...args)) as Envelope<T>;
  if (!result || typeof result !== "object") throw new ApiError("Unexpected response from the engine.");
  if (!result.ok) {
    const error = new ApiError(result.error);
    error.fileName = result.name;
    throw error;
  }
  return result.data;
}

export const isPreviewMode = () => Boolean((window as { __SD_MOCK__?: boolean }).__SD_MOCK__);

export const api = {
  bootstrap: () => call<Bootstrap>("get_bootstrap"),
  state: () => call<Omit<Bootstrap, "app">>("get_state"),
  analyze: (text: string, append = true) => call<AnalyzeResult>("analyze_text", text, append),
  inspect: (ids: string[]) => call<number>("inspect_preview", ids),
  removePreview: (ids: string[]) => call<number>("remove_preview", ids),
  clearPreview: () => call<number>("clear_preview"),
  playlistEntries: (id: string) => call<PlaylistEntry[]>("get_playlist_entries", id),
  start: (request: {
    items: { id: string; entries: string[] | null }[];
    options: DownloadOptions;
    destination: string | null;
  }) => call<StartResult>("start_downloads", request),
  jobAction: (action: "pause" | "resume" | "cancel" | "retry" | "remove", ids: string[]) =>
    call<number>("job_action", action, ids),
  queueAction: (
    action:
      | "pause_all"
      | "resume_all"
      | "retry_failed"
      | "clear_completed"
      | "clear_finished"
      | "clear_failed"
      | "clear_cancelled",
  ) => call<number>("queue_action", action),
  revealJob: (id: string) => call<boolean>("reveal_job", id),
  openJob: (id: string, confirmed = false) => call<boolean>("open_job", id, confirmed),
  revealHistory: (id: number) => call<boolean>("reveal_history", id),
  openHistory: (id: number, confirmed = false) => call<boolean>("open_history", id, confirmed),
  searchHistory: (params: { query: string; kind: string; status: string; limit: number; offset: number }) =>
    call<{ items: HistoryEntry[]; total: number }>("search_history", params),
  clearHistory: () => call<number>("clear_history"),
  deleteHistory: (ids: number[]) => call<number>("delete_history", ids),
  updateSettings: (patch: Partial<Settings>) => call<Settings>("update_settings", patch),
  chooseFolder: (initial: string) => call<string | null>("choose_folder", initial),
  importFile: () => call<{ name: string; text: string } | null>("import_url_file"),
  readClipboard: () => call<string>("read_clipboard"),
  copyText: (text: string) => call<boolean>("copy_text", text),
  exportData: (kind: "results" | "failed") => call<string | null>("export_data", kind),
  storageInfo: () => call<StorageInfo>("storage_info"),
  cleanTemp: (includePaused: boolean) => call<number>("clean_temp", includePaused),
  diagnostics: () => call<Diagnostics>("get_diagnostics"),
  openLogs: () => call<boolean>("open_logs_folder"),
  openPartial: () => call<boolean>("open_partial_folder"),
  openDownloads: () => call<boolean>("open_download_folder"),
};
