// The keyboard shortcut that opens copied links, stored as "ctrl+alt+d" (see swiftdrop/hotkey.py).

export type Modifier = "ctrl" | "alt" | "shift" | "cmd";

export const MODIFIERS: Modifier[] = ["ctrl", "alt", "shift", "cmd"];
export const SHORTCUT_KEYS = [..."ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"];
export const DEFAULT_SHORTCUT = "ctrl+alt+d";

const MAC_SYMBOLS: Record<Modifier, string> = { ctrl: "⌃", alt: "⌥", shift: "⇧", cmd: "⌘" };
const MAC_NAMES: Record<Modifier, string> = { ctrl: "Control", alt: "Option", shift: "Shift", cmd: "Command" };
const WINDOWS_NAMES: Record<Modifier, string> = { ctrl: "Ctrl", alt: "Alt", shift: "Shift", cmd: "Win" };

export interface Shortcut {
  modifiers: Modifier[];
  key: string; // "A"–"Z" or "0"–"9"
}

export function parseShortcut(text: string): Shortcut {
  const parts = text.toLowerCase().split("+");
  const key = (parts.pop() ?? "").toUpperCase();
  return { modifiers: MODIFIERS.filter((m) => parts.includes(m)), key };
}

export function composeShortcut({ modifiers, key }: Shortcut): string {
  return [...MODIFIERS.filter((m) => modifiers.includes(m)), key.toLowerCase()].join("+");
}

/** ⌃⌥D on a Mac, Ctrl+Alt+D on Windows. */
export function formatShortcut(text: string, mac: boolean): string {
  const { modifiers, key } = parseShortcut(text);
  return mac ? modifiers.map((m) => MAC_SYMBOLS[m]).join("") + key : [...modifiers.map((m) => WINDOWS_NAMES[m]), key].join("+");
}

/** The picker's checkbox label for a modifier. */
export function modifierName(modifier: Modifier, mac: boolean): string {
  return mac ? `${MAC_SYMBOLS[modifier]} ${MAC_NAMES[modifier]}` : WINDOWS_NAMES[modifier];
}

/** The modifiers this platform offers (Command is Mac only). */
export function platformModifiers(mac: boolean): Modifier[] {
  return mac ? MODIFIERS : MODIFIERS.filter((m) => m !== "cmd");
}
