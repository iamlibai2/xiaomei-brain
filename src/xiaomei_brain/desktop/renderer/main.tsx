import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./i18n";
import "./styles/ui.css";
import "./styles/global.css";
import "./styles/menubar.css";
import "./styles/sidebar.css";
import "./styles/home.css";
import "./styles/terminal.css";
import "./styles/about.css";
import "./styles/agent-dialog.css";

// ─── 平台标记 ───
document.body.setAttribute("data-electron-desktop", "true");
document.body.setAttribute("data-application-name", "xiaomei-brain");
const isMac = navigator.platform.toLowerCase().includes("mac");
const isWindows = navigator.platform.toLowerCase().includes("win");
document.body.setAttribute(
  "data-platform",
  isMac ? "mac" : isWindows ? "windows" : "linux"
);

const root = createRoot(document.getElementById("root")!);
root.render(<App />);
