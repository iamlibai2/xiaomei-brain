import { createHash } from "node:crypto";
import {
  BrowserWindow,
  ipcMain,
  session,
  WebContentsView,
  type Rectangle,
} from "electron";

export interface DesktopBrowserState {
  open: boolean;
  visible: boolean;
  loading: boolean;
  url: string;
  title: string;
  canGoBack: boolean;
  canGoForward: boolean;
  error?: string;
}

type BrowserCommand = {
  action: string;
  agentId?: string;
  url?: string;
  ref?: string;
  text?: string;
  value?: string;
  clear?: boolean;
  direction?: string;
  amount?: number;
  interactiveOnly?: boolean;
  maxElements?: number;
  key?: string;
};

type AxNode = {
  nodeId: string;
  backendDOMNodeId?: number;
  ignored?: boolean;
  role?: { value?: string };
  name?: { value?: string };
  value?: { value?: unknown };
  description?: { value?: string };
};

const ACTIONABLE_ROLES = new Set([
  "button", "checkbox", "combobox", "link", "listbox", "menuitem",
  "radio", "searchbox", "slider", "spinbutton", "switch", "tab",
  "textbox", "option",
]);

const READABLE_ROLES = new Set([
  ...ACTIONABLE_ROLES,
  "heading", "img", "paragraph", "StaticText", "table", "cell",
  "rowheader", "columnheader", "listitem", "article",
]);

export class DesktopBrowserManager {
  private view: WebContentsView | null = null;
  private partition = "";
  private bounds: Rectangle = { x: 0, y: 0, width: 0, height: 0 };
  private visible = false;
  private refs = new Map<string, number>();
  private lastError = "";

  constructor(
    private readonly getWindow: () => BrowserWindow | null,
    private readonly getIdentitySubject: () => string,
  ) {}

  registerIpc(): void {
    ipcMain.handle("desktop-browser:command", (_event, command: BrowserCommand) => this.command(command));
    ipcMain.handle("desktop-browser:setBounds", (_event, bounds: Rectangle) => {
      this.setBounds(bounds);
      return this.state();
    });
    ipcMain.handle("desktop-browser:setVisible", (_event, args: { visible: boolean }) => {
      this.setVisible(Boolean(args?.visible));
      return this.state();
    });
    ipcMain.handle("desktop-browser:getState", () => this.state());
  }

  async command(command: BrowserCommand): Promise<Record<string, unknown>> {
    try {
      const action = String(command?.action || "get_state");
      if (action === "open" || action === "navigate") {
        const url = normalizeUrl(command.url || "https://www.baidu.com/");
        await this.ensureView(command.agentId || "default");
        this.lastError = "";
        this.setVisible(true);
        await this.view!.webContents.loadURL(url);
        return { status: "completed", result: this.state() };
      }
      if (action === "close") {
        this.setVisible(false);
        return { status: "completed", result: this.state() };
      }

      await this.ensureView(command.agentId || "default");
      const contents = this.view!.webContents;
      if (action === "get_state") return { status: "completed", result: this.state() };
      if (action === "back") {
        if (contents.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
      } else if (action === "forward") {
        if (contents.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
      } else if (action === "reload") {
        contents.reload();
      } else if (action === "snapshot") {
        return { status: "completed", result: await this.snapshot(command) };
      } else if (action === "click") {
        await this.callOnRef(command.ref, "function(){ this.scrollIntoView({block:'center'}); this.click(); }");
      } else if (action === "type") {
        await this.typeIntoRef(command.ref, String(command.text ?? ""), command.clear !== false);
      } else if (action === "select") {
        await this.selectRef(command.ref, String(command.value ?? ""));
      } else if (action === "press") {
        const key = normalizeKey(command.key || "Enter");
        await this.cdp("Input.dispatchKeyEvent", { type: "keyDown", key, code: key });
        await this.cdp("Input.dispatchKeyEvent", { type: "keyUp", key, code: key });
      } else if (action === "scroll") {
        const amount = Math.max(100, Math.min(4000, Number(command.amount) || 700));
        const sign = String(command.direction || "down") === "up" ? -1 : 1;
        await this.cdp("Runtime.evaluate", { expression: `window.scrollBy({top:${sign * amount},behavior:'smooth'})` });
      } else {
        throw new Error(`不支持的浏览器动作：${action}`);
      }
      return { status: "completed", result: this.state() };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.lastError = message;
      this.emitState();
      return { status: "failed", error: message };
    }
  }

  private async ensureView(agentId: string): Promise<void> {
    const subject = this.getIdentitySubject() || "anonymous";
    const key = createHash("sha256").update(`${agentId}:${subject}`).digest("hex").slice(0, 24);
    const partition = `persist:xiaomei-browser-${key}`;
    if (this.view && this.partition === partition && !this.view.webContents.isDestroyed()) return;
    this.destroyView();

    const browserSession = session.fromPartition(partition);
    browserSession.setUserAgent(
      browserCompatibleUserAgent(browserSession.getUserAgent()),
      "zh-CN,zh;q=0.9,en;q=0.8",
    );
    browserSession.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
    this.view = new WebContentsView({
      webPreferences: {
        session: browserSession,
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
      },
    });
    this.partition = partition;
    const contents = this.view.webContents;
    contents.setWindowOpenHandler(({ url }) => {
      try { void contents.loadURL(normalizeUrl(url)); } catch { /* rejected URL */ }
      return { action: "deny" };
    });
    contents.on("will-navigate", (event, url) => {
      try { normalizeUrl(url); } catch { event.preventDefault(); }
    });
    contents.on("did-start-loading", () => { this.refs.clear(); this.emitState(); });
    contents.on("did-stop-loading", () => this.emitState());
    contents.on("did-finish-load", () => { this.lastError = ""; this.emitState(); });
    contents.on("page-title-updated", () => this.emitState());
    contents.on("did-navigate", () => { this.refs.clear(); this.emitState(); });
    contents.on("did-navigate-in-page", () => { this.refs.clear(); this.emitState(); });
    contents.on("did-fail-load", (_event, code, description, url, isMainFrame) => {
      if (isMainFrame && code !== -3) this.lastError = `${description} (${url})`;
      this.emitState();
    });
    contents.debugger.attach("1.3");
    const win = this.getWindow();
    if (!win) throw new Error("Desktop 窗口不可用");
    win.contentView.addChildView(this.view);
    this.applyBounds();
  }

  private destroyView(): void {
    if (!this.view) return;
    const win = this.getWindow();
    try { win?.contentView.removeChildView(this.view); } catch { /* already detached */ }
    try { this.view.webContents.close(); } catch { /* already destroyed */ }
    this.view = null;
    this.partition = "";
    this.refs.clear();
  }

  private setBounds(bounds: Rectangle): void {
    this.bounds = {
      x: Math.max(0, Math.round(Number(bounds?.x) || 0)),
      y: Math.max(0, Math.round(Number(bounds?.y) || 0)),
      width: Math.max(0, Math.round(Number(bounds?.width) || 0)),
      height: Math.max(0, Math.round(Number(bounds?.height) || 0)),
    };
    this.applyBounds();
  }

  private setVisible(visible: boolean): void {
    this.visible = visible;
    this.applyBounds();
    this.emitState();
  }

  private applyBounds(): void {
    if (!this.view) return;
    this.view.setVisible(this.visible && this.bounds.width > 0 && this.bounds.height > 0);
    if (this.bounds.width > 0 && this.bounds.height > 0) this.view.setBounds(this.bounds);
  }

  private state(): DesktopBrowserState {
    const contents = this.view?.webContents;
    const usable = contents && !contents.isDestroyed();
    return {
      open: Boolean(usable && this.visible),
      visible: Boolean(usable && this.visible),
      loading: Boolean(usable && contents!.isLoading()),
      url: usable ? contents!.getURL() : "",
      title: usable ? contents!.getTitle() : "",
      canGoBack: Boolean(usable && contents!.navigationHistory.canGoBack()),
      canGoForward: Boolean(usable && contents!.navigationHistory.canGoForward()),
      ...(this.lastError ? { error: this.lastError } : {}),
    };
  }

  private emitState(): void {
    const win = this.getWindow();
    if (win && !win.isDestroyed()) win.webContents.send("desktop-browser:state", this.state());
  }

  private async cdp(method: string, params: Record<string, unknown> = {}): Promise<any> {
    if (!this.view || this.view.webContents.isDestroyed()) throw new Error("浏览器尚未打开");
    return this.view.webContents.debugger.sendCommand(method, params);
  }

  private async snapshot(command: BrowserCommand): Promise<Record<string, unknown>> {
    const response = await this.cdp("Accessibility.getFullAXTree");
    const nodes = (response.nodes || []) as AxNode[];
    const interactiveOnly = Boolean(command.interactiveOnly);
    const limit = Math.max(20, Math.min(500, Number(command.maxElements) || 200));
    this.refs.clear();
    const elements: Record<string, unknown>[] = [];
    for (const node of nodes) {
      if (node.ignored || !node.backendDOMNodeId) continue;
      const role = String(node.role?.value || "");
      if (interactiveOnly ? !ACTIONABLE_ROLES.has(role) : !READABLE_ROLES.has(role)) continue;
      const name = String(node.name?.value || "").trim();
      const value = node.value?.value;
      if (!name && value == null && !ACTIONABLE_ROLES.has(role)) continue;
      const ref = `e${elements.length + 1}`;
      this.refs.set(ref, node.backendDOMNodeId);
      elements.push({
        ref,
        role,
        name,
        ...(value == null ? {} : { value: String(value) }),
        ...(node.description?.value ? { description: node.description.value } : {}),
      });
      if (elements.length >= limit) break;
    }
    return { page: this.state(), elements, count: elements.length, truncated: elements.length >= limit };
  }

  private backendNodeId(ref?: string): number {
    const id = this.refs.get(String(ref || ""));
    if (!id) throw new Error(`无效或已过期的页面元素引用：${ref || "(空)"}，请重新读取页面`);
    return id;
  }

  private async callOnRef(ref: string | undefined, functionDeclaration: string, args: unknown[] = []): Promise<any> {
    const resolved = await this.cdp("DOM.resolveNode", { backendNodeId: this.backendNodeId(ref) });
    const objectId = resolved.object?.objectId;
    if (!objectId) throw new Error(`无法定位页面元素：${ref}`);
    return this.cdp("Runtime.callFunctionOn", {
      objectId,
      functionDeclaration,
      arguments: args.map((value) => ({ value })),
      awaitPromise: true,
      returnByValue: true,
    });
  }

  private async typeIntoRef(ref: string | undefined, text: string, clear: boolean): Promise<void> {
    await this.callOnRef(ref, `function(clear){
      this.scrollIntoView({block:'center'}); this.focus();
      if (clear) {
        if ('value' in this) { this.value = ''; }
        else if (this.isContentEditable) { this.textContent = ''; }
        this.dispatchEvent(new Event('input', {bubbles:true}));
      }
    }`, [clear]);
    await this.cdp("Input.insertText", { text });
    await this.callOnRef(ref, "function(){ this.dispatchEvent(new Event('input',{bubbles:true})); this.dispatchEvent(new Event('change',{bubbles:true})); }");
  }

  private async selectRef(ref: string | undefined, value: string): Promise<void> {
    await this.callOnRef(ref, `function(value){
      this.value = value;
      this.dispatchEvent(new Event('input',{bubbles:true}));
      this.dispatchEvent(new Event('change',{bubbles:true}));
    }`, [value]);
  }
}

function normalizeUrl(input: string): string {
  const candidate = input.trim();
  const withScheme = /^[a-z][a-z0-9+.-]*:/i.test(candidate) ? candidate : `https://${candidate}`;
  const parsed = new URL(withScheme);
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw new Error("具身浏览器只允许打开 HTTP 或 HTTPS 网页");
  }
  return parsed.toString();
}

function normalizeKey(input: string): string {
  if (!["Enter", "Tab", "Escape"].includes(input)) throw new Error(`不支持的按键：${input}`);
  return input;
}

export function browserCompatibleUserAgent(defaultUserAgent: string): string {
  const sanitized = String(defaultUserAgent || "")
    .replace(/\s+Electron\/[\d.]+/gi, "")
    .replace(/\s+xiaomei-brain-desktop\/[\d.]+/gi, "")
    .replace(/\s+XiaoMei-Brain\/[\d.]+/gi, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  return sanitized || defaultUserAgent;
}
