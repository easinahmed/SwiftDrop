import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";
import { installDropGuard } from "./lib/dropGuard";

installDropGuard(window, (t) => t instanceof HTMLTextAreaElement && t.dataset.dropTarget === "links");

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
