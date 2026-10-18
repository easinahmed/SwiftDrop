import { useCallback, useEffect, useRef, useState } from "react";
import { Copy, ExternalLink, FileDown, FolderSearch, History as HistoryIcon, Search, Trash2, X } from "lucide-react";
import { api } from "../lib/api";
import { formatBytes, formatRelative, pluralize } from "../lib/format";
import { openWithConfirm } from "../lib/openFile";
import { errorMessage, useStore } from "../lib/store";
import type { HistoryEntry, MediaKind } from "../lib/types";
import { Thumb } from "../components/media";
import { ConfirmDialog } from "../components/overlay";
import { Badge, Button, EmptyState, IconButton, PageHeader, Segmented, Select } from "../components/ui";

const PAGE = 200;

export function HistoryPage() {
  const toast = useStore((s) => s.toast);
  const version = useStore((s) => s.historyVersion);
  const saveHistory = useStore((s) => s.settings?.save_history ?? true);
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<"all" | MediaKind>("all");
  const [status, setStatus] = useState<"all" | "completed" | "failed" | "cancelled">("all");
  const [items, setItems] = useState<HistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [confirmClear, setConfirmClear] = useState(false);
  const requestId = useRef(0);

  const load = useCallback(
    async (offset = 0) => {
      const id = ++requestId.current;
      setLoading(true);
      try {
        const result = await api.searchHistory({ query, kind, status, limit: PAGE, offset });
        if (id !== requestId.current) return;
        setItems((prev) => (offset ? [...prev, ...result.items] : result.items));
        setTotal(result.total);
      } catch (error) {
        toast("error", errorMessage(error));
      } finally {
        if (id === requestId.current) setLoading(false);
      }
    },
    [query, kind, status, toast],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(0), query ? 180 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query, version]);

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const exportData = async () => {
    try {
      const path = await api.exportData("results");
      if (path) toast("success", `Saved ${path.split("/").pop()}`);
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const filtered = query || kind !== "all" || status !== "all";

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="History"
        subtitle={
          saveHistory
            ? "Everything you've downloaded. Clearing history never deletes your files."
            : "History is turned off in Settings → Privacy."
        }
        actions={
          <>
            <Button size="sm" variant="ghost" icon={<FileDown className="size-3.5" />} onClick={exportData}>
              Export CSV
            </Button>
            <Button size="sm" icon={<Trash2 className="size-3.5" />} disabled={!total && !filtered} onClick={() => setConfirmClear(true)}>
              Clear history
            </Button>
          </>
        }
      />
      <div className="flex flex-wrap items-center gap-3 px-8 pb-3">
        <div className="relative w-[280px]">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-3" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles, links, files"
            aria-label="Search history"
            className="h-8 w-full rounded-[8px] border border-line-strong bg-surface pl-8 pr-8 text-[13px] outline-none focus:border-accent"
          />
          {query && (
            <button
              type="button"
              aria-label="Clear search"
              onClick={() => setQuery("")}
              className="absolute right-2 top-1/2 -translate-y-1/2 text-ink-3 hover:text-ink"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
        <Segmented
          label="Type"
          size="sm"
          value={kind}
          onChange={setKind}
          options={[
            { value: "all", label: "All" },
            { value: "video", label: "Video" },
            { value: "audio", label: "Audio" },
            { value: "image", label: "Images" },
            { value: "other", label: "Other" },
          ]}
        />
        <Select
          label="Status"
          value={status}
          onChange={setStatus}
          className="w-[140px]"
          options={[
            { value: "all", label: "Any status" },
            { value: "completed", label: "Completed" },
            { value: "failed", label: "Failed" },
            { value: "cancelled", label: "Cancelled" },
          ]}
        />
        <span className="ml-auto text-[12px] tabular-nums text-ink-3">{pluralize(total, "entry", "entries")}</span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto px-8 pb-8">
        {!loading && items.length === 0 ? (
          <EmptyState
            icon={<HistoryIcon className="size-6" />}
            title={filtered ? "No matches" : "No history yet"}
            body={filtered ? "Try a different search or filter." : "Finished downloads will be listed here so you can find them again."}
          />
        ) : (
          <section className="card overflow-hidden" aria-label="Download history">
            <ul>
              {items.map((entry) => (
                <li key={entry.id} className="row-cv group flex items-center gap-3 border-b border-line px-4 py-3 last:border-b-0">
                  <Thumb kind={entry.kind} src={entry.thumbnail} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-medium" title={entry.filepath ?? entry.url}>
                        {entry.title}
                      </span>
                      {entry.status === "failed" && <Badge tone="danger">Failed</Badge>}
                      {entry.status === "cancelled" && <Badge>Cancelled</Badge>}
                      {entry.status === "completed" && !entry.file_exists && <Badge tone="warning">File missing</Badge>}
                    </div>
                    <div className="mt-0.5 truncate text-[12px] text-ink-3">
                      {[
                        entry.source,
                        entry.collection_title,
                        entry.quality,
                        entry.file_size ? formatBytes(entry.file_size) : null,
                        formatRelative(entry.finished_at),
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                    </div>
                    {entry.status === "failed" && entry.error_message && (
                      <div className="mt-0.5 truncate text-[12px] text-danger">{entry.error_message}</div>
                    )}
                  </div>
                  <div className="flex shrink-0 items-center gap-0.5 opacity-80 group-hover:opacity-100">
                    {entry.file_exists && (
                      <>
                        <IconButton label="Open" onClick={() => act(() => openWithConfirm((confirmed) => api.openHistory(entry.id, confirmed)))}>
                          <ExternalLink className="size-4" />
                        </IconButton>
                        <IconButton label="Show in Finder" onClick={() => act(() => api.revealHistory(entry.id))}>
                          <FolderSearch className="size-4" />
                        </IconButton>
                      </>
                    )}
                    <IconButton
                      label="Copy link"
                      onClick={() => act(async () => {
                        await api.copyText(entry.url);
                        toast("success", "Link copied");
                      })}
                    >
                      <Copy className="size-4" />
                    </IconButton>
                    <IconButton
                      label="Remove from history"
                      tone="danger"
                      onClick={() => act(async () => {
                        await api.deleteHistory([entry.id]);
                        setItems((prev) => prev.filter((i) => i.id !== entry.id));
                        setTotal((t) => Math.max(0, t - 1));
                      })}
                    >
                      <Trash2 className="size-4" />
                    </IconButton>
                  </div>
                </li>
              ))}
            </ul>
            {items.length < total && (
              <div className="flex justify-center border-t border-line p-3">
                <Button size="sm" busy={loading} onClick={() => void load(items.length)}>
                  Load more
                </Button>
              </div>
            )}
          </section>
        )}
      </div>
      <ConfirmDialog
        open={confirmClear}
        title="Clear download history?"
        body="This removes the list of past downloads. Your downloaded files stay exactly where they are."
        confirmLabel="Clear history"
        danger
        onClose={() => setConfirmClear(false)}
        onConfirm={() =>
          act(async () => {
            const n = await api.clearHistory();
            toast("success", `Cleared ${pluralize(n, "entry", "entries")}`);
            void load(0);
          })
        }
      />
    </div>
  );
}
