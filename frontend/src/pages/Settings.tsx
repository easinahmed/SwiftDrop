import { useEffect, useState, type ReactNode } from "react";
import { Copy, Folder, FolderOpen, HardDrive, ScrollText, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { formatBytes, shortPath } from "../lib/format";
import { errorMessage, useStore } from "../lib/store";
import type {
  AudioFormat,
  Capabilities,
  Diagnostics,
  Quality,
  Settings,
  StorageInfo,
  Theme,
  VideoFormat,
} from "../lib/types";
import { Badge, Button, PageHeader, Segmented, Select, Toggle } from "../components/ui";
import { BOOKMARKLET, Bookmarklet } from "../components/Bookmarklet";

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="animate-fade-in">
      <h2 className="mb-1 px-1 text-[12px] font-semibold uppercase tracking-[0.06em] text-ink-3">{title}</h2>
      {description && <p className="mb-2 px-1 text-[12px] text-ink-3">{description}</p>}
      <div className="card divide-y divide-line">{children}</div>
    </section>
  );
}

function Row({ label, description, children }: { label: string; description?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-6 px-4 py-3">
      <div className="min-w-0">
        <div className="text-[13px] font-medium text-ink">{label}</div>
        {description && <div className="mt-0.5 text-[12px] text-ink-3">{description}</div>}
      </div>
      <div className="flex shrink-0 items-center gap-2">{children}</div>
    </div>
  );
}

function BandwidthInput({ value, onCommit }: { value: number; onCommit: (kbps: number) => void }) {
  // Re-mounted (via key) whenever the saved value changes, so local text never goes stale.
  const [text, setText] = useState(value ? String(+(value / 1024).toFixed(2)) : "");
  const commit = () => {
    const mb = parseFloat(text.replace(",", "."));
    const kbps = Number.isFinite(mb) && mb > 0 ? Math.max(1, Math.round(mb * 1024)) : 0;
    if (kbps !== value) onCommit(kbps);
  };
  return (
    <div className="flex items-center gap-2">
      <input
        value={text}
        inputMode="decimal"
        placeholder="Unlimited"
        aria-label="Bandwidth limit in megabytes per second"
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => e.key === "Enter" && commit()}
        className="h-8 w-[110px] rounded-[8px] border border-line-strong bg-surface px-3 text-right text-[13px] tabular-nums outline-none focus:border-accent"
      />
      <span className="text-[12px] text-ink-3">MB/s</span>
    </div>
  );
}

function PopupSection({
  settings,
  capabilities,
  update,
}: {
  settings: Settings;
  capabilities: Capabilities | null;
  update: (patch: Partial<Settings>) => Promise<void>;
}) {
  const toast = useStore((s) => s.toast);
  const windows = capabilities?.platform === "windows";

  const copyBookmark = async () => {
    try {
      await api.copyText(BOOKMARKLET);
      toast("success", "Copied. Add it as a bookmark's URL in your browser.");
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const quit = async () => {
    try {
      await api.quitApp();
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  return (
    <Section title="Pop-up" description="Download from any app or browser without opening SwiftDrop first.">
      <Row
        label="Pop up when I copy a download link"
        description={`Only download and video links trigger it; nothing you copy is saved. While on, closing the window keeps SwiftDrop running ${
          windows ? "in the background (open SwiftDrop again to show it)" : "in the Dock"
        }.`}
      >
        <Toggle
          label="Pop up when I copy a download link"
          checked={settings.clipboard_popup}
          onChange={(v) => update({ clipboard_popup: v })}
        />
      </Row>
      <Row
        label="Send to SwiftDrop"
        description="Drag this to your bookmarks bar. On any video or download page, click it to send the page to SwiftDrop."
      >
        <Bookmarklet />
        <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={copyBookmark} title="Copy the bookmark's address">
          Copy
        </Button>
      </Row>
      {windows && (
        <Row label="Quit SwiftDrop" description="Stops the pop-up and pauses running downloads until you open SwiftDrop again.">
          <Button size="sm" onClick={quit}>
            Quit
          </Button>
        </Row>
      )}
    </Section>
  );
}

export function SettingsPage() {
  const settings = useStore((s) => s.settings);
  const setSettings = useStore((s) => s.setSettings);
  const setDestination = useStore((s) => s.setDestination);
  const capabilities = useStore((s) => s.capabilities);
  const app = useStore((s) => s.app);
  const toast = useStore((s) => s.toast);
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [diag, setDiag] = useState<Diagnostics | null>(null);

  const refreshStorage = () => api.storageInfo().then(setStorage).catch(() => undefined);
  useEffect(() => {
    void refreshStorage();
    api.diagnostics().then(setDiag).catch(() => undefined);
  }, []);

  if (!settings) return null;

  const update = async (patch: Partial<Settings>) => {
    try {
      const next = await api.updateSettings(patch);
      setSettings(next);
      if (patch.download_dir) setDestination(next.download_dir);
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const chooseFolder = async () => {
    try {
      const folder = await api.chooseFolder(settings.download_dir);
      if (folder) await update({ download_dir: folder });
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const clean = async (includePaused: boolean) => {
    try {
      const freed = await api.cleanTemp(includePaused);
      toast("success", freed ? `Freed ${formatBytes(freed)}` : "Nothing to clean up");
      void refreshStorage();
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const copyDiagnostics = async () => {
    if (!diag) return;
    try {
      await api.copyText(JSON.stringify(diag, null, 2));
      toast("success", "Diagnostics copied");
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Settings" subtitle="Changes are saved automatically." />
      <div className="min-h-0 flex-1 overflow-auto px-8 pb-10">
        <div className="mx-auto max-w-[760px] space-y-7">
          <Section title="Downloads">
            <Row label="Save downloads to" description={<span className="selectable">{shortPath(settings.download_dir)}</span>}>
              <Button size="sm" icon={<Folder className="size-3.5" />} onClick={chooseFolder}>
                Choose…
              </Button>
              <Button size="sm" variant="ghost" icon={<FolderOpen className="size-3.5" />} onClick={() => api.openDownloads()}>
                Open
              </Button>
            </Row>
            <Row label="Remember the last folder used" description="When you pick a different folder on the download screen, make it the new default.">
              <Toggle label="Remember destination" checked={settings.remember_destination} onChange={(v) => update({ remember_destination: v })} />
            </Row>
            <Row label="Sort into folders by type" description="Videos, Audio, Images and Other subfolders inside the destination.">
              <Toggle label="Organize by type" checked={settings.organize_by_type} onChange={(v) => update({ organize_by_type: v })} />
            </Row>
            <Row label="Put playlists in their own folder" description="Each playlist or album is saved in a folder named after it.">
              <Toggle label="Playlist folders" checked={settings.playlist_subfolders} onChange={(v) => update({ playlist_subfolders: v })} />
            </Row>
            <Row label="Skip links downloaded before" description="Links whose file still exists are unselected in the preview, and skipped in playlists.">
              <Toggle label="Skip already downloaded" checked={settings.skip_already_downloaded} onChange={(v) => update({ skip_already_downloaded: v })} />
            </Row>
          </Section>

          <Section title="Quality" description="Defaults for video and audio sites. Direct files are always saved as published.">
            <Row label="Default quality">
              <Select<Quality>
                label="Default quality"
                value={settings.default_quality}
                onChange={(v) => update({ default_quality: v })}
                className="w-[170px]"
                options={[
                  { value: "best", label: "Best available" },
                  { value: "2160", label: "4K (2160p)" },
                  { value: "1440", label: "1440p" },
                  { value: "1080", label: "1080p" },
                  { value: "720", label: "720p" },
                  { value: "480", label: "480p" },
                  { value: "360", label: "360p" },
                  { value: "audio", label: "Audio only" },
                ]}
              />
            </Row>
            <Row label="Video format" description="MP4 plays everywhere on Apple devices.">
              <Select<VideoFormat>
                label="Default video format"
                value={settings.default_video_format}
                onChange={(v) => update({ default_video_format: v })}
                className="w-[260px]"
                options={[
                  { value: "mp4", label: "MP4 (plays in QuickTime)" },
                  { value: "mkv", label: "Original quality (MKV, may need VLC)" },
                  { value: "webm", label: "WebM" },
                  { value: "auto", label: "Original" },
                ]}
              />
            </Row>
            <Row label="Audio format" description="Used when downloading audio only.">
              <Select<AudioFormat>
                label="Default audio format"
                value={settings.default_audio_format}
                onChange={(v) => update({ default_audio_format: v })}
                className="w-[170px]"
                options={[
                  { value: "m4a", label: "M4A (AAC)" },
                  { value: "mp3", label: "MP3" },
                  { value: "opus", label: "Opus" },
                  { value: "flac", label: "FLAC" },
                  { value: "wav", label: "WAV" },
                  { value: "auto", label: "Original" },
                ]}
              />
            </Row>
          </Section>

          <Section title="Performance">
            <Row label="Simultaneous downloads" description="Other links wait in the queue. Lower this if a site rate-limits you.">
              <input
                type="range"
                min={1}
                max={10}
                value={settings.max_concurrent}
                aria-label="Simultaneous downloads"
                onChange={(e) => update({ max_concurrent: Number(e.target.value) })}
                className="w-[160px] accent-[var(--accent)]"
              />
              <span className="w-5 text-right text-[13px] font-semibold tabular-nums">{settings.max_concurrent}</span>
            </Row>
            <Row label="Connections per download" description="More connections can be faster; servers that limit connections are handled automatically.">
              <input
                type="range"
                min={1}
                max={16}
                value={settings.connections_per_download}
                aria-label="Connections per download"
                onChange={(e) => update({ connections_per_download: Number(e.target.value) })}
                className="w-[160px] accent-[var(--accent)]"
              />
              <span className="w-5 text-right text-[13px] font-semibold tabular-nums">{settings.connections_per_download}</span>
            </Row>
            <Row label="Bandwidth limit" description="Shared by all downloads. Leave empty for unlimited.">
              <BandwidthInput key={settings.bandwidth_limit_kbps} value={settings.bandwidth_limit_kbps} onCommit={(kbps) => update({ bandwidth_limit_kbps: kbps })} />
            </Row>
          </Section>

          <Section title="Appearance & behavior">
            <Row label="Theme">
              <Segmented<Theme>
                label="Theme"
                size="sm"
                value={settings.theme}
                onChange={(v) => update({ theme: v })}
                options={[
                  { value: "system", label: "System" },
                  { value: "light", label: "Light" },
                  { value: "dark", label: "Dark" },
                ]}
              />
            </Row>
            <Row label="Notifications" description="Notify when a batch of downloads finishes or fails.">
              <Toggle label="Notifications" checked={settings.notifications} onChange={(v) => update({ notifications: v })} />
            </Row>
            <Row
              label="Offer other copied links in the app"
              description="Off by default. While on, any copied link is offered in a banner inside SwiftDrop — nothing is added without your click, and clipboard contents are never stored."
            >
              <Toggle label="Clipboard monitoring" checked={settings.clipboard_monitoring} onChange={(v) => update({ clipboard_monitoring: v })} />
            </Row>
            <Row label="Fetch link details automatically" description="Look up titles, sizes and playlist items as soon as links are added.">
              <Toggle label="Fetch link details" checked={settings.auto_inspect} onChange={(v) => update({ auto_inspect: v })} />
            </Row>
            <Row label="Resume unfinished downloads on launch" description="Otherwise they wait for you to press Resume.">
              <Toggle label="Resume on launch" checked={settings.resume_on_launch} onChange={(v) => update({ resume_on_launch: v })} />
            </Row>
            <Row
              label="Open at login"
              description={capabilities?.login_item ? "Start SwiftDrop when you log in to your Mac." : "Available in the installed app (macOS 13 or later)."}
            >
              <Toggle
                label="Open at login"
                disabled={!capabilities?.login_item}
                checked={settings.open_at_login}
                onChange={(v) => update({ open_at_login: v })}
              />
            </Row>
          </Section>

          <PopupSection settings={settings} capabilities={capabilities} update={update} />

          <Section title="Privacy">
            <Row
              label="Use browser sign-in"
              description="For media you're allowed to access while signed in (for example your own uploads). Cookies are read from the browser only when a download starts and are never stored or logged. Passwords are never requested."
            >
              <Select
                label="Browser sign-in"
                value={settings.cookies_from_browser}
                onChange={(v) => update({ cookies_from_browser: v })}
                className="w-[140px]"
                options={[
                  { value: "", label: "Off" },
                  { value: "safari", label: "Safari" },
                  { value: "chrome", label: "Chrome" },
                  { value: "firefox", label: "Firefox" },
                  { value: "brave", label: "Brave" },
                  { value: "edge", label: "Edge" },
                  { value: "chromium", label: "Chromium" },
                  { value: "vivaldi", label: "Vivaldi" },
                  { value: "opera", label: "Opera" },
                ]}
              />
            </Row>
            <Row label="Show thumbnails" description="Thumbnails are loaded from the media's own site.">
              <Toggle label="Show thumbnails" checked={settings.show_thumbnails} onChange={(v) => update({ show_thumbnails: v })} />
            </Row>
            <Row label="Keep download history">
              <Toggle label="Save history" checked={settings.save_history} onChange={(v) => update({ save_history: v })} />
            </Row>
            <Row label="Detailed logs" description="Writes extra diagnostic information. Secrets such as tokens and cookies are always removed.">
              <Toggle label="Detailed logs" checked={settings.verbose_logging} onChange={(v) => update({ verbose_logging: v })} />
            </Row>
          </Section>

          <Section title="Storage">
            <Row
              label="Partial downloads"
              description={
                storage
                  ? `${formatBytes(storage.partial_bytes)} used by paused and unfinished downloads${
                      storage.download_dir_free != null ? ` · ${formatBytes(storage.download_dir_free)} free in destination` : ""
                    }`
                  : "Calculating…"
              }
            >
              <Button size="sm" variant="ghost" icon={<HardDrive className="size-3.5" />} onClick={() => api.openPartial()}>
                Show
              </Button>
              <Button size="sm" icon={<Trash2 className="size-3.5" />} onClick={() => clean(false)} title="Remove leftovers that no download can resume from">
                Clean up
              </Button>
            </Row>
            <Row label="Remove all partial data" description="Paused downloads will restart from the beginning.">
              <Button size="sm" variant="ghost" onClick={() => clean(true)}>
                Remove all
              </Button>
            </Row>
            <Row label="Clean up leftovers when quitting">
              <Toggle label="Clean up on quit" checked={settings.cleanup_temp_on_quit} onChange={(v) => update({ cleanup_temp_on_quit: v })} />
            </Row>
          </Section>

          <Section title="About & diagnostics">
            <Row label={`${app?.name ?? "SwiftDrop"} ${app?.version ?? ""}`} description={diag ? `macOS ${diag.macos} · ${diag.arch} · Python ${diag.python}` : undefined}>
              <Button size="sm" variant="ghost" icon={<ScrollText className="size-3.5" />} onClick={() => api.openLogs()}>
                Logs
              </Button>
              <Button size="sm" variant="ghost" icon={<Copy className="size-3.5" />} onClick={copyDiagnostics}>
                Copy diagnostics
              </Button>
            </Row>
            <Row label="Download engine" description={diag?.yt_dlp ? `yt-dlp ${diag.yt_dlp}` : "Site support unavailable"}>
              {capabilities?.sites ? <Badge tone="success">Ready</Badge> : <Badge tone="warning">Direct files only</Badge>}
            </Row>
            <Row
              label="FFmpeg"
              description={
                diag?.ffmpeg.path
                  ? `${diag.ffmpeg.version ?? "unknown version"} · ${diag.ffmpeg.bundled ? "bundled" : shortPath(diag.ffmpeg.path)}`
                  : "Needed to merge high-quality video and convert audio."
              }
            >
              {capabilities?.ffmpeg ? <Badge tone="success">Available</Badge> : <Badge tone="danger">Missing</Badge>}
            </Row>
            <Row
              label="JavaScript runtime"
              description={
                diag?.js_runtime
                  ? `${diag.js_runtime.name} ${diag.js_runtime.version}`
                  : "Optional. Some sites (notably YouTube) need Deno or Node.js 22+ to unlock all formats."
              }
            >
              {diag?.js_runtime ? <Badge tone="success">Found</Badge> : <Badge>Not found</Badge>}
            </Row>
          </Section>
          <p className="px-1 pb-4 text-[11.5px] text-ink-3">
            Respect copyright and each site's terms. {app?.name ?? "SwiftDrop"} does not bypass DRM, paywalls, private
            profiles or other access controls.
          </p>
        </div>
      </div>
    </div>
  );
}
