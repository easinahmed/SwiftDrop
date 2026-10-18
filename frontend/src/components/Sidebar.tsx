import { ArrowDownToLine, ClipboardList, Download, History, Layers, Settings as SettingsIcon } from "lucide-react";
import type { ReactNode } from "react";
import { formatSpeed } from "../lib/format";
import { useStore, type Page } from "../lib/store";
import { cx } from "./ui";

export function AppMark({ size = 30 }: { size?: number }) {
  return (
    <div
      className="gradient-accent flex items-center justify-center rounded-[9px] text-white shadow-[0_2px_6px_rgb(47_109_246/0.35),inset_0_1px_0_rgb(255_255_255/0.25)]"
      style={{ width: size, height: size }}
      aria-hidden
    >
      <ArrowDownToLine style={{ width: size * 0.55, height: size * 0.55 }} strokeWidth={2.4} />
    </div>
  );
}

function NavItem({
  page,
  icon,
  label,
  badge,
  shortcut,
}: {
  page: Page;
  icon: ReactNode;
  label: string;
  badge?: ReactNode;
  shortcut: string;
}) {
  const current = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);
  const active = current === page;
  return (
    <button
      type="button"
      onClick={() => setPage(page)}
      aria-current={active ? "page" : undefined}
      title={`${label} (${shortcut})`}
      className={cx(
        "group flex h-[32px] w-full items-center gap-2.5 rounded-[8px] px-2.5 text-[13px] transition-colors duration-150",
        active ? "bg-sidebar-active font-semibold text-ink" : "text-ink-2 hover:bg-sidebar-hover hover:text-ink",
      )}
    >
      <span className={cx("transition-colors", active ? "text-accent" : "text-ink-3 group-hover:text-ink-2")}>
        {icon}
      </span>
      <span className="flex-1 text-left">{label}</span>
      {badge}
    </button>
  );
}

function Count({ value, tone = "neutral" }: { value: number; tone?: "neutral" | "accent" | "danger" }) {
  if (!value) return null;
  return (
    <span
      className={cx(
        "min-w-[20px] rounded-full px-1.5 text-center text-[11px] font-semibold tabular-nums leading-[18px]",
        tone === "accent" ? "bg-accent text-white" : tone === "danger" ? "bg-danger text-white" : "bg-line text-ink-2",
      )}
    >
      {value > 999 ? "999+" : value}
    </span>
  );
}

export function Sidebar() {
  const app = useStore((s) => s.app);
  const stats = useStore((s) => s.stats);
  const collections = useStore((s) => s.collections.length);
  const clipboardOn = useStore((s) => s.settings?.clipboard_monitoring ?? false);
  const failed = stats.counts.failed;
  const speed = formatSpeed(stats.speed);
  return (
    <aside className="flex w-[218px] shrink-0 flex-col border-r border-line bg-sidebar">
      <div className="flex items-center gap-2.5 px-4 pb-5 pt-5">
        <AppMark />
        <div className="leading-tight">
          <div className="font-display text-[15px] font-semibold tracking-[-0.01em]">{app?.name ?? "SwiftDrop"}</div>
          <div className="text-[11px] text-ink-3">Media downloader</div>
        </div>
      </div>
      <nav className="flex flex-col gap-0.5 px-2.5" aria-label="Sections">
        <NavItem page="home" icon={<Download className="size-[17px]" />} label="New Download" shortcut="⌘1" />
        <NavItem
          page="downloads"
          icon={<ClipboardList className="size-[17px]" />}
          label="Downloads"
          shortcut="⌘2"
          badge={
            stats.active ? <Count value={stats.active} tone="accent" /> : <Count value={failed} tone="danger" />
          }
        />
        <NavItem
          page="collections"
          icon={<Layers className="size-[17px]" />}
          label="Playlists"
          shortcut="⌘3"
          badge={<Count value={collections} />}
        />
        <NavItem page="history" icon={<History className="size-[17px]" />} label="History" shortcut="⌘4" />
        <NavItem
          page="settings"
          icon={<SettingsIcon className="size-[17px]" />}
          label="Settings"
          shortcut="⌘,"
        />
      </nav>
      <div className="mt-auto space-y-2 px-4 pb-4">
        {clipboardOn && (
          <div className="flex items-center gap-1.5 text-[11.5px] text-ink-3" title="Clipboard monitoring is on">
            <span className="size-1.5 rounded-full bg-success" />
            Watching clipboard for links
          </div>
        )}
        {stats.active > 0 ? (
          <div className="rounded-[10px] border border-line bg-surface px-3 py-2.5 shadow-card">
            <div className="flex items-center justify-between text-[11.5px]">
              <span className="font-medium text-ink">
                {stats.active} active{stats.queued ? ` · ${stats.queued} waiting` : ""}
              </span>
            </div>
            {speed && <div className="mt-0.5 text-[11.5px] tabular-nums text-ink-3">{speed}</div>}
          </div>
        ) : null}
        <div className="border-t border-line pt-2.5 leading-tight">
          <div className="text-[11px] font-medium text-ink-2">Developed by Easin Codes</div>
          <div className="mt-0.5 text-[10.5px] text-ink-3">v{app?.version}</div>
        </div>
      </div>
    </aside>
  );
}
