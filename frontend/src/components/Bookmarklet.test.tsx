import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { applyBookmarkletHref, BOOKMARKLET, Bookmarklet } from "./Bookmarklet";

describe("Send to SwiftDrop bookmark", () => {
  it("renders a draggable link without a React-managed href", () => {
    const html = renderToStaticMarkup(<Bookmarklet />);
    expect(html).toContain("Send to SwiftDrop");
    expect(html).toContain('draggable="true"');
    expect(html).not.toContain("href=");
  });

  it("gets its javascript: href from the ref callback", () => {
    const attributes: Record<string, string> = {};
    applyBookmarkletHref({ setAttribute: (name: string, value: string) => void (attributes[name] = value) });
    expect(attributes.href).toBe(BOOKMARKLET);
    applyBookmarkletHref(null); // unmount
  });

  it("sends the current page as an encoded swiftdrop:// link", () => {
    const code = BOOKMARKLET.replace(/^javascript:/, "");
    const location = { href: "https://www.youtube.com/watch?v=abc&t=1" };
    new Function("location", code)(location);
    expect(location.href).toBe(
      "swiftdrop://add?url=https%3A%2F%2Fwww.youtube.com%2Fwatch%3Fv%3Dabc%26t%3D1",
    );
  });
});
