import { describe, expect, it } from "vitest";
import { countLinks, folderName, formatBytes, formatDuration, formatEta, formatSpeed, shortPath } from "./format";

describe("format helpers", () => {
  it("formats bytes with decimal units like Finder", () => {
    expect(formatBytes(999)).toBe("999 B");
    expect(formatBytes(1_500_000)).toBe("1.5 MB");
    expect(formatBytes(30_000_000)).toBe("30.0 MB");
    expect(formatBytes(null)).toBe("—");
  });

  it("never shows a speed or ETA it cannot know", () => {
    expect(formatSpeed(null)).toBeNull();
    expect(formatSpeed(0)).toBeNull();
    expect(formatSpeed(2_500_000)).toBe("2.5 MB/s");
    expect(formatEta(null)).toBeNull();
    expect(formatEta(42)).toBe("42s left");
    expect(formatEta(3_700)).toBe("1h 1m left");
    expect(formatEta(10 * 86_400)).toBeNull();
  });

  it("formats durations and paths", () => {
    expect(formatDuration(65)).toBe("1:05");
    expect(formatDuration(3_725)).toBe("1:02:05");
    expect(folderName("/Users/me/Downloads/")).toBe("Downloads");
    expect(shortPath("/Users/me/Movies/Clips")).toBe("~/Movies/Clips");
  });

  it("counts links in pasted text", () => {
    expect(countLinks("see https://a.com/x and www.b.org/page\nyoutube.com/watch?v=1")).toBe(3);
    expect(countLinks("no links here")).toBe(0);
  });
});
