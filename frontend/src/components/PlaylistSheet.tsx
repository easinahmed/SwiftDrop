import { useEffect, useMemo, useState } from "react";
import { Loader2, Search } from "lucide-react";
import { api } from "../lib/api";
import { formatDuration, pluralize } from "../lib/format";
import { errorMessage } from "../lib/store";
import type { PlaylistEntry, PreviewItem } from "../lib/types";
import { Modal } from "./overlay";
import { Button, Checkbox, cx } from "./ui";

export function PlaylistSheet({
  item,
  initial,
  onClose,
  onApply,
}: {
  item: PreviewItem;
  initial: string[] | null;
  onClose: () => void;
  onApply: (entries: string[] | null) => void;
}) {
  const [entries, setEntries] = useState<PlaylistEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    api
      .playlistEntries(item.id)
      .then((list) => {
        if (!alive) return;
        setEntries(list);
        const available = list.filter((e) => e.available).map((e) => e.id);
        setSelected(new Set(initial ?? available));
      })
      .catch((e) => alive && setError(errorMessage(e)));
    return () => {
      alive = false;
    };
  }, [item.id, initial]);

  const visible = useMemo(() => {
    if (!entries) return [];
    const q = query.trim().toLowerCase();
    return q ? entries.filter((e) => e.title.toLowerCase().includes(q)) : entries;
  }, [entries, query]);

  const available = entries?.filter((e) => e.available) ?? [];
  const allSelected = available.length > 0 && available.every((e) => selected.has(e.id));

  const toggle = (id: string, value: boolean) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (value) next.add(id);
      else next.delete(id);
      return next;
    });

  return (
    <Modal
      open
      onClose={onClose}
      width={640}
      title={item.info?.title || "Playlist"}
      subtitle={entries ? `${pluralize(entries.length, "item")} · ${selected.size.toLocaleString()} selected` : "Loading…"}
      footer={
        <>
          <span className="mr-auto text-[12px] text-ink-3">Unavailable items are skipped automatically.</span>
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!entries}
            onClick={() => onApply(allSelected ? null : available.filter((e) => selected.has(e.id)).map((e) => e.id))}
          >
            {selected.size ? `Use ${pluralize(selected.size, "item")}` : "Skip playlist"}
          </Button>
        </>
      }
    >
      {error && <p className="px-5 py-6 text-[13px] text-danger">{error}</p>}
      {!entries && !error && (
        <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-ink-3">
          <Loader2 className="size-4 animate-spin" /> Loading items…
        </div>
      )}
      {entries && (
        <>
          <div className="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-surface px-5 py-2.5">
            <Checkbox
              checked={allSelected}
              indeterminate={!allSelected && selected.size > 0}
              onChange={(v) => setSelected(new Set(v ? available.map((e) => e.id) : []))}
              label="Select all items"
            />
            <div className="relative flex-1">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-ink-3" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter items"
                aria-label="Filter playlist items"
                className="h-7 w-full rounded-[7px] border border-line bg-surface-2 pl-8 pr-2 text-[12.5px] outline-none focus:border-accent"
              />
            </div>
          </div>
          <ul className="py-1">
            {visible.map((entry) => (
              <li
                key={entry.id}
                className={cx("row-cv flex items-center gap-3 px-5 py-2", !entry.available && "opacity-45")}
                style={{ containIntrinsicSize: "auto 36px" }}
              >
                <Checkbox
                  checked={selected.has(entry.id)}
                  disabled={!entry.available}
                  onChange={(v) => toggle(entry.id, v)}
                  label={`Select ${entry.title}`}
                />
                <span className="w-8 shrink-0 text-right text-[11.5px] tabular-nums text-ink-3">{entry.index}</span>
                <span className="min-w-0 flex-1 truncate text-[13px]">{entry.title}</span>
                <span className="shrink-0 text-[11.5px] tabular-nums text-ink-3">
                  {entry.available ? formatDuration(entry.duration) : "Unavailable"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </Modal>
  );
}
