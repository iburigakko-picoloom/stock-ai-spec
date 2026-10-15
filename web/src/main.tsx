import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, HashRouter } from "react-router-dom";
import { isAndroid } from "./mobile/native";
import { App } from "./App";
import "./styles.css";

const Router = isAndroid() ? HashRouter : BrowserRouter;
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Router>
      <App />
    </Router>
  </StrictMode>,
);

if (!isAndroid() && "serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // A failed service worker must not affect the live, no-store API path.
    });
  });
}
