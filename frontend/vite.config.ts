import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI is loaded from disk by WKWebView (file://), so assets use relative paths
// and the build lands inside the Python package. `--mode demo` builds the web demo
// instead: the same UI driven by the simulated engine, written to ../web-dist/demo.
export default defineConfig(({ mode }) => {
  const demo = mode === "demo";
  return {
    base: "./",
    plugins: [react(), tailwindcss()],
    define: { __DEMO__: JSON.stringify(demo) },
    build: {
      outDir: fileURLToPath(new URL(demo ? "../web-dist/demo" : "../swiftdrop/ui/web", import.meta.url)),
      emptyOutDir: true,
      target: "safari16",
      sourcemap: false,
      chunkSizeWarningLimit: 800,
    },
    server: { port: 5199, strictPort: true },
  };
});
