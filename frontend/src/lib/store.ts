import { create } from "zustand";
import { api, ApiError } from "./api";
import type {
  Bootstrap,
  Capabilities,
  Collection,
  DownloadOptions,
  Job,
  Notice,
  PreviewItem,
  PushPayload,
  Settings,
  Stats,
} from "./types";

export type Page = "home" | "downloads" | "collections" | "history" | "settings";

export interface Toast {
  id: number;
  kind: Notice["kind"];
  message: string;
}

const EMPTY_STATS: Stats = {
  counts: {
    queued: 0,
    downloading: 0,
    processing: 0,
    paused: 0,
    interrupted: 0,
    completed: 0,
    failed: 0,
    cancelled: 0,
  },
  active: 0,
  queued: 0,
  total: 0,
  speed: 0,
  running: 0,
};

interface AppState {
  status: "loading" | "ready" | "error";
  fatal: string | null;
  app: Bootstrap["app"] | null;
  capabilities: Capabilities | null;
  settings: Settings | null;
  jobs: Record<string, Job>;
  collections: Collection[];
  preview: Record<string, PreviewItem>;
  selection: Record<string, boolean>;
  playlistSelections: Record<string, string[] | null>;
  stats: Stats;
  page: Page;
  toasts: Toast[];
  clipboard: PushPayload["clipboard"] | null;
  historyVersion: number;
  options: DownloadOptions;
  destination: string;

  init: () => Promise<void>;
  resync: () => Promise<void>;
  applyPush: (payload: PushPayload) => void;
  setPage: (page: Page) => void;
  toast: (kind: Toast["kind"], message: string) => void;
  dismissToast: (id: number) => void;
  addPreview: (items: PreviewItem[]) => void;
  setSelected: (ids: string[], selected: boolean) => void;
  setPlaylistSelection: (id: string, entries: string[] | null) => void;
  setOptions: (patch: Partial<DownloadOptions>) => void;
  setDestination: (path: string) => void;
  setSettings: (settings: Settings) => void;
  dismissClipboard: () => void;
}

let toastId = 0;

function defaultSelected(item: PreviewItem): boolean {
  if (item.status === "blocked") return false;
  if (item.in_queue) return false;
  if (item.downloaded_before) return false;
  if (item.status === "error" && item.error && !item.error.retryable) return false;
  return true;
}

function indexBy<T extends { id: string }>(items: T[]): Record<string, T> {
  const result: Record<string, T> = {};
  for (const item of items) result[item.id] = item;
  return result;
}

export const useStore = create<AppState>((set, get) => ({
  status: "loading",
  fatal: null,
  app: null,
  capabilities: null,
  settings: null,
  jobs: {},
  collections: [],
  preview: {},
  selection: {},
  playlistSelections: {},
  stats: EMPTY_STATS,
  page: "home",
  toasts: [],
  clipboard: null,
  historyVersion: 0,
  options: { quality: "best", video_format: "mp4", audio_format: "m4a" },
  destination: "",

  init: async () => {
    window.__SD_PUSH__ = (payload) => get().applyPush(payload);
    try {
      const boot = await api.bootstrap();
      const selection: Record<string, boolean> = {};
      for (const item of boot.preview) selection[item.id] = defaultSelected(item);
      set({
        status: "ready",
        app: boot.app,
        capabilities: boot.capabilities,
        settings: boot.settings,
        jobs: indexBy(boot.jobs),
        collections: boot.collections,
        preview: indexBy(boot.preview),
        selection,
        stats: boot.stats,
        options: {
          quality: boot.settings.default_quality,
          video_format: boot.settings.default_video_format,
          audio_format: boot.settings.default_audio_format,
        },
        destination: boot.settings.download_dir,
      });
    } catch (error) {
      set({
        status: "error",
        fatal: error instanceof ApiError ? error.message : "The app couldn't start its download engine.",
      });
    }
  },

  resync: async () => {
    try {
      const state = await api.state();
      set((s) => {
        const selection = { ...s.selection };
        for (const item of state.preview) {
          if (!(item.id in selection)) selection[item.id] = defaultSelected(item);
        }
        return {
          settings: state.settings,
          capabilities: state.capabilities,
          jobs: indexBy(state.jobs),
          collections: state.collections,
          preview: indexBy(state.preview),
          selection,
          stats: state.stats,
        };
      });
    } catch {
      /* the next push will catch up */
    }
  },

  applyPush: (payload) => {
    set((s) => {
      const next: Partial<AppState> = {};
      if (payload.stats) next.stats = payload.stats;
      if (payload.jobs || payload.removed_jobs) {
        const jobs = { ...s.jobs };
        for (const job of payload.jobs ?? []) jobs[job.id] = job;
        for (const id of payload.removed_jobs ?? []) delete jobs[id];
        next.jobs = jobs;
      }
      if (payload.collections) next.collections = payload.collections;
      if (payload.preview || payload.removed_preview) {
        const preview = { ...s.preview };
        const selection = { ...s.selection };
        for (const item of payload.preview ?? []) {
          const before = preview[item.id];
          preview[item.id] = item;
          if (!(item.id in selection)) selection[item.id] = defaultSelected(item);
          else if (before && before.status !== "error" && item.status === "error" && !defaultSelected(item)) {
            selection[item.id] = false;
          }
        }
        for (const id of payload.removed_preview ?? []) {
          delete preview[id];
          delete selection[id];
        }
        next.preview = preview;
        next.selection = selection;
      }
      if (payload.settings) next.settings = payload.settings;
      if (payload.history_changed) next.historyVersion = s.historyVersion + 1;
      if (payload.clipboard) next.clipboard = payload.clipboard;
      return next;
    });
    for (const notice of payload.notices ?? []) get().toast(notice.kind, notice.message);
  },

  setPage: (page) => set({ page }),

  toast: (kind, message) => {
    const id = ++toastId;
    set((s) => ({ toasts: [...s.toasts.slice(-3), { id, kind, message }] }));
    window.setTimeout(() => get().dismissToast(id), kind === "error" ? 8000 : 4500);
  },

  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),

  addPreview: (items) =>
    set((s) => {
      const preview = { ...s.preview };
      const selection = { ...s.selection };
      for (const item of items) {
        preview[item.id] = item;
        selection[item.id] = defaultSelected(item);
      }
      return { preview, selection };
    }),

  setSelected: (ids, selected) =>
    set((s) => {
      const selection = { ...s.selection };
      for (const id of ids) selection[id] = selected;
      return { selection };
    }),

  setPlaylistSelection: (id, entries) =>
    set((s) => ({ playlistSelections: { ...s.playlistSelections, [id]: entries } })),

  setOptions: (patch) => set((s) => ({ options: { ...s.options, ...patch } })),
  setDestination: (path) => set({ destination: path }),
  setSettings: (settings) => set({ settings }),
  dismissClipboard: () => set({ clipboard: null }),
}));

export const selectSortedJobs = (jobs: Record<string, Job>) =>
  Object.values(jobs).sort((a, b) => a.order - b.order);

export const selectSortedPreview = (preview: Record<string, PreviewItem>) =>
  Object.values(preview).sort((a, b) => a.order - b.order);

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
