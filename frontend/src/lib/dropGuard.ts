/**
 * Stops the webview from navigating to a dropped file (which would replace the UI
 * with the file and, in a browser-like shell, expose the native bridge to it).
 * Drops are only left alone on targets the UI handles itself.
 */
export function installDropGuard(
  win: Window,
  isAllowedTarget: (t: EventTarget | null) => boolean,
): () => void {
  const guard = (e: Event) => {
    if (!isAllowedTarget(e.target)) e.preventDefault();
  };
  win.addEventListener("dragover", guard);
  win.addEventListener("drop", guard);
  return () => {
    win.removeEventListener("dragover", guard);
    win.removeEventListener("drop", guard);
  };
}
