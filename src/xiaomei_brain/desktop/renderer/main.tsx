import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { installDesktopEmbodiment } from "./embodiment";
import {
  installRendererErrorReporting,
  RendererErrorBoundary,
} from "./components/RendererErrorBoundary";
import "./i18n";
import "./styles/ui.css";
import "./styles/global.css";
import "./styles/menubar.css";
import "./styles/sidebar.css";
import "./styles/home.css";
import "./styles/terminal.css";
import "./styles/about.css";
import "./styles/agent-dialog.css";
import "./styles/identity-settings.css";
import "./styles/agent-settings.css";
import "./styles/settings-center.css";
import "./styles/unified-search.css";

// ─── 平台标记 ───
document.body.setAttribute("data-electron-desktop", "true");
document.body.setAttribute("data-application-name", "xiaomei-brain");
const isMac = navigator.platform.toLowerCase().includes("mac");
const isWindows = navigator.platform.toLowerCase().includes("win");
document.body.setAttribute(
  "data-platform",
  isMac ? "mac" : isWindows ? "windows" : "linux"
);
installDesktopEmbodiment();
installRendererErrorReporting();

const root = createRoot(document.getElementById("root")!);
root.render(
  <RendererErrorBoundary>
    <App />
  </RendererErrorBoundary>,
);
