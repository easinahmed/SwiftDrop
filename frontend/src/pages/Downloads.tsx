import { useCallback, useMemo, useState } from "react";
import { ClipboardList, Download, FileDown, Pause, Play, RotateCcw, Square, Trash2 } from "lucide-react";
import { api } from "../lib/api";
import { formatSpeed, pluralize } from "../lib/format";
import { errorMessage, selectSortedJobs, useStore } from "../lib/store";
import type { Job, JobState } from "../lib/types";
import { useJobCommand } from "../lib/useJobCommand";
import { JobRow } from "../components/JobRow";
import { Button, Checkbox, EmptyState, PageHeader, Segmented } from "../components/ui";

type Filter = "all" | "active" | "queued" | "paused" | "completed" | "failed";

const FILTERS: Record<Filter, (s: JobState) => boolean> = {
  all: () => true,
  active: (s) => s === "downloading" || s === "processing",
  queued: (s) => s === "queued",
  paused: (s) => s === "paused" || s === "interrupted",
  completed: (s) => s === "completed",
  failed: (s) => s === "failed" || s === "cancelled",
};

const GROUP: Record<JobState, number> = {
  downloading: 0,
  processing: 0,
  queued: 1,
  failed: 2,
  paused: 2,
  interrupted: 2,
  completed: 3,
  cancelled: 3,
};

const BULK_VERB = {
  pause: "Paused",
  resume: "Resumed",
  cancel: "Cancelled",
  retry: "Retrying",
  remove: "Removed",
} as const;

export function DownloadsPage() {
  const jobsMap = useStore((s) => s.jobs);
  const stats = useStore((s) => s.stats);
  const setPage = useStore((s) => s.setPage);
  const toast = useStore((s) => s.toast);
  const onCommand = useJobCommand();
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<Record<string, boolean>>({});

  const jobs = useMemo(() => selectSortedJobs(jobsMap), [jobsMap]);
  const visible = useMemo(() => {
    const matching = jobs.filter((j) => FILTERS[filter](j.state));
    // In "All", keep what's happening now at the top so it isn't buried under finished items.
    return filter === "all" ? [...matching].sort((a, b) => GROUP[a.state] - GROUP[b.state] || a.order - b.order) : matching;
  }, [jobs, filter]);
  const selectedIds = visible.filter((j) => selected[j.id]).map((j) => j.id);
  const counts = useMemo(() => {
    const result = {} as Record<Filter, number>;
    for (const key of Object.keys(FILTERS) as Filter[]) result[key] = jobs.filter((j) => FILTERS[key](j.state)).length;
    return result;
  }, [jobs]);

  const onSelect = useCallback((id: string, value: boolean) => setSelected((s) => ({ ...s, [id]: value })), []);

  const run = async (fn: () => Promise<number>, done?: (n: number) => string) => {
    try {
      const n = await fn();
      if (done) toast(n ? "success" : "info", done(n));
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const bulk = (action: keyof typeof BULK_VERB) =>
    run(() => api.jobAction(action, selectedIds), (n) => `${BULK_VERB[action]} ${pluralize(n, "item")}`).then(() =>
      setSelected({}),
    );

  const exportData = async (kind: "results" | "failed") => {
    try {
      const path = await api.exportData(kind);
      if (path) toast("success", `Saved ${path.split("/").pop()}`);
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const allVisibleSelected = visible.length > 0 && selectedIds.length === visible.length;
  const totalSpeed = formatSpeed(stats.speed);
  const paused = stats.counts.paused + stats.counts.interrupted;

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Downloads"
        subtitle={
          jobs.length
            ? [
                stats.active ? `${stats.active} downloading` : null,
                stats.queued ? `${stats.queued} waiting` : null,
                totalSpeed,
                `${stats.counts.completed.toLocaleString()} completed`,
                stats.counts.failed ? `${stats.counts.failed} failed` : null,
              ]
                .filter(Boolean)
                .join(" · ")
            : "Your queue is empty."
        }
        actions={
          jobs.length > 0 && (
            <>
              {stats.active + stats.queued > 0 && (
                <Button size="sm" icon={<Pause className="size-3.5" />} onClick={() => run(() => api.queueAction("pause_all"))}>
                  Pause all
                </Button>
              )}
              {paused > 0 && (
                <Button size="sm" icon={<Play className="size-3.5" />} onClick={() => run(() => api.queueAction("resume_all"))}>
                  Resume all
                </Button>
              )}
              {stats.counts.failed > 0 && (
                <Button
                  size="sm"
                  icon={<RotateCcw className="size-3.5" />}
                  onClick={() => run(() => api.queueAction("retry_failed"), (n) => `Retrying ${pluralize(n, "item")}`)}
                >
                  Retry failed
                </Button>
              )}
              {stats.counts.failed > 0 && (
                <Button size="sm" variant="ghost" icon={<FileDown className="size-3.5" />} onClick={() => exportData("failed")}>
                  Export failed
                </Button>
              )}
              {stats.counts.completed + stats.counts.cancelled > 0 && (
                <Button
                  size="sm"
                  variant="ghost"
                  icon={<Trash2 className="size-3.5" />}
                  onClick={() =>
                    run(() => api.queueAction("clear_completed"), (n) => `Cleared ${pluralize(n, "item")} (files are kept)`)
                  }
                >
                  Clear completed
                </Button>
              )}
            </>
          )
        }
      />
      {jobs.length === 0 ? (
        <EmptyState
          icon={<ClipboardList className="size-6" />}
          title="No downloads yet"
          body="Links you start downloading appear here with live progress, speed and time remaining."
          action={
            <Button variant="primary" icon={<Download className="size-4" />} onClick={() => setPage("home")}>
              New download
            </Button>
          }
        />
      ) : (
        <>
          <div className="flex items-center gap-3 px-8 pb-3">
            <Segmented
              label="Filter downloads"
              value={filter}
              onChange={(f) => {
                setFilter(f);
                setSelected({});
              }}
              size="sm"
              options={[
                { value: "all", label: "All", count: counts.all },
                { value: "active", label: "Active", count: counts.active },
                { value: "queued", label: "Queued", count: counts.queued },
                { value: "paused", label: "Paused", count: counts.paused },
                { value: "completed", label: "Completed", count: counts.completed },
                { value: "failed", label: "Failed", count: counts.failed },
              ]}
            />
            {selectedIds.length > 0 && (
              <div className="ml-auto flex items-center gap-1.5 animate-fade-in">
                <span className="mr-1 text-[12px] text-ink-2">{selectedIds.length} selected</span>
                <Button size="sm" variant="ghost" icon={<Pause className="size-3.5" />} onClick={() => bulk("pause")}>
                  Pause
                </Button>
                <Button size="sm" variant="ghost" icon={<Play className="size-3.5" />} onClick={() => bulk("resume")}>
                  Resume
                </Button>
                <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={() => bulk("retry")}>
                  Retry
                </Button>
                <Button size="sm" variant="ghost" icon={<Square className="size-3" />} onClick={() => bulk("cancel")}>
                  Cancel
                </Button>
                <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => bulk("remove")}>
                  Remove
                </Button>
              </div>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-auto px-8 pb-8">
            <section className="card overflow-hidden" aria-label="Download queue">
              <div className="flex items-center gap-3 border-b border-line bg-surface-2 px-4 py-2">
                <Checkbox
                  checked={allVisibleSelected}
                  indeterminate={!allVisibleSelected && selectedIds.length > 0}
                  onChange={(v) => setSelected(v ? Object.fromEntries(visible.map((j) => [j.id, true])) : {})}
                  label="Select all visible"
                />
                <span className="text-[12px] text-ink-2">{pluralize(visible.length, "item")}</span>
                <Button size="sm" variant="ghost" className="ml-auto" icon={<FileDown className="size-3.5" />} onClick={() => exportData("results")}>
                  Export results
                </Button>
              </div>
              {visible.length === 0 ? (
                <p className="px-4 py-10 text-center text-[13px] text-ink-3">Nothing here.</p>
              ) : (
                <ul>
                  {visible.map((job: Job) => (
                    <JobRow key={job.id} job={job} selected={Boolean(selected[job.id])} onSelect={onSelect} onCommand={onCommand} />
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
