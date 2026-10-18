import { useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  File,
  FileAudio,
  FileImage,
  FileVideo,
  Link2,
  ListVideo,
} from "lucide-react";
import type { ErrorInfo, JobState, MediaKind } from "../lib/types";
import { useStore } from "../lib/store";
import { Badge, cx } from "./ui";

const KIND_STYLE: Record<MediaKind, { icon: typeof File; className: string }> = {
  video: { icon: FileVideo, className: "text-[#6a4ff0] bg-[rgb(106_79_240/0.12)]" },
  audio: { icon: FileAudio, className: "text-[#e5484d] bg-[rgb(229_72_77/0.11)]" },
  image: { icon: FileImage, className: "text-[#12a594] bg-[rgb(18_165_148/0.12)]" },
  other: { icon: File, className: "text-ink-2 bg-surface-3" },
  unknown: { icon: Link2, className: "text-ink-2 bg-surface-3" },
};

export function Thumb({
  kind,
  src,
  playlist,
  size = 44,
}: {
  kind: MediaKind;
  src?: string | null;
  playlist?: boolean;
  size?: number;
}) {
  const showThumbnails = useStore((s) => s.settings?.show_thumbnails ?? true);
  const [failed, setFailed] = useState(false);
  const style = KIND_STYLE[kind] ?? KIND_STYLE.unknown;
  const Icon = playlist ? ListVideo : style.icon;
  const safeSrc = src && /^https?:\/\//i.test(src) ? src : null;
  const width = Math.round(size * 1.45);
  if (safeSrc && showThumbnails && !failed) {
    return (
      <div
        className="relative shrink-0 overflow-hidden rounded-[9px] bg-surface-3 shadow-[inset_0_0_0_1px_var(--line)]"
        style={{ width, height: size }}
      >
        <img
          src={safeSrc}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          draggable={false}
          onError={() => setFailed(true)}
          className="size-full object-cover"
        />
        {playlist && (
          <div className="absolute inset-y-0 right-0 flex w-1/3 items-center justify-center bg-black/55 text-white">
            <ListVideo className="size-4" />
          </div>
        )}
      </div>
    );
  }
  return (
    <div
      className={cx("flex shrink-0 items-center justify-center rounded-[9px]", style.className)}
      style={{ width, height: size }}
      aria-hidden
    >
      <Icon className="size-[18px]" strokeWidth={1.8} />
    </div>
  );
}

const STATE_LABEL: Record<JobState, string> = {
  queued: "Queued",
  downloading: "Downloading",
  processing: "Processing",
  paused: "Paused",
  interrupted: "Interrupted",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function StateBadge({ state }: { state: JobState }) {
  const tone =
    state === "completed"
      ? "success"
      : state === "failed"
        ? "danger"
        : state === "downloading" || state === "processing"
          ? "accent"
          : state === "paused" || state === "interrupted"
            ? "warning"
            : "neutral";
  return <Badge tone={tone}>{STATE_LABEL[state]}</Badge>;
}

export function ErrorNote({ error, compact }: { error: ErrorInfo; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <div className={cx("selectable text-[12px]", compact ? "mt-1" : "mt-2")}>
      <div className="flex items-start gap-1.5 text-danger">
        <AlertTriangle className="mt-[1px] size-3.5 shrink-0" />
        <span>
          <span className="font-medium">{error.title}.</span> <span className="text-ink-2">{error.message}</span>
        </span>
      </div>
      {(error.hint || error.detail) && (
        <div className="ml-5">
          {error.hint && <p className="mt-0.5 text-ink-2">{error.hint}</p>}
          {error.detail && (
            <>
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                className="mt-1 inline-flex items-center gap-0.5 text-[11.5px] font-medium text-ink-3 hover:text-ink-2"
              >
                Technical details
                <ChevronDown className={cx("size-3 transition-transform", open && "rotate-180")} />
              </button>
              {open && (
                <pre className="mt-1 max-h-40 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-surface-3 p-2 font-mono text-[11px] text-ink-2">
                  {error.detail}
                </pre>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
