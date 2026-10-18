import { useEffect } from "react";
import { AlertTriangle, ClipboardCheck, Loader2, X } from "lucide-react";
import { api, isPreviewMode } from "./lib/api";
import { pluralize } from "./lib/format";
import { errorMessage, useStore, type Page } from "./lib/store";
import { Sidebar, AppMark } from "./components/Sidebar";
import { Toasts } from "./components/overlay";
import { Button } from "./components/ui";
import { DownloaderPage } from "./pages/Downloader";
import { DownloadsPage } from "./pages/Downloads";
import { CollectionsPage } from "./pages/Collections";
import { HistoryPage } from "./pages/History";
import { SettingsPage } from "./pages/Settings";

const SHORTCUTS: Record<string, Page> = {
  "1": "home",
  "2": "downloads",
  "3": "collections",
  "4": "history",
  ",": "settings",
};

function useTheme() {
  const theme = useStore((s) => s.settings?.theme ?? "system");
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && media.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
}

function ClipboardBanner() {
  const clipboard = useStore((s) => s.clipboard);
  const dismiss = useStore((s) => s.dismissClipboard);
  const addPreview = useStore((s) => s.addPreview);
  const setPage = useStore((s) => s.setPage);
  const toast = useStore((s) => s.toast);
  if (!clipboard) return null;
  const add = async () => {
    try {
      const result = await api.analyze(clipboard.urls.join("\n"), true);
      addPreview(result.added);
      setPage("home");
      toast("success", `Added ${pluralize(result.added.length, "link")} from the clipboard`);
    } catch (error) {
      toast("error", errorMessage(error));
    } finally {
      dismiss();
    }
  };
  return (
    <div className="animate-pop fixed left-1/2 top-4 z-40 flex -translate-x-1/2 items-center gap-3 rounded-[12px] border border-line bg-surface py-2 pl-3.5 pr-2 shadow-pop">
      <ClipboardCheck className="size-4 text-accent" />
      <span className="text-[12.5px]">
        <span className="font-semibold">{pluralize(clipboard.count, "link")}</span> copied to the clipboard
      </span>
      <Button size="sm" variant="primary" onClick={add}>
        Add to list
      </Button>
      <button type="button" aria-label="Dismiss" onClick={dismiss} className="rounded p-1 text-ink-3 hover:text-ink">
        <X className="size-3.5" />
      </button>
    </div>
  );
}

function Splash({ error }: { error?: string | null }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <AppMark size={52} />
      {error ? (
        <>
          <div className="flex items-center gap-2 text-[14px] font-semibold text-danger">
            <AlertTriangle className="size-4" /> {error}
          </div>
          <Button onClick={() => window.location.reload()}>Try again</Button>
        </>
      ) : (
        <Loader2 className="size-5 animate-spin text-ink-3" aria-label="Loading" />
      )}
    </div>
  );
}

export default function App() {
  const status = useStore((s) => s.status);
  const fatal = useStore((s) => s.fatal);
  const page = useStore((s) => s.page);
  const init = useStore((s) => s.init);
  const resync = useStore((s) => s.resync);
  const setPage = useStore((s) => s.setPage);
  useTheme();

  useEffect(() => {
    void init();
  }, [init]);

  useEffect(() => {
    const onFocus = () => void resync();
    const onKey = (e: KeyboardEvent) => {
      if (!e.metaKey || e.altKey || e.ctrlKey) return;
      const target = SHORTCUTS[e.key];
      if (target) {
        e.preventDefault();
        setPage(target);
      }
    };
    window.addEventListener("focus", onFocus);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("keydown", onKey);
    };
  }, [resync, setPage]);

  if (status !== "ready") return <Splash error={fatal} />;

  return (
    <div className="flex h-full">
      <Sidebar />
      <main className="relative min-w-0 flex-1 bg-bg" key={page}>
        {isPreviewMode() && (
          <div className="bg-warning-soft px-8 py-1.5 text-[11.5px] font-medium text-warning">
            Preview mode — UI running in a browser without the download engine. Nothing is downloaded.
          </div>
        )}
        <div className="animate-fade-in h-full">
          {page === "home" && <DownloaderPage />}
          {page === "downloads" && <DownloadsPage />}
          {page === "collections" && <CollectionsPage />}
          {page === "history" && <HistoryPage />}
          {page === "settings" && <SettingsPage />}
        </div>
      </main>
      <ClipboardBanner />
      <Toasts />
    </div>
  );
}
