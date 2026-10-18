import { describe, expect, it } from "vitest";
import { installDropGuard } from "./dropGuard";

type Handler = (e: FakeEvent) => void;
interface FakeEvent {
  type: string;
  target: unknown;
  defaultPrevented: boolean;
  preventDefault(): void;
}

function fakeWindow() {
  const handlers = new Map<string, { fn: Handler; capture: unknown }>();
  const win = {
    addEventListener(type: string, fn: Handler, opts?: unknown) {
      handlers.set(type, { fn, capture: opts });
    },
    removeEventListener(type: string) {
      handlers.delete(type);
    },
  };
  const fire = (type: string, target: unknown) => {
    const e: FakeEvent = {
      type,
      target,
      defaultPrevented: false,
      preventDefault() {
        this.defaultPrevented = true;
      },
    };
    handlers.get(type)?.fn(e);
    return e;
  };
  return { win: win as unknown as Window, fire, handlers };
}

describe("installDropGuard", () => {
  const body = { name: "body" };
  const area = { name: "textarea" };
  const allowed = (t: EventTarget | null) => (t as unknown) === area;

  it("prevents drops and dragovers outside the allowed target", () => {
    const { win, fire } = fakeWindow();
    installDropGuard(win, allowed);
    expect(fire("drop", body).defaultPrevented).toBe(true);
    expect(fire("dragover", body).defaultPrevented).toBe(true);
  });

  it("leaves drops on the allowed target alone", () => {
    const { win, fire } = fakeWindow();
    installDropGuard(win, allowed);
    expect(fire("drop", area).defaultPrevented).toBe(false);
    expect(fire("dragover", area).defaultPrevented).toBe(false);
  });

  it("returns a disposer that removes the listeners", () => {
    const { win, fire, handlers } = fakeWindow();
    const dispose = installDropGuard(win, allowed);
    dispose();
    expect(handlers.size).toBe(0);
    expect(fire("drop", body).defaultPrevented).toBe(false);
  });
});
