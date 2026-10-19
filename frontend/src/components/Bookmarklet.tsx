// "Send to SwiftDrop": a bookmark the user drags to the browser's bookmarks bar. Clicking it
// on any page opens swiftdrop://add?url=<that page>, which SwiftDrop shows in its confirm
// window. React 19 refuses javascript: URLs as href props, so the attribute is set on the
// DOM node after mount; clicking it inside SwiftDrop does nothing.

import type { MouseEvent } from "react";
import { Bookmark } from "lucide-react";

export const BOOKMARKLET = "javascript:location.href='swiftdrop://add?url='+encodeURIComponent(location.href)";

/** Ref callback: give the anchor its javascript: href without going through React's href prop. */
export function applyBookmarkletHref(node: Pick<HTMLAnchorElement, "setAttribute"> | null): void {
  node?.setAttribute("href", BOOKMARKLET);
}

const ignoreClick = (e: MouseEvent) => e.preventDefault();

export function Bookmarklet() {
  return (
    <a
      ref={applyBookmarkletHref}
      onClick={ignoreClick}
      draggable
      title="Drag to your bookmarks bar"
      className="inline-flex h-7 cursor-grab select-none items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 text-[12px] font-medium text-ink shadow-[0_1px_1px_rgb(0_0_0/0.04)] active:cursor-grabbing"
    >
      <Bookmark className="size-3.5 text-accent" />
      Send to SwiftDrop
    </a>
  );
}
