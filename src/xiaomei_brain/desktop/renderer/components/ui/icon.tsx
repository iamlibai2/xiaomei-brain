import React from "react";

export type IconName =
  | "plus"
  | "search"
  | "refresh"
  | "sidebar-panel-left"
  | "sidebar-panel-right"
  | "bell"
  | "settings"
  | "paperclip"
  | "microphone"
  | "camera"
  | "arrow-up"
  | "chevron-down"
  | "chevron-left"
  | "chevron-right"
  | "x"
  | "copy"
  | "file-text"
  | "currency-dollar"
  | "chart-bar"
  | "dots-vertical"
  | "map-pin"
  | "globe"
  | "shield"
  | "robot"
  | "cpu"
  | "folder"
  | "image"
  | "sparkles"
  | "moon"
  | "clock"
  | "info"
  | "external-link"
  | "eye"
  | "maximize"
  | "minimize"
  | "terminal"
  | "play"
  | "pause"
  | "skip-back"
  | "skip-forward"
  | "volume"
  | "volume-muted"
  | "power"
  | "trash";

interface IconProps {
  name: IconName;
  size?: number;
  className?: string;
}

// ── SVG paths (Feather icons style: 24x24 viewBox, stroke="currentColor") ──

const ICON_PATHS: Record<IconName, React.ReactNode> = {
  plus: (
    <>
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
    </>
  ),
  search: (
    <>
      <circle cx="11" cy="11" r="8" />
      <path d="m21 21-4.3-4.3" />
    </>
  ),
  globe: (
    <>
      <circle cx="12" cy="12" r="10" />
      <line x1="2" y1="12" x2="22" y2="12" />
      <path d="M12 2a15.3 15.3 0 0 1 0 20M12 2a15.3 15.3 0 0 0 0 20" />
    </>
  ),
  refresh: (
    <>
      <path d="M3 2v6h6" />
      <path d="M21 12A9 9 0 0 0 6 5.3L3 8" />
      <path d="M21 22v-6h-6" />
      <path d="M3 12a9 9 0 0 0 15 6.7l3-2.7" />
    </>
  ),
  "sidebar-panel-left": (
    <>
      <rect x="1" y="2" width="16" height="14" rx="2" />
      <line x1="4" y1="2" x2="4" y2="16" />
      <line x1="10" y1="7" x2="7" y2="9" />
      <line x1="10" y1="11" x2="7" y2="9" />
    </>
  ),
  "sidebar-panel-right": (
    <>
      <rect x="1" y="2" width="16" height="14" rx="2" />
      <line x1="14" y1="2" x2="14" y2="16" />
      <line x1="8" y1="7" x2="11" y2="9" />
      <line x1="8" y1="11" x2="11" y2="9" />
    </>
  ),
  maximize: (
    <>
      <path d="M8 3H3v5" />
      <path d="m3 3 6 6" />
      <path d="M16 3h5v5" />
      <path d="m21 3-6 6" />
      <path d="M8 21H3v-5" />
      <path d="m3 21 6-6" />
      <path d="M16 21h5v-5" />
      <path d="m21 21-6-6" />
    </>
  ),
  minimize: (
    <>
      <path d="M8 3v5H3" />
      <path d="m3 8 6-6" />
      <path d="M16 3v5h5" />
      <path d="m21 8-6-6" />
      <path d="M8 21v-5H3" />
      <path d="m3 16 6 6" />
      <path d="M16 21v-5h5" />
      <path d="m21 16-6 6" />
    </>
  ),
  eye: (
    <>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z" />
      <circle cx="12" cy="12" r="3" />
    </>
  ),
  bell: (
    <>
      <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
      <path d="M10 21a2 2 0 0 0 4 0" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 1v6m0 10v6M4.22 4.22l4.24 4.24m7.08 7.08 4.24 4.24M1 12h6m10 0h6M4.22 19.78l4.24-4.24m7.08-7.08 4.24-4.24" />
    </>
  ),
  paperclip: (
    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
  ),
  microphone: (
    <>
      <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z" />
      <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
      <line x1="12" y1="19" x2="12" y2="22" />
    </>
  ),
  "arrow-up": (
    <>
      <line x1="12" y1="19" x2="12" y2="5" />
      <polyline points="5 12 12 5 19 12" />
    </>
  ),
  "chevron-down": <polyline points="6 9 12 15 18 9" />,
  "chevron-left": <polyline points="15 18 9 12 15 6" />,
  "chevron-right": <polyline points="9 18 15 12 9 6" />,
  x: (
    <>
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </>
  ),
  copy: (
    <>
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </>
  ),
  "file-text": (
    <>
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <line x1="10" y1="9" x2="8" y2="9" />
    </>
  ),
  "currency-dollar": (
    <>
      <line x1="12" y1="2" x2="12" y2="22" />
      <path d="M17 5H9.5a3.5 3.5 0 1 0 0 7h5a3.5 3.5 0 1 1 0 7H6" />
    </>
  ),
  "chart-bar": (
    <>
      <line x1="18" y1="20" x2="18" y2="10" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="6" y1="20" x2="6" y2="14" />
    </>
  ),
  "dots-vertical": (
    <>
      <circle cx="12" cy="12" r="1" />
      <circle cx="12" cy="5" r="1" />
      <circle cx="12" cy="19" r="1" />
    </>
  ),
  "map-pin": (
    <>
      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z" />
      <circle cx="12" cy="10" r="3" />
    </>
  ),
  shield: <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />,
  robot: (
    <>
      <rect width="18" height="18" x="3" y="3" rx="2" />
      <path d="M12 8v4" />
      <path d="M12 16h.01" />
    </>
  ),
  folder: (
    <>
      <path d="M3 7v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2H5a2 2 0 0 1-2-2" />
      <path d="M8 3v4" />
      <path d="M16 3v4" />
    </>
  ),
  sparkles: (
    <>
      <path d="M12 2v6" />
      <path d="M5 8h14l-1 5a7 7 0 0 1-12 0z" />
      <path d="M12 18v4" />
    </>
  ),
  clock: (
    <>
      <path d="M12 2a10 10 0 1 0 10 10" />
      <path d="M12 6v6l4 2" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="16" x2="12" y2="12" />
      <line x1="12" y1="8" x2="12.01" y2="8" />
    </>
  ),
  "external-link": (
    <>
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </>
  ),
  terminal: (
    <>
      <rect x="2" y="3" width="20" height="18" rx="2" />
      <polyline points="6 8 10 12 6 16" />
      <line x1="12" y1="16" x2="18" y2="16" />
    </>
  ),
  cpu: (
    <>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <rect x="9" y="9" width="6" height="6" />
      <path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3" />
    </>
  ),
  camera: (
    <>
      <path d="M14.5 4 16 7h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h3l1.5-3z" />
      <circle cx="12" cy="13" r="4" />
    </>
  ),
  image: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <circle cx="8.5" cy="9" r="1.5" />
      <path d="m3 16 4.5-4.5 3.5 3.5 2.5-2.5L21 20" />
    </>
  ),
  moon: (
    <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79Z" />
  ),
  play: <polygon points="5 3 19 12 5 21 5 3" />,
  pause: (
    <>
      <rect x="6" y="4" width="4" height="16" rx="1" />
      <rect x="14" y="4" width="4" height="16" rx="1" />
    </>
  ),
  "skip-back": (
    <>
      <line x1="6" y1="5" x2="6" y2="19" />
      <polygon points="18 5 8 12 18 19 18 5" />
    </>
  ),
  "skip-forward": (
    <>
      <line x1="18" y1="5" x2="18" y2="19" />
      <polygon points="6 5 16 12 6 19 6 5" />
    </>
  ),
  volume: (
    <>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <path d="M15.5 8.5a5 5 0 0 1 0 7" />
      <path d="M18.5 5.5a9 9 0 0 1 0 13" />
    </>
  ),
  "volume-muted": (
    <>
      <polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" />
      <line x1="16" y1="9" x2="21" y2="14" />
      <line x1="21" y1="9" x2="16" y2="14" />
    </>
  ),
  power: (
    <>
      <path d="M18.36 6.64a9 9 0 1 1-12.73 0" />
      <line x1="12" y1="2" x2="12" y2="12" />
    </>
  ),
  trash: (
    <>
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6l-1 14H6L5 6m3 0V4h8v2" />
      <line x1="10" y1="10" x2="10" y2="16" />
      <line x1="14" y1="10" x2="14" y2="16" />
    </>
  ),
};

export function Icon({ name, size = 16, className }: IconProps) {
  const viewBox = name === "sidebar-panel-left" || name === "sidebar-panel-right" ? "0 0 18 18" : "0 0 24 24";
  const strokeWidth = name === "sidebar-panel-left" || name === "sidebar-panel-right" ? 1.5 : 2;

  return (
    <svg
      width={size}
      height={size}
      viewBox={viewBox}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      {ICON_PATHS[name]}
    </svg>
  );
}
