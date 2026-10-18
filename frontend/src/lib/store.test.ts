import { beforeEach, describe, expect, it } from "vitest";
import { useStore } from "./store";
import type { Job, PreviewItem } from "./types";

function preview(id: string, patch: Partial<PreviewItem> = {}): PreviewItem {
  return {
    id, url: `https://e.com/${id}`, source: "e.com", status: "pending",
    link: { provider: "direct", kind: "video", label: "MP4 file", extractor: null, playlist_hint: false, blocked: null },
    info: null, kind: "video", title: null, error: null, in_queue: null, downloaded_before: null, order: 0, ...patch,
  };
}

describe("store push merging", () => {
  beforeEach(() => useStore.setState({ preview: {}, selection: {}, jobs: {} }));

  it("selects new links by default but not blocked, queued or already-downloaded ones", () => {
    useStore.getState().addPreview([
      preview("a"),
      preview("b", { status: "blocked" }),
      preview("c", { in_queue: "downloading" }),
      preview("d", { downloaded_before: { filepath: "/x", finished_at: 1, title: "x" } }),
    ]);
    expect(useStore.getState().selection).toEqual({ a: true, b: false, c: false, d: false });
  });

  it("deselects an item when inspection finds a permanent error, and removes items", () => {
    useStore.getState().addPreview([preview("a")]);
    const error = { code: "drm", title: "Protected", message: "m", hint: "", detail: "", retryable: false };
    useStore.getState().applyPush({ preview: [preview("a", { status: "error", error })] });
    expect(useStore.getState().selection.a).toBe(false);
    useStore.getState().applyPush({ removed_preview: ["a"] });
    expect(useStore.getState().preview.a).toBeUndefined();
  });

  it("merges job updates and removals", () => {
    const job = { id: "j1", order: 1, state: "downloading", progress: 0.5 } as Job;
    useStore.getState().applyPush({ jobs: [job] });
    useStore.getState().applyPush({ jobs: [{ ...job, state: "completed", progress: 1 }] });
    expect(useStore.getState().jobs.j1.state).toBe("completed");
    useStore.getState().applyPush({ removed_jobs: ["j1"] });
    expect(useStore.getState().jobs.j1).toBeUndefined();
  });
});
