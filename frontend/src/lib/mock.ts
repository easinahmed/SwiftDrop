// DEV-ONLY preview bridge used when the UI runs in a plain browser (`npm run dev`).
// It never ships in production builds (imported only behind import.meta.env.DEV) and the
// UI shows a "Preview mode" banner while it is active. It simulates engine events so the
// interface can be developed and reviewed without the Python download engine.

import type {
  Bootstrap,
  Collection,
  HistoryEntry,
  Job,
  PreviewItem,
  PushPayload,
  Settings,
  Stats,
} from "./types";

type Envelope = { ok: true; data: unknown } | { ok: false; error: string };

const settings: Settings = {
  download_dir: "/Users/demo/Downloads",
  remember_destination: true,
  organize_by_type: false,
  playlist_subfolders: true,
  max_concurrent: 3,
  connections_per_download: 4,
  theme: "system",
  default_quality: "best",
  default_video_format: "mp4",
  default_audio_format: "m4a",
  notifications: true,
  clipboard_monitoring: false,
  resume_on_launch: false,
  open_at_login: false,
  bandwidth_limit_kbps: 0,
  cleanup_temp_on_quit: false,
  skip_already_downloaded: true,
  auto_inspect: true,
  show_thumbnails: true,
  save_history: true,
  cookies_from_browser: "",
  verbose_logging: false,
};

let counter = 0;
const id = () => (++counter).toString(16).padStart(16, "0");
const preview = new Map<string, PreviewItem>();
const jobs = new Map<string, Job>();
const collections = new Map<string, Collection>();
const history: HistoryEntry[] = [];

function push(payload: PushPayload) {
  window.setTimeout(() => window.__SD_PUSH__?.({ ...payload, stats: stats() }), 0);
}

function stats(): Stats {
  const counts = { queued: 0, downloading: 0, processing: 0, paused: 0, interrupted: 0, completed: 0, failed: 0, cancelled: 0 };
  let speed = 0;
  for (const j of jobs.values()) {
    counts[j.state] += 1;
    speed += j.state === "downloading" ? j.speed ?? 0 : 0;
  }
  return { counts, active: counts.downloading + counts.processing, queued: counts.queued, total: jobs.size, speed, running: counts.downloading };
}

function classify(url: string): PreviewItem {
  const host = new URL(url).hostname.replace(/^www\./, "");
  const ext = url.split("?")[0].split(".").pop()?.toLowerCase() ?? "";
  const kind = ["mp4", "mov", "webm"].includes(ext) ? "video" : ["mp3", "m4a"].includes(ext) ? "audio" : ["jpg", "png", "webp"].includes(ext) ? "image" : "unknown";
  const blocked = host.includes("spotify.com");
  const playlist = url.includes("playlist") || url.includes("list=");
  return {
    id: id(),
    url,
    source: host,
    status: blocked ? "blocked" : "pending",
    link: {
      provider: blocked ? "blocked" : kind !== "unknown" ? "direct" : "ytdlp",
      kind: kind as PreviewItem["kind"],
      label: blocked ? "Spotify" : kind !== "unknown" ? `${ext.toUpperCase()} file` : "Video site",
      extractor: null,
      playlist_hint: playlist,
      blocked: blocked
        ? {
            code: "drm",
            title: "Spotify isn't supported",
            message: "Spotify music and audiobooks are DRM-protected streams, so they can't be saved as files.",
            hint: "Use “Download” in the Spotify app (Premium) for offline listening.",
            detail: "",
            retryable: false,
          }
        : null,
    },
    info: null,
    kind: kind as PreviewItem["kind"],
    title: null,
    error: null,
    in_queue: null,
    downloaded_before: null,
    order: counter,
  };
}

function inspect(item: PreviewItem) {
  window.setTimeout(() => {
    item.status = "inspecting";
    push({ preview: [item] });
  }, 200 + Math.random() * 400);
  window.setTimeout(() => {
    const playlist = item.link.playlist_hint;
    item.status = "ready";
    item.title = playlist ? "Nature Documentary Collection" : `Sample media ${item.order}`;
    item.kind = item.kind === "unknown" ? "video" : item.kind;
    item.info = {
      provider: item.link.provider,
      title: item.title,
      kind: item.kind,
      extractor: playlist ? "Video site" : null,
      thumbnail: null,
      duration: item.kind === "image" ? null : 120 + item.order * 13,
      size: playlist ? null : 4_000_000 + item.order * 1_300_000,
      size_is_estimate: false,
      filename: null,
      heights: item.kind === "video" ? [360, 720, 1080] : [],
      has_audio_only: true,
      is_playlist: playlist,
      entry_count: playlist ? 8 : 0,
      entries_truncated: false,
    };
    push({ preview: [item] });
  }, 900 + Math.random() * 1200);
}

function tick() {
  let active = 0;
  const changed: Job[] = [];
  for (const job of [...jobs.values()].sort((a, b) => a.order - b.order)) {
    if (job.state === "downloading") active += 1;
  }
  for (const job of [...jobs.values()].sort((a, b) => a.order - b.order)) {
    if (job.state === "queued" && active < settings.max_concurrent) {
      job.state = "downloading";
      job.phase = "Downloading";
      active += 1;
      changed.push(job);
    } else if (job.state === "downloading") {
      const total = job.total_bytes ?? 20_000_000;
      job.speed = 2_000_000 + Math.random() * 1_500_000;
      job.downloaded_bytes = Math.min(total, job.downloaded_bytes + job.speed / 4);
      job.progress = job.downloaded_bytes / total;
      job.eta = (total - job.downloaded_bytes) / job.speed;
      if (job.downloaded_bytes >= total) {
        if (job.url.includes("fail")) {
          job.state = "failed";
          job.error = { code: "not_found", title: "Not found", message: "The file or page doesn't exist (HTTP 404).", hint: "The link may have been removed or mistyped.", detail: "HTTP 404", retryable: false };
        } else {
          job.state = "completed";
          job.file_size = total;
          job.filepath = `${settings.download_dir}/${job.title}.mp4`;
          job.filename = `${job.title}.mp4`;
          history.unshift({
            id: history.length + 1, job_id: job.id, url: job.url, title: job.title, source: job.source, kind: job.kind,
            status: "completed", filepath: job.filepath, file_size: total, quality: job.quality_label, error_code: null,
            error_message: null, thumbnail: null, collection_title: null, duration: job.duration, sha256: null,
            finished_at: Date.now() / 1000, file_exists: true,
          });
        }
        job.speed = null;
        job.eta = null;
        job.finished_at = Date.now() / 1000;
      }
      changed.push(job);
    }
  }
  if (changed.length) push({ jobs: changed, collections: [...collections.values()].map(withStats), history_changed: true });
}

function withStats(c: Collection): Collection {
  const members = [...jobs.values()].filter((j) => j.collection_id === c.id);
  const counts = { queued: 0, downloading: 0, processing: 0, paused: 0, interrupted: 0, completed: 0, failed: 0, cancelled: 0 };
  for (const m of members) counts[m.state] += 1;
  return {
    ...c,
    item_ids: members.map((m) => m.id),
    counts,
    count: members.length,
    completed: counts.completed,
    progress: members.length ? members.reduce((s, m) => s + (m.state === "completed" ? 1 : m.progress ?? 0), 0) / members.length : 0,
  };
}

function makeJob(item: PreviewItem, title: string, extra: Partial<Job> = {}): Job {
  return {
    id: id(), url: item.url, destination: settings.download_dir, options: { quality: "best", video_format: "mp4", audio_format: "m4a" },
    provider: item.link.provider, title, source: item.source, kind: item.kind === "unknown" ? "video" : item.kind, state: "queued",
    created_at: Date.now() / 1000, order: counter, collection_id: null, playlist_index: null, thumbnail: null, extractor: item.info?.extractor ?? null,
    duration: item.info?.duration ?? null, phase: "", downloaded_bytes: 0, total_bytes: item.info?.size ?? 18_000_000, total_is_estimate: false,
    speed: null, connections: null, eta: null, progress: null, filename: null, filepath: null, file_size: null, quality_label: "Best · MP4", error: null,
    attempts: 0, started_at: null, finished_at: null, resumable: true, note: null, file_missing: false, sha256: null, ...extra,
  };
}

const handlers: Record<string, (...args: never[]) => unknown> = {
  get_bootstrap: (): Bootstrap => ({
    app: { name: "SwiftDrop", version: "1.0.0", bundle_id: "dev.preview", frozen: false },
    settings,
    jobs: [...jobs.values()],
    collections: [],
    preview: [...preview.values()],
    stats: stats(),
    capabilities: { sites: true, ffmpeg: true, login_item: false, js_runtime: "node" },
  }),
  get_state: () => ({ settings, jobs: [...jobs.values()], collections: [...collections.values()].map(withStats), preview: [...preview.values()], stats: stats(), capabilities: { sites: true, ffmpeg: true, login_item: false, js_runtime: "node" } }),
  analyze_text: (text: string) => {
    const urls = Array.from(new Set(text.match(/https?:\/\/[^\s]+/g) ?? []));
    const added = urls.map(classify);
    for (const item of added) {
      preview.set(item.id, item);
      if (item.status === "pending") inspect(item);
    }
    return { added, duplicates: 0, invalid: [], invalid_count: 0, truncated: false };
  },
  inspect_preview: () => 0,
  remove_preview: (ids: string[]) => {
    ids.forEach((i) => preview.delete(i));
    push({ removed_preview: ids });
    return ids.length;
  },
  clear_preview: () => {
    const ids = [...preview.keys()];
    preview.clear();
    push({ removed_preview: ids });
    return ids.length;
  },
  get_playlist_entries: () =>
    Array.from({ length: 8 }, (_, i) => ({ id: `e${i}`, url: `https://example.com/v${i}`, title: `Episode ${i + 1}: The Wild Coast`, index: i + 1, duration: 600 + i * 31, thumbnail: null, available: i !== 5 })),
  start_downloads: (request: { items: { id: string; entries: string[] | null }[] }) => {
    const created: Job[] = [];
    for (const { id: itemId, entries } of request.items) {
      const item = preview.get(itemId);
      if (!item || item.status === "blocked") continue;
      if (item.info?.is_playlist) {
        const collection: Collection = { id: id(), title: item.info.title, url: item.url, source: item.source, destination: settings.download_dir, extractor: "Video site", thumbnail: null, created_at: Date.now() / 1000, total_entries: 8, item_ids: [], counts: {} as Collection["counts"], count: 0, completed: 0, progress: 0, downloaded_bytes: 0 };
        collections.set(collection.id, collection);
        const picks = entries ?? ["e0", "e1", "e2", "e3", "e4", "e6", "e7"];
        picks.forEach((e, n) => created.push(makeJob(item, `Episode ${Number(e.slice(1)) + 1}: The Wild Coast`, { collection_id: collection.id, playlist_index: n + 1 })));
      } else {
        created.push(makeJob(item, item.title ?? item.url));
      }
      preview.delete(itemId);
    }
    created.forEach((j) => jobs.set(j.id, j));
    push({ jobs: created, removed_preview: request.items.map((i) => i.id), collections: [...collections.values()].map(withStats) });
    return { created: created.length, skipped: [], job_ids: created.map((j) => j.id) };
  },
  job_action: (action: string, ids: string[]) => {
    const changed: Job[] = [];
    for (const jobId of ids) {
      const job = jobs.get(jobId);
      if (!job) continue;
      if (action === "pause" && ["queued", "downloading"].includes(job.state)) job.state = "paused";
      else if (action === "resume" && ["paused", "interrupted"].includes(job.state)) job.state = "queued";
      else if (action === "cancel") job.state = "cancelled";
      else if (action === "retry") Object.assign(job, { state: "queued", error: null, downloaded_bytes: 0, progress: null });
      else if (action === "remove") {
        jobs.delete(jobId);
        push({ removed_jobs: [jobId] });
        continue;
      }
      job.speed = null;
      changed.push(job);
    }
    push({ jobs: changed });
    return ids.length;
  },
  queue_action: (action: string) => {
    const all = [...jobs.values()];
    const pick = (s: string[]) => all.filter((j) => s.includes(j.state)).map((j) => j.id);
    if (action === "pause_all") return handlers.job_action("pause" as never, pick(["queued", "downloading"]) as never);
    if (action === "resume_all") return handlers.job_action("resume" as never, pick(["paused", "interrupted"]) as never);
    if (action === "retry_failed") return handlers.job_action("retry" as never, pick(["failed"]) as never);
    return handlers.job_action("remove" as never, pick(["completed", "cancelled"]) as never);
  },
  reveal_job: () => true,
  open_job: () => true,
  reveal_history: () => true,
  open_history: () => true,
  search_history: (params: { query: string }) => {
    const items = history.filter((h) => h.title.toLowerCase().includes(params.query.toLowerCase()));
    return { items, total: items.length };
  },
  clear_history: () => history.splice(0).length,
  delete_history: () => 1,
  get_settings: () => settings,
  update_settings: (patch: Partial<Settings>) => {
    Object.assign(settings, patch);
    return settings;
  },
  choose_folder: () => "/Users/demo/Movies",
  import_url_file: () => ({ name: "links.txt", text: "https://example.com/a.mp4\nhttps://example.com/b.mp3" }),
  read_clipboard: () => "https://example.com/clip.mp4",
  copy_text: () => true,
  export_data: () => "/Users/demo/Downloads/SwiftDrop downloads.csv",
  storage_info: () => ({ partial_bytes: 48_200_000, partial_dir: "/Users/demo/Library/Application Support/SwiftDrop/partial", download_dir_free: 120_000_000_000 }),
  clean_temp: () => 48_200_000,
  get_diagnostics: () => ({ app: "SwiftDrop 1.0.0", python: "3.14.0", macos: "15.0", arch: "arm64", yt_dlp: "2026.08.19", ffmpeg: { path: "/Applications/SwiftDrop.app/Contents/Frameworks/bin/ffmpeg", version: "7.1.1", bundled: true }, ffprobe: null, js_runtime: { name: "node", version: "25.9.0", path: "/opt/homebrew/bin/node" }, paths: { data: "", logs: "", partial: "" }, frozen: false, pid: 1 }),
  open_logs_folder: () => true,
  open_partial_folder: () => true,
  open_download_folder: () => true,
};

export function createMockBridge() {
  (window as { __SD_MOCK__?: boolean }).__SD_MOCK__ = true;
  window.setInterval(tick, 250);
  const bridge: Record<string, (...args: unknown[]) => Promise<Envelope>> = {};
  for (const [name, fn] of Object.entries(handlers)) {
    bridge[name] = async (...args: unknown[]) => {
      try {
        return { ok: true, data: (fn as (...a: unknown[]) => unknown)(...args) };
      } catch (error) {
        return { ok: false, error: String(error) };
      }
    };
  }
  return bridge;
}
