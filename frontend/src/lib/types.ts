// Shapes produced by the Python side (swiftdrop/models.py, service.py, preview.py).

export type MediaKind = "video" | "audio" | "image" | "other" | "unknown";

export type JobState =
  | "queued"
  | "downloading"
  | "processing"
  | "paused"
  | "interrupted"
  | "completed"
  | "failed"
  | "cancelled";

export type Quality = "best" | "2160" | "1440" | "1080" | "720" | "480" | "360" | "audio";
export type VideoFormat = "auto" | "mp4" | "mkv" | "webm";
export type AudioFormat = "auto" | "m4a" | "mp3" | "opus" | "flac" | "wav";
export type Theme = "system" | "light" | "dark";

export interface DownloadOptions {
  quality: Quality;
  video_format: VideoFormat;
  audio_format: AudioFormat;
}

export interface ErrorInfo {
  code: string;
  title: string;
  message: string;
  hint: string;
  detail: string;
  retryable: boolean;
}

export interface Job {
  id: string;
  url: string;
  destination: string;
  options: DownloadOptions;
  provider: string;
  title: string;
  source: string;
  kind: MediaKind;
  state: JobState;
  created_at: number;
  order: number;
  collection_id: string | null;
  playlist_index: number | null;
  thumbnail: string | null;
  extractor: string | null;
  duration: number | null;
  phase: string;
  downloaded_bytes: number;
  total_bytes: number | null;
  total_is_estimate: boolean;
  speed: number | null;
  connections: number | null;
  eta: number | null;
  progress: number | null;
  filename: string | null;
  filepath: string | null;
  file_size: number | null;
  quality_label: string | null;
  error: ErrorInfo | null;
  attempts: number;
  started_at: number | null;
  finished_at: number | null;
  resumable: boolean | null;
  note: string | null;
  file_missing: boolean;
  sha256: string | null;
}

export interface Collection {
  id: string;
  title: string;
  url: string;
  source: string;
  destination: string;
  extractor: string | null;
  thumbnail: string | null;
  created_at: number;
  total_entries: number | null;
  item_ids: string[];
  counts: Record<JobState, number>;
  count: number;
  completed: number;
  progress: number;
  downloaded_bytes: number;
}

export interface LinkInfo {
  provider: "direct" | "ytdlp" | "auto" | "blocked";
  kind: MediaKind;
  label: string;
  extractor: string | null;
  playlist_hint: boolean;
  blocked: ErrorInfo | null;
}

export interface InspectInfo {
  provider: string;
  title: string;
  kind: MediaKind;
  extractor: string | null;
  thumbnail: string | null;
  duration: number | null;
  size: number | null;
  size_is_estimate: boolean;
  filename: string | null;
  heights: number[];
  has_audio_only: boolean;
  is_playlist: boolean;
  entry_count: number;
  entries_truncated: boolean;
}

export interface PreviewItem {
  id: string;
  url: string;
  source: string;
  status: "pending" | "inspecting" | "ready" | "error" | "blocked";
  link: LinkInfo;
  info: InspectInfo | null;
  kind: MediaKind;
  title: string | null;
  error: ErrorInfo | null;
  in_queue: string | null;
  downloaded_before: { filepath: string; finished_at: number; title: string } | null;
  order: number;
}

export interface PlaylistEntry {
  id: string;
  url: string;
  title: string;
  index: number;
  duration: number | null;
  thumbnail: string | null;
  available: boolean;
}

export interface Settings {
  download_dir: string;
  remember_destination: boolean;
  organize_by_type: boolean;
  playlist_subfolders: boolean;
  max_concurrent: number;
  connections_per_download: number;
  theme: Theme;
  default_quality: Quality;
  default_video_format: VideoFormat;
  default_audio_format: AudioFormat;
  notifications: boolean;
  clipboard_monitoring: boolean;
  resume_on_launch: boolean;
  open_at_login: boolean;
  bandwidth_limit_kbps: number;
  cleanup_temp_on_quit: boolean;
  skip_already_downloaded: boolean;
  auto_inspect: boolean;
  show_thumbnails: boolean;
  save_history: boolean;
  cookies_from_browser: string;
  verbose_logging: boolean;
}

export interface Stats {
  counts: Record<JobState, number>;
  active: number;
  queued: number;
  total: number;
  speed: number;
  running: number;
}

export interface Capabilities {
  sites: boolean;
  ffmpeg: boolean;
  login_item: boolean;
  js_runtime: string | null;
}

export interface Bootstrap {
  app: { name: string; version: string; bundle_id: string; frozen: boolean };
  settings: Settings;
  jobs: Job[];
  collections: Collection[];
  preview: PreviewItem[];
  stats: Stats;
  capabilities: Capabilities;
}

export interface AnalyzeResult {
  added: PreviewItem[];
  duplicates: number;
  invalid: { url: string; reason: string }[];
  invalid_count: number;
  truncated: boolean;
}

export interface StartResult {
  created: number;
  skipped: { url: string; reason: string }[];
  job_ids: string[];
}

export interface HistoryEntry {
  id: number;
  job_id: string;
  url: string;
  title: string;
  source: string;
  kind: MediaKind;
  status: "completed" | "failed" | "cancelled";
  filepath: string | null;
  file_size: number | null;
  quality: string | null;
  error_code: string | null;
  error_message: string | null;
  thumbnail: string | null;
  collection_title: string | null;
  duration: number | null;
  sha256: string | null;
  finished_at: number;
  file_exists: boolean;
}

export interface Notice {
  kind: "success" | "warning" | "error" | "info";
  message: string;
}

export interface PushPayload {
  stats?: Stats;
  jobs?: Job[];
  removed_jobs?: string[];
  collections?: Collection[];
  preview?: PreviewItem[];
  removed_preview?: string[];
  settings?: Settings;
  history_changed?: boolean;
  clipboard?: { count: number; urls: string[]; at: number };
  notices?: Notice[];
}

export interface Diagnostics {
  app: string;
  python: string;
  macos: string;
  arch: string;
  yt_dlp: string | null;
  ffmpeg: { path: string | null; version: string | null; bundled: boolean };
  ffprobe: string | null;
  js_runtime: { name: string; version: string; path: string } | null;
  paths: { data: string; logs: string; partial: string };
  frozen: boolean;
  pid: number;
}

export interface StorageInfo {
  partial_bytes: number;
  partial_dir: string;
  download_dir_free: number | null;
}
