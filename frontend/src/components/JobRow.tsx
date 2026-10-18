import { memo } from "react";
import {
  ExternalLink,
  FolderSearch,
  Pause,
  Play,
  RotateCcw,
  Square,
  Trash2,
} from "lucide-react";
import { formatBytes, formatConnections, formatEta, formatRelative, formatSpeed } from "../lib/format";
import type { Job } from "../lib/types";
import { ErrorNote, StateBadge, Thumb } from "./media";
import { Checkbox, cx, IconButton, ProgressBar } from "./ui";

export type JobCommand = "pause" | "resume" | "cancel" | "retry" | "remove" | "reveal" | "open";

function progressLine(job: Job): string {
  const parts: string[] = [];
  const total = job.total_bytes;
  if (job.state === "downloading" || job.state === "processing") {
    if (job.phase && (job.state === "processing" || !job.downloaded_bytes)) parts.push(job.phase);
    if (job.downloaded_bytes) {
      parts.push(
        total
          ? `${formatBytes(job.downloaded_bytes)} of ${job.total_is_estimate ? "~" : ""}${formatBytes(total)}`
          : `${formatBytes(job.downloaded_bytes)} downloaded`,
      );
    }
    if (job.state === "downloading") {
      const speed = formatSpeed(job.speed);
      if (speed) parts.push(speed);
      const connections = formatConnections(job.connections);
      if (connections) parts.push(connections);
      const eta = formatEta(job.eta);
      if (eta) parts.push(job.total_is_estimate ? `~${eta}` : eta);
      if (job.phase && job.downloaded_bytes && job.phase !== "Downloading") parts.push(job.phase);
    }
    return parts.join(" · ") || "Starting…";
  }
  if (job.state === "completed") {
    if (job.file_missing) return "File was moved or deleted";
    return [formatBytes(job.file_size), formatRelative(job.finished_at)].filter(Boolean).join(" · ");
  }
  if (job.state === "paused" || job.state === "interrupted") {
    const done = job.downloaded_bytes
      ? total
        ? `${formatBytes(job.downloaded_bytes)} of ${formatBytes(total)}`
        : `${formatBytes(job.downloaded_bytes)} downloaded`
      : "";
    return [job.note ?? (job.state === "paused" ? "Paused" : "Interrupted"), done].filter(Boolean).join(" · ");
  }
  if (job.state === "queued") return job.attempts ? "Waiting to retry" : "Waiting for a free slot";
  if (job.state === "cancelled") return "Cancelled · partial data removed";
  return "";
}

export const JobRow = memo(function JobRow({
  job,
  selected,
  onSelect,
  onCommand,
  compact,
}: {
  job: Job;
  selected?: boolean;
  onSelect?: (id: string, value: boolean) => void;
  onCommand: (command: JobCommand, job: Job) => void;
  compact?: boolean;
}) {
  const active = job.state === "downloading" || job.state === "processing";
  const title = job.title || job.filename || job.url;
  const subtitle = [job.source, job.extractor && job.extractor !== job.source ? job.extractor : null, job.quality_label]
    .filter(Boolean)
    .join(" · ");
  const tone =
    job.state === "completed"
      ? "success"
      : job.state === "failed"
        ? "danger"
        : job.state === "paused" || job.state === "interrupted"
          ? "warning"
          : job.state === "cancelled"
            ? "muted"
            : "accent";
  const value =
    job.state === "completed" ? 1 : job.progress ?? (job.state === "cancelled" || job.state === "failed" ? 0 : null);
  const indeterminate = active && job.progress == null;

  return (
    <li
      className={cx(
        "row-cv group flex items-center gap-3 border-b border-line px-4 last:border-b-0",
        compact ? "py-2" : "py-3",
        selected && "bg-accent-soft",
      )}
    >
      {onSelect && (
        <Checkbox checked={Boolean(selected)} onChange={(v) => onSelect(job.id, v)} label={`Select ${title}`} />
      )}
      <Thumb kind={job.kind} src={job.thumbnail} size={compact ? 34 : 44} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[13px] font-medium text-ink" title={job.filepath ?? job.url}>
            {job.playlist_index != null && <span className="mr-1.5 tabular-nums text-ink-3">{job.playlist_index}.</span>}
            {title}
          </span>
          <StateBadge state={job.state} />
        </div>
        {!compact && subtitle && <div className="mt-0.5 truncate text-[12px] text-ink-3">{subtitle}</div>}
        {(active || job.state === "paused" || job.state === "interrupted" || job.state === "queued") && (
          <ProgressBar
            value={value}
            tone={tone as "accent"}
            indeterminate={indeterminate}
            className="mt-2"
            label={`${title} progress`}
          />
        )}
        <div className="mt-1 flex items-center gap-2 text-[11.5px] tabular-nums text-ink-3" aria-live="off">
          <span className="truncate">{progressLine(job)}</span>
          {active && job.progress != null && (
            <span className="ml-auto shrink-0 font-medium text-ink-2">{Math.floor(job.progress * 100)}%</span>
          )}
        </div>
        {job.state === "failed" && job.error && <ErrorNote error={job.error} compact />}
      </div>
      <div className="flex shrink-0 items-center gap-0.5 opacity-80 transition-opacity group-hover:opacity-100">
        {active && (
          <IconButton label="Pause" onClick={() => onCommand("pause", job)}>
            <Pause className="size-4" />
          </IconButton>
        )}
        {job.state === "queued" && (
          <IconButton label="Pause" onClick={() => onCommand("pause", job)}>
            <Pause className="size-4" />
          </IconButton>
        )}
        {(job.state === "paused" || job.state === "interrupted") && (
          <IconButton label="Resume" tone="accent" onClick={() => onCommand("resume", job)}>
            <Play className="size-4" />
          </IconButton>
        )}
        {(job.state === "failed" || job.state === "cancelled" || (job.state === "completed" && job.file_missing)) && (
          <IconButton label="Retry" tone="accent" onClick={() => onCommand("retry", job)}>
            <RotateCcw className="size-4" />
          </IconButton>
        )}
        {job.state === "completed" && !job.file_missing && (
          <>
            <IconButton label="Open" onClick={() => onCommand("open", job)}>
              <ExternalLink className="size-4" />
            </IconButton>
            <IconButton label="Show in Finder" onClick={() => onCommand("reveal", job)}>
              <FolderSearch className="size-4" />
            </IconButton>
          </>
        )}
        {(active || job.state === "queued" || job.state === "paused" || job.state === "interrupted") && (
          <IconButton label="Cancel" tone="danger" onClick={() => onCommand("cancel", job)}>
            <Square className="size-3.5" />
          </IconButton>
        )}
        {!active && (
          <IconButton label="Remove from list" tone="danger" onClick={() => onCommand("remove", job)}>
            <Trash2 className="size-4" />
          </IconButton>
        )}
      </div>
    </li>
  );
});
