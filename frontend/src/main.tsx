import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

// Stale chunk recovery: when a lazy import fails because an old chunk hash no
// longer exists on the server (post-deploy), reload once to pick up the new build.
window.addEventListener("unhandledrejection", (event) => {
  const msg = (event.reason as Error)?.message ?? "";
  if (
    msg.includes("Failed to fetch dynamically imported module") ||
    msg.includes("Importing a module script failed") ||
    (event.reason as Error)?.name === "ChunkLoadError"
  ) {
    window.location.reload();
  }
});

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
