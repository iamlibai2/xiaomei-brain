export type VisualizationTheme = "light" | "dark";

const BRIDGE_SOURCE = "xiaomei-visualization";

const ALLOWED_EXTERNAL_ORIGINS = new Set([
  "https://cdnjs.cloudflare.com",
  "https://esm.sh",
  "https://cdn.jsdelivr.net",
  "https://unpkg.com",
  "https://fonts.googleapis.com",
  "https://fonts.gstatic.com",
  "https://fonts.bunny.net",
]);

const ALLOWED_CSP_SOURCES = Array.from(ALLOWED_EXTERNAL_ORIGINS).join(" ");

export { BRIDGE_SOURCE };

function isAllowedExternalResource(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && ALLOWED_EXTERNAL_ORIGINS.has(url.origin);
  } catch {
    return false;
  }
}

function isAllowedResourceReference(value: string): boolean {
  return /^(#|data:|blob:)/i.test(value) || isAllowedExternalResource(value);
}

function sanitizeFragment(source: string): string {
  const documentValue = new DOMParser().parseFromString(source, "text/html");
  documentValue.querySelectorAll("iframe,object,embed,base,meta").forEach((node) => node.remove());
  documentValue.querySelectorAll<HTMLLinkElement>("link").forEach((node) => {
    const rel = new Set(node.rel.toLowerCase().split(/\s+/).filter(Boolean));
    if (!rel.has("stylesheet") || !isAllowedExternalResource(node.href)) node.remove();
  });
  documentValue.querySelectorAll<HTMLScriptElement>("script[src]").forEach((node) => {
    if (!isAllowedExternalResource(node.src)) node.remove();
  });
  documentValue.querySelectorAll<HTMLElement>("*").forEach((element) => {
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim();
      if (["srcdoc", "srcset", "formaction", "action", "target"].includes(name)) {
        element.removeAttribute(attribute.name);
      } else if (
        (name === "src" || name === "href")
        && !isAllowedResourceReference(value)
      ) {
        element.removeAttribute(attribute.name);
      }
    }
  });
  // DOMParser may lift leading fragment resources into <head>. Reattach the
  // already-sanitized nodes so CDN scripts and styles are not lost.
  const headResources = Array.from(
    documentValue.head.querySelectorAll("style, link[rel~='stylesheet'], script"),
  )
    .map((node) => node.outerHTML)
    .join("\n");
  return `${headResources}\n${documentValue.body.innerHTML}`;
}

function bridgeScript(token: string): string {
  return `(() => {
    const source = ${JSON.stringify(BRIDGE_SOURCE)};
    const token = ${JSON.stringify(token)};
    const send = (type, payload = {}) => window.parent.postMessage({ source, token, type, ...payload }, '*');
    let mediaState = Object.freeze({ status: 'idle', title: '', positionMs: 0, durationMs: 0 });
    const mediaListeners = new Set();
    const mediaCommand = (action) => {
      if (navigator.userActivation && !navigator.userActivation.isActive) return false;
      send('media-command', { action });
      return true;
    };
    window.addEventListener('message', (event) => {
      const data = event.data || {};
      if (event.source !== window.parent || data.source !== source || data.token !== token || data.type !== 'media-state') return;
      mediaState = Object.freeze({ ...(data.state || {}) });
      mediaListeners.forEach((listener) => {
        try { listener(mediaState); } catch (error) { setTimeout(() => { throw error; }); }
      });
    });
    Object.defineProperty(window, 'xiaomei', {
      configurable: false,
      writable: false,
      value: Object.freeze({
        sendFollowUpMessage(value) {
          if (navigator.userActivation && !navigator.userActivation.isActive) return;
          const item = typeof value === 'string' ? { prompt: value } : (value || {});
          const prompt = String(item.prompt || '').trim().slice(0, 8000);
          const title = String(item.title || '').trim().slice(0, 250);
          if (prompt) send('follow-up', { prompt, title });
        },
        media: Object.freeze({
          getState() { return mediaState; },
          subscribe(listener) {
            if (typeof listener !== 'function') return () => {};
            mediaListeners.add(listener);
            listener(mediaState);
            return () => mediaListeners.delete(listener);
          },
          play() { return mediaCommand('play'); },
          pause() { return mediaCommand('pause'); },
          stop() { return mediaCommand('stop'); },
          seek(positionMs) {
            if (!Number.isFinite(Number(positionMs))) return false;
            send('media-command', { action: 'seek', positionMs: Number(positionMs) });
            return true;
          },
          setVolume(volume) {
            if (!Number.isFinite(Number(volume))) return false;
            send('media-command', { action: 'volume', volume: Number(volume) });
            return true;
          },
        }),
      }),
    });
    const reportHeight = () => {
      const height = Math.max(
        document.documentElement.scrollHeight,
        document.body?.scrollHeight || 0,
      );
      send('height', { height });
    };
    window.addEventListener('error', (event) => {
      send('runtime-error', { message: String(event.message || 'Visualization failed') });
    });
    window.addEventListener('unhandledrejection', (event) => {
      send('runtime-error', { message: String(event.reason?.message || event.reason || 'Visualization failed') });
    });
    document.addEventListener('submit', (event) => event.preventDefault(), true);
    document.addEventListener('click', (event) => {
      const anchor = event.target instanceof Element ? event.target.closest('a') : null;
      if (anchor && anchor.getAttribute('href') !== '#') event.preventDefault();
    }, true);
    window.addEventListener('DOMContentLoaded', () => {
      send('media-ready');
      reportHeight();
      if (window.ResizeObserver) new ResizeObserver(reportHeight).observe(document.documentElement);
      else window.setInterval(reportHeight, 500);
    }, { once: true });
  })();`;
}

const BASE_STYLE = `
  :root {
    color-scheme: light;
    --background: transparent;
    --foreground: #202124;
    --card: #ffffff;
    --card-foreground: #202124;
    --muted: #f2f3f5;
    --muted-foreground: #666b73;
    --border: #d9dce2;
    --primary: #2467d6;
    --primary-foreground: #ffffff;
    --accent: #e9f0fd;
    --accent-foreground: #184d9b;
    --destructive: #c83c3c;
    --viz-series-1: #2f6fed;
    --viz-series-2: #e07a2d;
    --viz-series-3: #2d9672;
    --viz-series-4: #8757c6;
    --viz-series-5: #c94f72;
    --viz-series-6: #8d7928;
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --foreground: #eceef2;
    --card: #24262b;
    --card-foreground: #eceef2;
    --muted: #2b2e34;
    --muted-foreground: #aeb3bd;
    --border: #41454e;
    --primary: #8eb6ff;
    --primary-foreground: #13213b;
    --accent: #283957;
    --accent-foreground: #dce8ff;
    --destructive: #ff8b8b;
    --viz-series-1: #8eb6ff;
    --viz-series-2: #ffad72;
    --viz-series-3: #68c7a2;
    --viz-series-4: #bd99ef;
    --viz-series-5: #ee8fad;
    --viz-series-6: #d8c56e;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; min-width: 0; background: transparent; color: var(--foreground); }
  body { padding: 12px 14px 16px; font: 400 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
  h1, h2, h3, p { margin-top: 0; }
  h1, h2, h3 { color: var(--foreground); font-weight: 500; }
  h1 { font-size: 20px; } h2 { font-size: 17px; } h3 { font-size: 15px; }
  button, input, select, textarea { font: inherit; color: inherit; }
  button {
    border: 1px solid var(--border); border-radius: 7px; padding: 6px 10px;
    background: var(--card); cursor: pointer;
  }
  button:hover { background: var(--accent); color: var(--accent-foreground); }
  button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible {
    outline: 2px solid var(--primary); outline-offset: 2px;
  }
  input, select, textarea {
    border: 1px solid var(--border); border-radius: 7px; padding: 6px 8px; background: var(--card);
  }
  input[type="range"] { padding: 0; accent-color: var(--primary); }
  .viz-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
  .viz-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
  .viz-controls { display: flex; flex-wrap: wrap; align-items: end; gap: 10px; margin: 10px 0; }
  .card { padding: 12px; border: 1px solid var(--border); border-radius: 9px; background: var(--card); color: var(--card-foreground); }
  .text-muted { color: var(--muted-foreground); }
  .text-small { font-size: 12px; }
  svg, canvas { display: block; max-width: 100%; }
  table { width: 100%; border-collapse: collapse; }
  th, td { padding: 7px 8px; border-bottom: 1px solid var(--border); text-align: left; }
  @media (max-width: 480px) {
    body { padding-inline: 8px; }
    .viz-controls { align-items: stretch; flex-direction: column; }
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
  }
`;

export function buildVisualizationDocument(
  source: string,
  token: string,
  theme: VisualizationTheme,
): string {
  const fragment = sanitizeFragment(source);
  const csp = [
    "default-src 'none'",
    `script-src 'unsafe-inline' ${ALLOWED_CSP_SOURCES}`,
    `style-src 'unsafe-inline' ${ALLOWED_CSP_SOURCES}`,
    `img-src data: blob: ${ALLOWED_CSP_SOURCES}`,
    `media-src data: blob: ${ALLOWED_CSP_SOURCES}`,
    `font-src data: ${ALLOWED_CSP_SOURCES}`,
    "connect-src 'none'",
    "worker-src 'none'",
    "frame-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
  return `<!doctype html>
<html lang="zh-CN" data-theme="${theme}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="no-referrer">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <style>${BASE_STYLE}</style>
  <script>${bridgeScript(token)}</script>
</head>
<body>
  <main id="xiaomei-visualization-root">${fragment}</main>
</body>
</html>`;
}
