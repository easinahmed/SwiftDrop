import { memo, useCallback, useMemo, useRef, useState, type DragEvent } from "react";
import {
  CheckCircle2,
  ClipboardPaste,
  FileUp,
  Folder,
  ListChecks,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import { countLinks, folderName, formatBytes, formatDuration, pluralize, shortPath } from "../lib/format";
import { errorMessage, selectSortedPreview, useStore } from "../lib/store";
import type { AudioFormat, PreviewItem, Quality, VideoFormat } from "../lib/types";
import { ErrorNote, Thumb } from "../components/media";
import { Badge, Button, Checkbox, cx, IconButton, PageHeader, Select } from "../components/ui";
import { PlaylistSheet } from "../components/PlaylistSheet";

const QUALITY_OPTIONS: { value: Quality; label: string }[] = [
  { value: "best", label: "Best available" },
  { value: "2160", label: "4K (2160p)" },
  { value: "1440", label: "1440p" },
  { value: "1080", label: "1080p" },
  { value: "720", label: "720p" },
  { value: "480", label: "480p" },
  { value: "360", label: "360p" },
  { value: "audio", label: "Audio only" },
];
const VIDEO_FORMATS: { value: VideoFormat; label: string }[] = [
  { value: "mp4", label: "MP4 (plays in QuickTime)" },
  { value: "mkv", label: "Original quality (MKV, may need VLC)" },
  { value: "webm", label: "WebM" },
  { value: "auto", label: "Original" },
];
const AUDIO_FORMATS: { value: AudioFormat; label: string }[] = [
  { value: "m4a", label: "M4A (AAC)" },
  { value: "mp3", label: "MP3" },
  { value: "opus", label: "Opus" },
  { value: "flac", label: "FLAC" },
  { value: "wav", label: "WAV" },
  { value: "auto", label: "Original" },
];
const TEXT_EXT = /\.(txt|csv|md|list|text)$/i;
const MAX_DROP_BYTES = 5 * 1024 * 1024;

function useAnalyze() {
  const addPreview = useStore((s) => s.addPreview);
  const toast = useStore((s) => s.toast);
  return useCallback(
    async (text: string, source?: string) => {
      const result = await api.analyze(text, true);
      addPreview(result.added);
      const parts: string[] = [];
      if (result.added.length) parts.push(`Added ${pluralize(result.added.length, "link")}`);
      if (result.duplicates) parts.push(`${pluralize(result.duplicates, "duplicate")} skipped`);
      if (result.invalid_count) parts.push(`${result.invalid_count} invalid`);
      if (result.truncated) parts.push("list was too long and was truncated");
      if (!result.added.length && !result.duplicates && !result.invalid_count) {
        toast("warning", source ? `No links found in ${source}.` : "No links found in that text.");
      } else {
        const message = (source ? `${source}: ` : "") + parts.join(" · ");
        toast(result.invalid_count && !result.added.length ? "warning" : "success", message);
      }
      return result;
    },
    [addPreview, toast],
  );
}

function Composer() {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const analyze = useAnalyze();
  const toast = useStore((s) => s.toast);
  const textRef = useRef<HTMLTextAreaElement>(null);
  const detected = useMemo(() => countLinks(text), [text]);

  const submit = async (value: string, source?: string) => {
    if (!value.trim()) return;
    setBusy(true);
    try {
      const result = await analyze(value, source);
      if (!source && (result.added.length || result.duplicates)) setText("");
    } catch (error) {
      toast("error", errorMessage(error));
    } finally {
      setBusy(false);
    }
  };

  const pasteFromClipboard = async () => {
    try {
      const value = await api.readClipboard();
      if (!value.trim()) {
        toast("info", "The clipboard is empty.");
        return;
      }
      await submit(value, "Clipboard");
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const importFile = async () => {
    try {
      const file = await api.importFile();
      if (file) await submit(file.text, file.name);
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const onDrop = async (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) {
      for (const file of files) {
        if (!TEXT_EXT.test(file.name) && !file.type.startsWith("text/")) {
          toast("warning", `${file.name} isn't a text file. Drop a .txt list of links.`);
          continue;
        }
        if (file.size > MAX_DROP_BYTES) {
          toast("warning", `${file.name} is larger than 5 MB.`);
          continue;
        }
        await submit(await file.text(), file.name);
      }
      return;
    }
    const dropped = e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain");
    if (dropped) await submit(dropped, "Dropped links");
  };

  return (
    <div
      className={cx(
        "card relative overflow-hidden transition-[box-shadow,border-color] duration-200",
        dragging && "border-accent shadow-[0_0_0_4px_var(--accent-soft)]",
      )}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={onDrop}
    >
      <label htmlFor="url-input" className="sr-only">
        Links to download
      </label>
      <textarea
        id="url-input"
        data-drop-target="links"
        ref={textRef}
        value={text}
        spellCheck={false}
        autoFocus
        onChange={(e) => setText(e.target.value)}
        onPaste={(e) => {
          const pasted = e.clipboardData.getData("text/plain");
          if (countLinks(pasted) > 0 && !text.trim()) {
            e.preventDefault();
            void submit(pasted, "Pasted");
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault();
            void submit(text);
          }
        }}
        placeholder={"Paste one link or hundreds — videos, audio, images, playlists or files.\nhttps://…"}
        className="block h-[128px] w-full resize-none bg-transparent px-5 pb-2 pt-4 font-mono text-[12.5px] leading-[1.65] text-ink outline-none placeholder:font-sans placeholder:text-[13.5px] placeholder:text-ink-3"
      />
      <div className="flex items-center gap-2 border-t border-line bg-surface-2 px-3 py-2">
        <Button size="sm" variant="ghost" icon={<ClipboardPaste className="size-3.5" />} onClick={pasteFromClipboard}>
          Paste
        </Button>
        <Button size="sm" variant="ghost" icon={<FileUp className="size-3.5" />} onClick={importFile}>
          Import .txt
        </Button>
        {text && (
          <Button size="sm" variant="ghost" icon={<X className="size-3.5" />} onClick={() => setText("")}>
            Clear
          </Button>
        )}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-[12px] tabular-nums text-ink-3" aria-live="polite">
            {detected ? `${pluralize(detected, "link")} detected` : "Drop a .txt list here"}
          </span>
          <Button
            size="sm"
            variant="primary"
            icon={busy ? <Loader2 className="size-3.5 animate-spin" /> : <Plus className="size-3.5" />}
            disabled={!detected || busy}
            onClick={() => void submit(text)}
            title="Add links (⌘↩)"
          >
            {detected > 1 ? `Add ${detected.toLocaleString()} links` : "Add link"}
          </Button>
        </div>
      </div>
      {dragging && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-accent-soft text-[14px] font-semibold text-accent-ink backdrop-blur-[1px]">
          Drop a .txt file or links to add them
        </div>
      )}
    </div>
  );
}

function describe(item: PreviewItem): string[] {
  const parts: string[] = [item.source];
  const info = item.info;
  if (info?.is_playlist) {
    parts.push(`${info.extractor ?? item.link.label} playlist`);
  } else if (info?.extractor) {
    parts.push(info.extractor);
  } else if (item.link.label && item.link.provider !== "auto") {
    parts.push(item.link.label);
  }
  const duration = formatDuration(info?.duration);
  if (duration) parts.push(duration);
  if (info?.size) parts.push(`${info.size_is_estimate ? "~" : ""}${formatBytes(info.size)}`);
  if (info?.heights?.length) parts.push(`up to ${Math.max(...info.heights)}p`);
  return parts;
}

const PreviewRow = memo(function PreviewRow({
  item,
  selected,
  entrySelection,
  onToggle,
  onRemove,
  onChoose,
}: {
  item: PreviewItem;
  selected: boolean;
  entrySelection: string[] | null | undefined;
  onToggle: (id: string, value: boolean) => void;
  onRemove: (id: string) => void;
  onChoose: (item: PreviewItem) => void;
}) {
  const info = item.info;
  const playlist = Boolean(info?.is_playlist);
  const title = item.title || info?.filename || item.url;
  const blocked = item.status === "blocked";
  return (
    <li
      className={cx(
        "row-cv group flex items-start gap-3 border-b border-line px-4 py-3 last:border-b-0 transition-colors",
        selected ? "bg-surface" : "bg-surface-2/60",
      )}
    >
      <div className="pt-[13px]">
        <Checkbox
          checked={selected && !blocked}
          disabled={blocked}
          onChange={(v) => onToggle(item.id, v)}
          label={`Select ${title}`}
        />
      </div>
      <Thumb kind={item.kind} src={info?.thumbnail} playlist={playlist || item.link.playlist_hint} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span
            className={cx("truncate text-[13px] font-medium", item.title ? "text-ink" : "font-mono text-[12px] text-ink-2")}
            title={item.url}
          >
            {title}
          </span>
          {item.in_queue && <Badge tone="accent">In queue</Badge>}
          {item.downloaded_before && (
            <Badge tone="success" className="shrink-0">
              <CheckCircle2 className="size-3" /> Downloaded before
            </Badge>
          )}
        </div>
        <div className="mt-0.5 flex items-center gap-1.5 truncate text-[12px] text-ink-3">
          {describe(item).map((part, i) => (
            <span key={i} className="flex items-center gap-1.5 truncate">
              {i > 0 && <span aria-hidden>·</span>}
              {part}
            </span>
          ))}
        </div>
        {playlist && (
          <div className="mt-1.5 flex items-center gap-2">
            <Badge tone="accent">
              {entrySelection
                ? `${entrySelection.length} of ${info?.entry_count ?? 0} selected`
                : `All ${info?.entry_count ?? 0} items`}
            </Badge>
            <button
              type="button"
              onClick={() => onChoose(item)}
              className="inline-flex items-center gap-1 text-[12px] font-medium text-accent-ink hover:underline"
            >
              <ListChecks className="size-3.5" /> Choose items
            </button>
            {info?.entries_truncated && <span className="text-[11.5px] text-ink-3">(first items only)</span>}
          </div>
        )}
        {item.error && <ErrorNote error={item.error} compact />}
      </div>
      <div className="flex shrink-0 items-center gap-1 pt-[11px]">
        {item.status === "inspecting" && (
          <span className="flex items-center gap-1.5 text-[12px] text-ink-3">
            <Loader2 className="size-3.5 animate-spin" /> Fetching details
          </span>
        )}
        {item.status === "pending" && <span className="text-[12px] text-ink-3">Waiting</span>}
        {item.status === "ready" && <CheckCircle2 className="size-4 text-success" aria-label="Ready" />}
        <IconButton label="Remove from list" tone="danger" onClick={() => onRemove(item.id)} className="ml-1">
          <X className="size-4" />
        </IconButton>
      </div>
    </li>
  );
});

function OptionsBar({ selectedCount, onStart, starting }: { selectedCount: number; onStart: () => void; starting: boolean }) {
  const options = useStore((s) => s.options);
  const setOptions = useStore((s) => s.setOptions);
  const destination = useStore((s) => s.destination);
  const setDestination = useStore((s) => s.setDestination);
  const toast = useStore((s) => s.toast);
  const ffmpeg = useStore((s) => s.capabilities?.ffmpeg ?? true);
  const audio = options.quality === "audio";

  const choose = async () => {
    try {
      const folder = await api.chooseFolder(destination);
      if (folder) setDestination(folder);
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  return (
    <div className="border-t border-line bg-surface/85 px-8 py-3 backdrop-blur-xl">
      <div className="flex flex-wrap items-center gap-2.5">
        <Select
          label="Quality"
          value={options.quality}
          onChange={(quality) => setOptions({ quality })}
          options={QUALITY_OPTIONS}
          className="w-[150px]"
        />
        {audio ? (
          <Select
            label="Audio format"
            value={options.audio_format}
            onChange={(audio_format) => setOptions({ audio_format })}
            options={AUDIO_FORMATS}
            className="w-[150px]"
          />
        ) : (
          <Select
            label="Video format"
            value={options.video_format}
            onChange={(video_format) => setOptions({ video_format })}
            options={VIDEO_FORMATS}
            className="w-[260px]"
          />
        )}
        <button
          type="button"
          onClick={choose}
          title={destination}
          className="inline-flex h-8 max-w-[260px] items-center gap-2 rounded-[8px] border border-line-strong bg-surface px-3 text-[13px] shadow-[0_1px_1px_rgb(0_0_0/0.04)] hover:bg-surface-2"
        >
          <Folder className="size-4 shrink-0 text-accent" />
          <span className="truncate">{folderName(destination) || "Choose folder"}</span>
        </button>
        <div className="ml-auto flex items-center gap-3">
          {!ffmpeg && (audio || options.video_format !== "auto") && (
            <span className="text-[11.5px] text-warning">FFmpeg missing — conversion unavailable</span>
          )}
          <Button
            size="lg"
            variant="primary"
            disabled={selectedCount === 0}
            busy={starting}
            onClick={onStart}
            title="Start downloading (⌘↩)"
            className="min-w-[170px]"
          >
            {selectedCount ? `Download ${pluralize(selectedCount, "item")}` : "Download"}
          </Button>
        </div>
      </div>
      <p className="mt-1.5 truncate text-[11.5px] text-ink-3" title={destination}>
        Quality and format apply to video and audio sites; direct files are saved exactly as published. Saving to{" "}
        <span className="selectable">{shortPath(destination)}</span>
      </p>
    </div>
  );
}

function Tips() {
  const sites = useStore((s) => s.capabilities?.sites ?? true);
  const tips = [
    ["Bulk links", "Paste or import hundreds of links at once — duplicates are detected automatically."],
    ["Video & audio sites", sites ? "YouTube, Vimeo, SoundCloud, Bandcamp, podcasts (RSS) and many more public sources." : "Site support is unavailable in this build."],
    ["Direct files", "Any http(s) file — MP4, MP3, images, PDFs, archives — with resume support."],
  ];
  return (
    <div className="mt-6 grid grid-cols-3 gap-3">
      {tips.map(([title, body]) => (
        <div key={title} className="rounded-[12px] border border-dashed border-line-strong px-4 py-3.5">
          <div className="flex items-center gap-1.5 text-[12.5px] font-semibold text-ink">
            <Sparkles className="size-3.5 text-accent" /> {title}
          </div>
          <p className="mt-1 text-[12px] text-ink-2">{body}</p>
        </div>
      ))}
      <p className="col-span-3 mt-1 text-[11.5px] text-ink-3">
        Only download media you own or have permission to save. Spotify songs are saved from matching YouTube
        recordings. DRM-protected services (Netflix, Apple Music…), private profiles and paywalled content aren't
        supported.
      </p>
    </div>
  );
}

export function DownloaderPage() {
  const preview = useStore((s) => s.preview);
  const selection = useStore((s) => s.selection);
  const playlistSelections = useStore((s) => s.playlistSelections);
  const setSelected = useStore((s) => s.setSelected);
  const setPlaylistSelection = useStore((s) => s.setPlaylistSelection);
  const options = useStore((s) => s.options);
  const destination = useStore((s) => s.destination);
  const toast = useStore((s) => s.toast);
  const setPage = useStore((s) => s.setPage);
  const [starting, setStarting] = useState(false);
  const [choosing, setChoosing] = useState<PreviewItem | null>(null);

  const items = useMemo(() => selectSortedPreview(preview), [preview]);
  const selectable = items.filter((i) => i.status !== "blocked");
  const selectedItems = selectable.filter((i) => selection[i.id]);
  const selectedCount = selectedItems.reduce((sum, item) => {
    if (item.info?.is_playlist) {
      const chosen = playlistSelections[item.id];
      return sum + (chosen ? chosen.length : item.info.entry_count);
    }
    return sum + 1;
  }, 0);
  const knownSize = selectedItems.reduce((sum, i) => sum + (i.info && !i.info.is_playlist ? i.info.size ?? 0 : 0), 0);
  const unknownSize = selectedItems.some((i) => !i.info?.size);
  const inspecting = items.filter((i) => i.status === "inspecting" || i.status === "pending").length;

  const onToggle = useCallback((id: string, value: boolean) => setSelected([id], value), [setSelected]);
  const onRemove = useCallback(
    (id: string) => {
      api.removePreview([id]).catch((error) => toast("error", errorMessage(error)));
    },
    [toast],
  );
  const onChoose = useCallback((item: PreviewItem) => setChoosing(item), []);

  const start = async () => {
    if (!selectedItems.length) return;
    setStarting(true);
    try {
      const result = await api.start({
        items: selectedItems.map((i) => ({ id: i.id, entries: playlistSelections[i.id] ?? null })),
        options,
        destination,
      });
      const skipped = result.skipped.length ? ` · ${result.skipped.length} skipped` : "";
      if (result.created) {
        toast("success", `Started ${pluralize(result.created, "download")}${skipped}`);
        setPage("downloads");
      } else {
        toast("warning", `Nothing to download${skipped ? `: ${result.skipped[0].reason.toLowerCase()}` : ""}.`);
      }
    } catch (error) {
      toast("error", errorMessage(error));
    } finally {
      setStarting(false);
    }
  };

  const allSelected = selectable.length > 0 && selectedItems.length === selectable.length;

  return (
    <div
      className="flex h-full flex-col"
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && !(e.target instanceof HTMLTextAreaElement)) {
          e.preventDefault();
          void start();
        }
      }}
    >
      <PageHeader
        title="New Download"
        subtitle="Paste links, review what was found, then download everything in one go."
      />
      <div className="min-h-0 flex-1 overflow-auto px-8 pb-6">
        <Composer />
        {items.length === 0 ? (
          <Tips />
        ) : (
          <section className="card mt-5 overflow-hidden animate-fade-in" aria-label="Links to download">
            <div className="flex items-center gap-3 border-b border-line bg-surface-2 px-4 py-2.5">
              <Checkbox
                checked={allSelected}
                indeterminate={!allSelected && selectedItems.length > 0}
                onChange={(v) => setSelected(selectable.map((i) => i.id), v)}
                label="Select all"
              />
              <div className="flex-1 text-[12.5px] text-ink-2">
                <span className="font-semibold text-ink">{pluralize(items.length, "link")}</span>
                {" · "}
                {selectedCount.toLocaleString()} selected
                {knownSize > 0 && (
                  <>
                    {" · "}
                    {unknownSize ? "at least " : ""}
                    {formatBytes(knownSize)}
                  </>
                )}
                {inspecting > 0 && (
                  <span className="ml-2 inline-flex items-center gap-1 text-ink-3">
                    <Loader2 className="size-3 animate-spin" /> checking {inspecting}
                  </span>
                )}
              </div>
              {selectedItems.length > 0 && selectedItems.length < items.length && (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 className="size-3.5" />}
                  onClick={() => api.removePreview(selectedItems.map((i) => i.id)).catch((e) => toast("error", errorMessage(e)))}
                >
                  Remove selected
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                icon={<Trash2 className="size-3.5" />}
                onClick={() => api.clearPreview().catch((e) => toast("error", errorMessage(e)))}
              >
                Clear all
              </Button>
            </div>
            <ul>
              {items.map((item) => (
                <PreviewRow
                  key={item.id}
                  item={item}
                  selected={Boolean(selection[item.id])}
                  entrySelection={playlistSelections[item.id]}
                  onToggle={onToggle}
                  onRemove={onRemove}
                  onChoose={onChoose}
                />
              ))}
            </ul>
          </section>
        )}
      </div>
      <OptionsBar selectedCount={selectedCount} onStart={start} starting={starting} />
      {choosing && (
        <PlaylistSheet
          item={choosing}
          initial={playlistSelections[choosing.id] ?? null}
          onClose={() => setChoosing(null)}
          onApply={(entries) => {
            setPlaylistSelection(choosing.id, entries);
            setSelected([choosing.id], entries === null || entries.length > 0);
            setChoosing(null);
          }}
        />
      )}
    </div>
  );
}
