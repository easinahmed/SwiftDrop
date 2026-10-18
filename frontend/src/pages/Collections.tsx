import { useState } from "react";
import { ChevronDown, Layers, Pause, Play, RotateCcw } from "lucide-react";
import { api } from "../lib/api";
import { pluralize } from "../lib/format";
import { errorMessage, useStore } from "../lib/store";
import type { Collection } from "../lib/types";
import { useJobCommand } from "../lib/useJobCommand";
import { JobRow } from "../components/JobRow";
import { Thumb } from "../components/media";
import { Badge, Button, cx, EmptyState, PageHeader, ProgressBar } from "../components/ui";

function CollectionCard({ collection }: { collection: Collection }) {
  const jobs = useStore((s) => s.jobs);
  const toast = useStore((s) => s.toast);
  const onCommand = useJobCommand();
  const [open, setOpen] = useState(false);
  const c = collection.counts;
  const active = c.downloading + c.processing;
  const waiting = c.queued;
  const paused = c.paused + c.interrupted;
  const failed = c.failed;
  const done = collection.completed === collection.count;
  const items = collection.item_ids.map((id) => jobs[id]).filter(Boolean);

  const act = async (action: "pause" | "resume" | "retry", ids: string[]) => {
    try {
      await api.jobAction(action, ids);
    } catch (error) {
      toast("error", errorMessage(error));
    }
  };

  const idsIn = (states: string[]) => items.filter((j) => states.includes(j.state)).map((j) => j.id);

  return (
    <section className="card overflow-hidden animate-fade-in">
      <div className="flex items-center gap-4 px-5 py-4">
        <Thumb kind="video" src={collection.thumbnail} playlist size={52} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-[14px] font-semibold">{collection.title}</h2>
            {done ? (
              <Badge tone="success">Complete</Badge>
            ) : active ? (
              <Badge tone="accent">Downloading</Badge>
            ) : paused ? (
              <Badge tone="warning">Paused</Badge>
            ) : null}
          </div>
          <div className="mt-0.5 text-[12px] text-ink-3">
            {[collection.source, collection.extractor].filter(Boolean).join(" · ")}
          </div>
          <div className="mt-2.5 flex items-center gap-3">
            <ProgressBar value={collection.progress} tone={done ? "success" : "accent"} className="max-w-[420px]" label="Playlist progress" />
            <span className="shrink-0 text-[12px] tabular-nums text-ink-2">
              {collection.completed} of {collection.count} downloaded
              {failed ? ` · ${failed} failed` : ""}
              {waiting ? ` · ${waiting} waiting` : ""}
            </span>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {active + waiting > 0 && (
            <Button size="sm" icon={<Pause className="size-3.5" />} onClick={() => act("pause", idsIn(["downloading", "processing", "queued"]))}>
              Pause
            </Button>
          )}
          {paused > 0 && (
            <Button size="sm" icon={<Play className="size-3.5" />} onClick={() => act("resume", idsIn(["paused", "interrupted"]))}>
              Resume
            </Button>
          )}
          {failed > 0 && (
            <Button size="sm" icon={<RotateCcw className="size-3.5" />} onClick={() => act("retry", idsIn(["failed"]))}>
              Retry failed
            </Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            icon={<ChevronDown className={cx("size-3.5 transition-transform", open && "rotate-180")} />}
          >
            {open ? "Hide" : "Show"} items
          </Button>
        </div>
      </div>
      {open && (
        <ul className="border-t border-line bg-surface-2/50">
          {items.map((job) => (
            <JobRow key={job.id} job={job} onCommand={onCommand} compact />
          ))}
        </ul>
      )}
    </section>
  );
}

export function CollectionsPage() {
  const collections = useStore((s) => s.collections);
  const setPage = useStore((s) => s.setPage);
  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Playlists"
        subtitle={
          collections.length
            ? `${pluralize(collections.length, "playlist")} and collections in your queue`
            : "Playlists, albums and channels you download are grouped here."
        }
      />
      <div className="min-h-0 flex-1 space-y-3 overflow-auto px-8 pb-8">
        {collections.length === 0 ? (
          <EmptyState
            icon={<Layers className="size-6" />}
            title="No playlists yet"
            body="Paste a playlist, album or podcast feed link. You can pick individual items before downloading, and track the whole collection here."
            action={
              <Button variant="primary" onClick={() => setPage("home")}>
                Add a playlist
              </Button>
            }
          />
        ) : (
          collections.map((c) => <CollectionCard key={c.id} collection={c} />)
        )}
      </div>
    </div>
  );
}
