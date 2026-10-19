// The confirm window for a copied or sent link (index.html#/capture/<id>).
// It runs in its own small native window, without the sidebar or the app store. Three
// variants: a file (editable name, size, folder), a video page (quality from Settings,
// folder) and several links ("Add all" puts them in the New Download list).
//
// The window takes focus while the user may be typing in another app, so nothing is
// focused automatically, there is no implicit form submission, and Return / Escape
// only count once the window has had focus for a moment.

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, Folder, Globe, Link2, Loader2 } from "lucide-react";
import { api } from "../lib/api";
import { formatBytes, pluralize, shortPath } from "../lib/format";
import { errorMessage } from "../lib/store";
import type { CaptureDecision, CaptureInfo, Theme } from "../lib/types";
import { Thumb } from "../components/media";
import { AppMark } from "../components/Sidebar";
import { Button } from "../components/ui";

function useDialogTheme(theme: Theme | undefined) {
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const choice = theme ?? "system";
      const dark = choice === "dark" || (choice === "system" && media.matches);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);
}

/** Keys pressed this soon after the window gains focus were meant for another app. */
const KEYBOARD_ARM_MS = 1000;

const OUTCOME_TEXT: Record<CaptureDecision, string> = {
  start: "Added to your downloads",
  later: "Added to your downloads, paused",
  add_all: "Added to New Download",
  cancel: "Cancelled",
};

const HEADINGS: Record<CaptureInfo["kind"], string> = {
  file: "Download this file?",
  page: "Download this video?",
  links: "Download these links?",
};

function SectionLabel({ children, htmlFor }: { children: string; htmlFor?: string }) {
  const className = "block px-0.5 text-[11.5px] font-semibold uppercase tracking-[0.06em] text-ink-3";
  return htmlFor ? (
    <label htmlFor={htmlFor} className={className}>
      {children}
    </label>
  ) : (
    <div className={className}>{children}</div>
  );
}

export function CaptureDialog({ id }: { id: string }) {
  const [info, setInfo] = useState<CaptureInfo | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState<CaptureDecision | null>(null);
  const [outcome, setOutcome] = useState<CaptureDecision | null>(null);
  const nameInput = useRef<HTMLInputElement>(null);
  const focusedAt = useRef(0);
  const stemSelected = useRef(false);
  const keepSelection = useRef(false);
  useDialogTheme(info?.theme);

  useEffect(() => {
    const onFocus = () => {
      focusedAt.current = performance.now();
    };
    onFocus(); // the window opens focused
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, []);

  useEffect(() => {
    api
      .getCapture(id)
      .then((data) => {
        setInfo(data);
        setName(data.filename);
        setFolder(data.folder);
      })
      .catch((e) => setLoadError(errorMessage(e)));
  }, [id]);

  const selectStem = () => {
    // Like Finder's rename: the first click in the name selects it without the extension.
    const input = nameInput.current;
    if (!input || stemSelected.current) return;
    stemSelected.current = true;
    keepSelection.current = true; // the mouseup of this click would otherwise collapse it
    const dot = input.value.lastIndexOf(".");
    input.setSelectionRange(0, dot > 0 ? dot : input.value.length);
  };

  const decide = async (decision: CaptureDecision) => {
    if (busy || outcome) return;
    setBusy(decision);
    setError(null);
    try {
      const result = await api.decideCapture(id, decision, name, folder);
      setOutcome(result.decision); // the app closes this window right away
    } catch (e) {
      setError(errorMessage(e));
      setBusy(null);
    }
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Enter" && e.key !== "Escape") return;
      if (e.target instanceof HTMLButtonElement) return; // the focused button handles its own keys
      e.preventDefault();
      if (e.repeat || e.isComposing || !info) return;
      if (performance.now() - focusedAt.current < KEYBOARD_ARM_MS) return;
      if (e.key === "Escape") void decide("cancel");
      else void decide(info.kind === "links" ? "add_all" : "start");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const chooseFolder = async () => {
    try {
      const chosen = await api.chooseFolder(folder);
      if (chosen) setFolder(chosen);
    } catch (e) {
      setError(errorMessage(e));
    }
  };

  if (loadError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 bg-bg px-8 text-center">
        <AppMark size={40} />
        <p className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
          <AlertTriangle className="size-4 text-warning" /> {loadError}
        </p>
        <p className="text-[12px] text-ink-3">You can close this window.</p>
      </div>
    );
  }

  if (!info) {
    return (
      <div className="flex h-full items-center justify-center bg-bg">
        <Loader2 className="size-5 animate-spin text-ink-3" aria-label="Loading" />
      </div>
    );
  }

  const locked = busy !== null || outcome !== null;
  const many = info.kind === "links";
  const subtitle = many
    ? `${pluralize(info.count, "link")} · ${info.sites.slice(0, 3).join(", ")}${info.sites.length > 3 ? "…" : ""}`
    : info.kind === "page"
      ? [info.label || info.source, info.quality_label].filter(Boolean).join(" · ")
      : `${info.source || "Unknown site"} · ${info.size != null ? formatBytes(info.size) : "Unknown size"}`;

  return (
    <div className="flex h-full flex-col bg-bg">
      <div className="min-h-0 flex-1 px-6 pt-5">
        <div className="flex items-center gap-3.5">
          <Thumb kind={info.media} size={44} playlist={many} />
          <div className="min-w-0">
            <h1 className="font-display text-[16px] font-semibold tracking-[-0.01em] text-ink">{HEADINGS[info.kind]}</h1>
            <p className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[12.5px] text-ink-2" title={info.url}>
              <Globe className="size-3.5 shrink-0 text-ink-3" />
              <span className="truncate tabular-nums">{subtitle}</span>
            </p>
          </div>
        </div>

        {info.kind === "file" && (
          <div className="mt-5">
            <SectionLabel htmlFor="capture-name">File name</SectionLabel>
            <input
              id="capture-name"
              ref={nameInput}
              value={name}
              disabled={locked}
              spellCheck={false}
              autoComplete="off"
              onChange={(e) => setName(e.target.value)}
              onFocus={selectStem}
              onMouseUp={(e) => {
                if (keepSelection.current) e.preventDefault();
                keepSelection.current = false;
              }}
              className="mt-1.5 h-9 w-full rounded-[8px] border border-line-strong bg-surface px-3 text-[13px] text-ink shadow-[0_1px_1px_rgb(0_0_0/0.04)] outline-none transition-colors focus:border-accent disabled:opacity-60"
            />
          </div>
        )}

        {info.kind === "page" && (
          <div className="mt-5">
            <SectionLabel>Link</SectionLabel>
            <div className="mt-1.5 flex h-9 items-center gap-2 rounded-[8px] border border-line bg-surface-2 px-3 text-[13px] text-ink-2">
              <Link2 className="size-4 shrink-0 text-ink-3" />
              <span className="selectable truncate">{info.url}</span>
            </div>
          </div>
        )}

        {many ? (
          <div className="mt-4">
            <SectionLabel>Links</SectionLabel>
            <ul className="selectable mt-1.5 max-h-[118px] overflow-auto rounded-[8px] border border-line bg-surface-2 px-3 py-1.5 text-[12.5px] text-ink-2">
              {info.urls.map((url) => (
                <li key={url} className="truncate py-0.5" title={url}>
                  {url}
                </li>
              ))}
              {info.count > info.urls.length && (
                <li className="py-0.5 text-ink-3">and {pluralize(info.count - info.urls.length, "more link")}</li>
              )}
            </ul>
          </div>
        ) : (
          <div className="mt-4">
            <SectionLabel>Save to</SectionLabel>
            <div className="mt-1.5 flex items-center gap-2">
              <div className="flex h-9 min-w-0 flex-1 items-center gap-2 rounded-[8px] border border-line bg-surface-2 px-3 text-[13px] text-ink-2">
                <Folder className="size-4 shrink-0 text-ink-3" />
                <span className="selectable truncate" title={folder}>
                  {shortPath(folder)}
                </span>
              </div>
              <Button onClick={chooseFolder} disabled={locked}>
                Choose…
              </Button>
            </div>
          </div>
        )}

        <div className="mt-3 min-h-[18px] text-[12px]" aria-live="polite">
          {error ? (
            <p className="flex items-start gap-1.5 text-danger">
              <AlertTriangle className="mt-[1px] size-3.5 shrink-0" /> <span className="selectable">{error}</span>
            </p>
          ) : outcome ? (
            <p className="text-ink-2">{OUTCOME_TEXT[outcome]}</p>
          ) : many ? (
            <p className="text-ink-3">They open in New Download, where you can pick what to keep.</p>
          ) : null}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-line bg-surface px-5 py-3">
        <Button disabled={locked} busy={busy === "cancel"} onClick={() => decide("cancel")}>
          Cancel
        </Button>
        {many ? (
          <Button variant="primary" disabled={locked} busy={busy === "add_all"} onClick={() => decide("add_all")}>
            Add all
          </Button>
        ) : (
          <>
            <Button disabled={locked} busy={busy === "later"} onClick={() => decide("later")}>
              Start later
            </Button>
            <Button
              variant="primary"
              disabled={locked}
              busy={busy === "start"}
              className="min-w-[72px]"
              onClick={() => decide("start")}
            >
              Start
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
