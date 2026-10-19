import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { installDropGuard } from "./lib/dropGuard";
import { CaptureDialog } from "./pages/CaptureDialog";

installDropGuard(window, (t) => t instanceof HTMLTextAreaElement && t.dataset.dropTarget === "links");

// A browser download's confirm window loads the same page at #/capture/<id>.
const CAPTURE_ROUTE = "#/capture/";
const captureId = window.location.hash.startsWith(CAPTURE_ROUTE)
  ? window.location.hash.slice(CAPTURE_ROUTE.length)
  : null;

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(<StrictMode>{captureId ? <CaptureDialog id={captureId} /> : <App />}</StrictMode>);
}
