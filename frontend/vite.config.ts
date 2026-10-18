import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The UI is loaded from disk by WKWebView (file://), so assets use relative paths
// and the build lands inside the Python package.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: fileURLToPath(new URL("../swiftdrop/ui/web", import.meta.url)),
    emptyOutDir: true,
    target: "safari16",
    sourcemap: false,
    chunkSizeWarningLimit: 800,
  },
  server: { port: 5199, strictPort: true },
});
