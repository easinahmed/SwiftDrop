import { describe, expect, it } from "vitest";
import { composeShortcut, formatShortcut, modifierName, parseShortcut, platformModifiers } from "./shortcut";

describe("keyboard shortcut helpers", () => {
  it("shows the shortcut the way each platform writes it", () => {
    expect(formatShortcut("ctrl+alt+d", true)).toBe("⌃⌥D");
    expect(formatShortcut("ctrl+alt+d", false)).toBe("Ctrl+Alt+D");
    expect(formatShortcut("ctrl+alt+shift+cmd+9", true)).toBe("⌃⌥⇧⌘9");
  });

  it("round-trips through the picker in the stored order", () => {
    const parsed = parseShortcut("shift+ctrl+k");
    expect(parsed).toEqual({ modifiers: ["ctrl", "shift"], key: "K" });
    expect(composeShortcut({ modifiers: ["cmd", "alt"], key: "7" })).toBe("alt+cmd+7");
  });

  it("offers Command only on a Mac", () => {
    expect(platformModifiers(false)).toEqual(["ctrl", "alt", "shift"]);
    expect(modifierName("alt", true)).toBe("⌥ Option");
    expect(modifierName("alt", false)).toBe("Alt");
  });
});
