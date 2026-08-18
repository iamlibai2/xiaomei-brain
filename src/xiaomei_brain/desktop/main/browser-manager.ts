import { createHash, randomUUID } from "node:crypto";
import { mkdirSync } from "node:fs";
import { promises as fs } from "node:fs";
import path from "node:path";
import {
  app,
  BrowserWindow,
  ipcMain,
  session,
  WebContentsView,
  type DownloadItem,
  type Rectangle,
  type WebFrameMain,
} from "electron";

// Base64 is transported in one existing embodiment command frame. Keep the
// encoded JSON comfortably below the Gateway's WebSocket frame limit.
const MAX_TRANSFER_BYTES = 10 * 1024 * 1024;
// A third-party frame can keep executeJavaScript pending indefinitely (for
// example while its challenge document is navigating). A page snapshot is
// best-effort and must always answer the Agent before the embodiment command
// timeout, so iframe enrichment gets a small bounded budget.
const FRAME_SNAPSHOT_TIMEOUT_MS = 600;
const FRAME_SNAPSHOT_BUDGET_MS = 2_000;

export interface DesktopBrowserState {
  open: boolean;
  visible: boolean;
  loading: boolean;
  url: string;
  title: string;
  canGoBack: boolean;
  canGoForward: boolean;
  transfer?: {
    direction: "download" | "upload";
    status: "starting" | "transferring" | "completed" | "failed";
    name: string;
    receivedBytes: number;
    totalBytes: number;
    percent: number;
  };
  error?: string;
}

type BrowserCommand = {
  action: string;
  agentId?: string;
  commandId?: string;
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
  name?: string;
  mimeType?: string;
  dataBase64?: string;
  condition?: string;
  timeoutMs?: number;
};

type PageObservation = {
  url: string;
  title: string;
  loading: boolean;
  revision: number;
};

type DownloadResult = {
  name: string;
  mime_type: string;
  size: number;
  data_base64: string;
};

type PendingDownload = {
  partition: string;
  resolve: (result: DownloadResult) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
  item?: DownloadItem;
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

type BrowserElementRef =
  | { kind: "cdp"; backendDOMNodeId: number }
  | { kind: "frame"; frame: WebFrameMain; domRef: string };

type FrameSnapshotElement = {
  domRef: string;
  role: string;
  name: string;
  value?: string;
  description?: string;
};

type FileInputElement = {
  backendDOMNodeId: number;
  name: string;
  accept: string;
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
  private refs = new Map<string, BrowserElementRef>();
  private lastError = "";
  private transfer: DesktopBrowserState["transfer"];
  private pendingDownload: PendingDownload | null = null;
  private configuredDownloadPartitions = new Set<string>();
  private uploadTempPaths = new Set<string>();
  private pendingFileChooserBackendNodeId: number | null = null;
  private cancelledCommands = new Set<string>();

  constructor(
    private readonly getWindow: () => BrowserWindow | null,
    private readonly getIdentitySubject: () => string,
  ) {}

  registerIpc(): void {
    ipcMain.handle("desktop-browser:command", (_event, command: BrowserCommand) => this.command(command));
    ipcMain.handle("desktop-browser:cancel", (_event, args: { commandId?: string }) => ({
      cancelled: this.cancel(String(args?.commandId || "")),
    }));
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
    const commandId = String(command?.commandId || "");
    if (commandId) this.cancelledCommands.delete(commandId);
    try {
      this.throwIfCancelled(commandId);
      const action = String(command?.action || "get_state");
      if (action === "open" || action === "navigate") {
        const url = normalizeUrl(command.url || "https://www.baidu.com/");
        await this.ensureView(command.agentId || "default");
        this.lastError = "";
        this.setVisible(true);
        await this.view!.webContents.loadURL(url);
        this.throwIfCancelled(commandId);
        return { status: "completed", result: this.state() };
      }
      if (action === "close") {
        this.setVisible(false);
        return { status: "completed", result: this.state() };
      }

      await this.ensureView(command.agentId || "default");
      const contents = this.view!.webContents;
      if (action === "get_state") return { status: "completed", result: this.state() };
      this.lastError = "";
      if (action === "wait_for") {
        return { status: "completed", result: await this.waitFor(command) };
      }
      const before = await this.pageObservation();
      if (action === "back") {
        if (contents.navigationHistory.canGoBack()) contents.navigationHistory.goBack();
      } else if (action === "forward") {
        if (contents.navigationHistory.canGoForward()) contents.navigationHistory.goForward();
      } else if (action === "reload") {
        contents.reload();
      } else if (action === "snapshot") {
        return { status: "completed", result: await this.snapshot(command) };
      } else if (action === "click") {
        const chooserBackendNodeId = await this.clickRef(command.ref);
        const result = await this.validateAction(action, before);
        return {
          status: "completed",
          result: {
            ...result,
            ...(chooserBackendNodeId ? { file_chooser_opened: true } : {}),
          },
        };
      } else if (action === "type") {
        return {
          status: "completed",
          result: await this.typeIntoRef(command.ref, String(command.text ?? ""), command.clear !== false),
        };
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
      } else if (action === "download") {
        return { status: "completed", result: await this.downloadRef(command.ref) };
      } else if (action === "upload") {
        return { status: "completed", result: await this.uploadRef(command) };
      } else {
        throw new Error(`不支持的浏览器动作：${action}`);
      }
      return { status: "completed", result: await this.validateAction(action, before) };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.lastError = message;
      this.emitState();
      if (this.isStaleRefError(message)) {
        const recoverySnapshot = await this.snapshot({
          action: "snapshot",
          interactiveOnly: true,
          maxElements: 100,
        }).catch(() => undefined);
        return {
          status: "failed",
          error: message,
          ...(recoverySnapshot ? { result: { recovery_snapshot: recoverySnapshot } } : {}),
        };
      }
      return { status: "failed", error: message };
    } finally {
      if (commandId) this.cancelledCommands.delete(commandId);
    }
  }

  private cancel(commandId: string): boolean {
    if (!commandId) return false;
    this.cancelledCommands.add(commandId);
    const contents = this.view?.webContents;
    if (contents && !contents.isDestroyed() && contents.isLoading()) contents.stop();
    if (this.pendingDownload) {
      this.pendingDownload.item?.cancel();
      this.rejectPendingDownload(new Error("Browser command cancelled"));
    }
    return true;
  }

  private throwIfCancelled(commandId?: string): void {
    if (commandId && this.cancelledCommands.has(commandId)) {
      throw new Error("Browser command cancelled");
    }
  }

  private async pageObservation(): Promise<PageObservation> {
    const contents = this.view!.webContents;
    const response = await this.cdp("Runtime.evaluate", {
      expression: `(() => {
        const key = Symbol.for('xiaomei.browser.mutation-state');
        let state = globalThis[key];
        if (!state || !state.observer) {
          state = { revision: 0, observer: null };
          const root = document.documentElement;
          if (root) {
            state.observer = new MutationObserver(() => { state.revision += 1; });
            state.observer.observe(root, { subtree: true, childList: true, attributes: true, characterData: true });
          }
          globalThis[key] = state;
        }
        return { revision: Number(state.revision || 0) };
      })()`,
      returnByValue: true,
    }).catch(() => ({ result: { value: { revision: 0 } } }));
    return {
      url: contents.getURL(),
      title: contents.getTitle(),
      loading: contents.isLoading(),
      revision: Number(response?.result?.value?.revision) || 0,
    };
  }

  private async validateAction(action: string, before: PageObservation): Promise<Record<string, unknown>> {
    const started = Date.now();
    let after = before;
    while (Date.now() - started < 900) {
      await delay(90);
      after = await this.pageObservation();
      if (after.url !== before.url || after.title !== before.title
        || after.loading !== before.loading || after.revision !== before.revision) break;
    }
    const changes = {
      url: after.url !== before.url,
      title: after.title !== before.title,
      loading: after.loading !== before.loading,
      dom: after.revision !== before.revision,
    };
    return {
      action,
      changed: Object.values(changes).some(Boolean),
      changes,
      elapsed_ms: Date.now() - started,
      page: this.state(),
      snapshot: await this.snapshot({ action: "snapshot", interactiveOnly: true, maxElements: 100 }),
    };
  }

  private async waitFor(command: BrowserCommand): Promise<Record<string, unknown>> {
    const condition = String(command.condition || "load").toLowerCase();
    if (!["load", "url", "text", "element", "hidden"].includes(condition)) {
      throw new Error(`Unsupported browser wait condition: ${condition}`);
    }
    if (condition === "url" && !command.url) throw new Error("wait_for url requires url");
    if (condition === "text" && !command.text) throw new Error("wait_for text requires text");
    if ((condition === "element" || condition === "hidden") && !command.ref) {
      throw new Error(`wait_for ${condition} requires ref`);
    }
    const timeoutMs = Math.max(100, Math.min(30_000, Number(command.timeoutMs) || 5_000));
    const started = Date.now();
    let matched = false;
    while (Date.now() - started < timeoutMs) {
      this.throwIfCancelled(command.commandId);
      matched = await this.matchesWaitCondition(condition, command);
      if (matched) break;
      await delay(150);
    }
    return {
      matched,
      timed_out: !matched,
      condition,
      elapsed_ms: Date.now() - started,
      page: this.state(),
      snapshot: await this.snapshot({ action: "snapshot", interactiveOnly: true, maxElements: 100 }),
    };
  }

  private async matchesWaitCondition(condition: string, command: BrowserCommand): Promise<boolean> {
    if (condition === "load") return !this.view!.webContents.isLoading();
    if (condition === "url") return this.view!.webContents.getURL().includes(String(command.url));
    if (condition === "text") {
      const needle = String(command.text);
      const expression = `(document.body?.innerText || document.documentElement?.innerText || '').includes(${JSON.stringify(needle)})`;
      const main = await this.view!.webContents.executeJavaScript(expression, true).catch(() => false);
      if (main) return true;
      for (const frame of this.view!.webContents.mainFrame.framesInSubtree.slice(1)) {
        if (frame.detached || frame.isDestroyed()) continue;
        const found = await withTimeout(
          frame.executeJavaScript(expression, true),
          FRAME_SNAPSHOT_TIMEOUT_MS,
          false,
        ).catch(() => false);
        if (found) return true;
      }
      return false;
    }
    try {
      const visible = Boolean(await this.callOnRef(command.ref, `function(){
        if (!this.isConnected) return false;
        const style = getComputedStyle(this);
        const rect = this.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden'
          && Number(style.opacity || 1) !== 0 && rect.width > 0 && rect.height > 0;
      }`));
      return condition === "element" ? visible : !visible;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      return condition === "hidden" && this.isStaleRefError(message);
    }
  }

  private isStaleRefError(message: string): boolean {
    return /引用.*(?:失效|过期)|(?:失效|过期).*引用|stale|detached/i.test(message);
  }

  private async ensureView(agentId: string): Promise<void> {
    const subject = this.getIdentitySubject() || "anonymous";
    const key = createHash("sha256").update(`${agentId}:${subject}`).digest("hex").slice(0, 24);
    const partition = `persist:xiaomei-browser-${key}`;
    if (this.view && this.partition === partition && !this.view.webContents.isDestroyed()) return;
    this.destroyView();

    const browserSession = session.fromPartition(partition);
    if (!this.configuredDownloadPartitions.has(partition)) {
      this.configuredDownloadPartitions.add(partition);
      browserSession.on("will-download", (_event, item) => {
        if (this.partition === partition) {
          void this.captureDownload(item).catch((error) => {
            this.rejectPendingDownload(error instanceof Error ? error : new Error(String(error)));
          });
        }
      });
    }
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
    contents.on("did-navigate", () => {
      this.refs.clear();
      this.pendingFileChooserBackendNodeId = null;
      this.emitState();
    });
    contents.on("did-navigate-in-page", () => {
      this.refs.clear();
      this.pendingFileChooserBackendNodeId = null;
      this.emitState();
    });
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
    if (this.pendingDownload) {
      this.pendingDownload.item?.cancel();
      this.rejectPendingDownload(new Error("网页已关闭，下载已取消"));
    }
    for (const tempPath of this.uploadTempPaths) {
      void fs.rm(tempPath, { force: true }).catch(() => undefined);
    }
    this.uploadTempPaths.clear();
    if (!this.view) return;
    const win = this.getWindow();
    try { win?.contentView.removeChildView(this.view); } catch { /* already detached */ }
    try { this.view.webContents.close(); } catch { /* already destroyed */ }
    this.view = null;
    this.partition = "";
    this.refs.clear();
    this.transfer = undefined;
    this.pendingFileChooserBackendNodeId = null;
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
      ...(this.transfer ? { transfer: { ...this.transfer } } : {}),
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
      this.refs.set(ref, { kind: "cdp", backendDOMNodeId: node.backendDOMNodeId });
      elements.push({
        ref,
        role,
        name,
        ...(value == null ? {} : { value: String(value) }),
        ...(node.description?.value ? { description: node.description.value } : {}),
      });
      if (elements.length >= limit) break;
    }
    if (elements.length < limit) {
      const childFrames = this.view?.webContents.mainFrame.framesInSubtree.slice(1) || [];
      const frameDeadline = Date.now() + FRAME_SNAPSHOT_BUDGET_MS;
      for (const frame of childFrames) {
        const remaining = frameDeadline - Date.now();
        if (remaining <= 0) break;
        if (frame.detached || frame.isDestroyed()) continue;
        try {
          const frameElements = await withTimeout(
            this.snapshotFrame(frame, interactiveOnly, limit - elements.length),
            Math.min(FRAME_SNAPSHOT_TIMEOUT_MS, remaining),
            [],
          );
          for (const element of frameElements) {
            const ref = `e${elements.length + 1}`;
            this.refs.set(ref, { kind: "frame", frame, domRef: element.domRef });
            elements.push({
              ref,
              role: element.role,
              name: element.name,
              ...(element.value == null ? {} : { value: element.value }),
              ...(element.description ? { description: element.description } : {}),
              frame_url: frame.url,
            });
            if (elements.length >= limit) break;
          }
        } catch {
          // Frames may navigate or detach while a snapshot is being built.
          // Keep the rest of the page usable when that happens.
        }
        if (elements.length >= limit) break;
      }
    }
    if (elements.length < limit) {
      const existingBackendIds = new Set(
        [...this.refs.values()]
          .filter((target): target is Extract<BrowserElementRef, { kind: "cdp" }> => target.kind === "cdp")
          .map((target) => target.backendDOMNodeId),
      );
      for (const input of await this.discoverFileInputs()) {
        if (existingBackendIds.has(input.backendDOMNodeId)) continue;
        const ref = `e${elements.length + 1}`;
        this.refs.set(ref, { kind: "cdp", backendDOMNodeId: input.backendDOMNodeId });
        elements.push({
          ref,
          role: "file",
          name: input.name || "文件上传控件",
          ...(input.accept ? { description: `接受文件：${input.accept}` } : {}),
        });
        if (elements.length >= limit) break;
      }
    }
    return { page: this.state(), elements, count: elements.length, truncated: elements.length >= limit };
  }

  private async discoverFileInputs(): Promise<FileInputElement[]> {
    let searchId = "";
    try {
      const search = await this.cdp("DOM.performSearch", {
        query: 'input[type="file"]',
        includeUserAgentShadowDOM: true,
      });
      searchId = String(search.searchId || "");
      const count = Math.max(0, Math.min(20, Number(search.resultCount) || 0));
      if (!searchId || count <= 0) return [];
      const matches = await this.cdp("DOM.getSearchResults", {
        searchId,
        fromIndex: 0,
        toIndex: count,
      });
      const result: FileInputElement[] = [];
      for (const nodeId of (matches.nodeIds || []) as number[]) {
        try {
          const described = await this.cdp("DOM.describeNode", { nodeId, depth: 0, pierce: true });
          const node = described.node || {};
          const backendDOMNodeId = Number(node.backendNodeId) || 0;
          if (!backendDOMNodeId) continue;
          const rawAttributes = Array.isArray(node.attributes) ? node.attributes as string[] : [];
          const attributes = new Map<string, string>();
          for (let index = 0; index + 1 < rawAttributes.length; index += 2) {
            attributes.set(String(rawAttributes[index]).toLowerCase(), String(rawAttributes[index + 1]));
          }
          if (attributes.has("disabled")) continue;
          result.push({
            backendDOMNodeId,
            name: attributes.get("aria-label") || attributes.get("title")
              || attributes.get("name") || "文件上传控件",
            accept: attributes.get("accept") || "",
          });
        } catch {
          // A framework may replace the hidden input while search results are
          // being resolved. Ignore that stale candidate and keep the others.
        }
      }
      return result;
    } catch {
      return [];
    } finally {
      if (searchId) {
        await this.cdp("DOM.discardSearchResults", { searchId }).catch(() => undefined);
      }
    }
  }

  private backendNodeId(ref?: string): number {
    const target = this.elementRef(ref);
    if (target.kind !== "cdp") throw new Error("iframe 内的文件上传控件暂不支持直接传入文件");
    return target.backendDOMNodeId;
  }

  private async callOnRef(ref: string | undefined, functionDeclaration: string, args: unknown[] = []): Promise<any> {
    const target = this.elementRef(ref);
    if (target.kind === "frame") {
      if (target.frame.detached || target.frame.isDestroyed()) {
        throw new Error(`页面元素引用已经失效：${ref}，请重新读取页面`);
      }
      const code = `(() => {
        const domRef = ${JSON.stringify(target.domRef)};
        const element = globalThis[Symbol.for('xiaomei.browser.refs')]?.get(domRef);
        if (!element) throw new Error('页面元素引用已经失效');
        return (${functionDeclaration}).apply(element, ${JSON.stringify(args)});
      })()`;
      return target.frame.executeJavaScript(code, true);
    }
    const resolved = await this.cdp("DOM.resolveNode", { backendNodeId: target.backendDOMNodeId });
    const objectId = resolved.object?.objectId;
    if (!objectId) throw new Error(`无法定位页面元素：${ref}`);
    const response = await this.cdp("Runtime.callFunctionOn", {
      objectId,
      functionDeclaration,
      arguments: args.map((value) => ({ value })),
      awaitPromise: true,
      returnByValue: true,
    });
    return response?.result?.value;
  }

  private elementRef(ref?: string): BrowserElementRef {
    const target = this.refs.get(String(ref || ""));
    if (!target) throw new Error(`无效或已过期的页面元素引用：${ref || "(空)"}，请重新读取页面`);
    return target;
  }

  private async clickRef(ref?: string): Promise<number | undefined> {
    const chooserBackendNodeId = await this.captureFileChooser(
      () => this.nativeClickRef(ref),
      350,
    );
    if (chooserBackendNodeId) this.pendingFileChooserBackendNodeId = chooserBackendNodeId;
    return chooserBackendNodeId;
  }

  private async nativeClickRef(ref?: string): Promise<void> {
    const target = this.elementRef(ref);
    await this.callOnRef(ref, "function(){ this.scrollIntoView({block:'center',inline:'center'}); }");
    if (target.kind === "frame") {
      // CDP mouse coordinates are relative to the top-level viewport. Until a
      // frame-aware coordinate mapper is needed, emit the complete pointer and
      // mouse sequence in the owning frame instead of falling back to click().
      await this.callOnRef(ref, `function(){
        const options = {bubbles:true,cancelable:true,composed:true,view:this.ownerDocument.defaultView,
          button:0,buttons:1,pointerId:1,pointerType:'mouse',isPrimary:true};
        this.dispatchEvent(new PointerEvent('pointerover', options));
        this.dispatchEvent(new MouseEvent('mouseover', options));
        this.dispatchEvent(new PointerEvent('pointerdown', options));
        this.dispatchEvent(new MouseEvent('mousedown', options));
        this.focus?.({preventScroll:true});
        this.dispatchEvent(new PointerEvent('pointerup', {...options,buttons:0}));
        this.dispatchEvent(new MouseEvent('mouseup', {...options,buttons:0}));
        this.dispatchEvent(new MouseEvent('click', {...options,buttons:0}));
      }`);
      return;
    }
    const response = await this.cdp("DOM.getBoxModel", { backendNodeId: target.backendDOMNodeId });
    const quad = response?.model?.border || response?.model?.content;
    if (!Array.isArray(quad) || quad.length < 8) {
      throw new Error(`无法取得页面元素的可点击区域：${ref || "(空)"}`);
    }
    const xs = [Number(quad[0]), Number(quad[2]), Number(quad[4]), Number(quad[6])];
    const ys = [Number(quad[1]), Number(quad[3]), Number(quad[5]), Number(quad[7])];
    const x = xs.reduce((sum, value) => sum + value, 0) / xs.length;
    const y = ys.reduce((sum, value) => sum + value, 0) / ys.length;
    if (!Number.isFinite(x) || !Number.isFinite(y)) {
      throw new Error(`页面元素的可点击坐标无效：${ref || "(空)"}`);
    }
    await this.cdp("Input.dispatchMouseEvent", { type: "mouseMoved", x, y });
    await this.cdp("Input.dispatchMouseEvent", {
      type: "mousePressed", x, y, button: "left", buttons: 1, clickCount: 1,
    });
    await this.cdp("Input.dispatchMouseEvent", {
      type: "mouseReleased", x, y, button: "left", buttons: 0, clickCount: 1,
    });
  }

  private async captureFileChooser(
    trigger: () => Promise<void>,
    timeoutMs: number,
  ): Promise<number | undefined> {
    const contents = this.view?.webContents;
    if (!contents || contents.isDestroyed()) throw new Error("浏览器尚未打开");
    let resolveChooser: (value: number | undefined) => void = () => undefined;
    const chooser = new Promise<number | undefined>((resolve) => { resolveChooser = resolve; });
    const handler = (_event: unknown, method: string, params: Record<string, unknown>) => {
      if (method !== "Page.fileChooserOpened") return;
      const backendNodeId = Number(params?.backendNodeId) || 0;
      resolveChooser(backendNodeId || undefined);
    };
    contents.debugger.on("message", handler);
    try {
      await this.cdp("Page.setInterceptFileChooserDialog", { enabled: true });
      await trigger();
      return await Promise.race([
        chooser,
        delay(Math.max(50, timeoutMs)).then(() => undefined),
      ]);
    } finally {
      contents.debugger.removeListener("message", handler);
      await this.cdp("Page.setInterceptFileChooserDialog", { enabled: false }).catch(() => undefined);
    }
  }

  private async isFileInputRef(ref?: string): Promise<boolean> {
    return Boolean(await this.callOnRef(ref, `function(){
      return String(this.tagName || '').toLowerCase() === 'input'
        && String(this.getAttribute('type') || '').toLowerCase() === 'file';
    }`));
  }

  private async snapshotFrame(
    frame: WebFrameMain,
    interactiveOnly: boolean,
    limit: number,
  ): Promise<FrameSnapshotElement[]> {
    const token = randomUUID();
    const code = `(() => {
      const refs = new Map();
      globalThis[Symbol.for('xiaomei.browser.refs')] = refs;
      const actionable = 'a[href],button,input,textarea,select,option,[contenteditable="true"],[role="button"],[role="checkbox"],[role="combobox"],[role="link"],[role="listbox"],[role="menuitem"],[role="radio"],[role="searchbox"],[role="slider"],[role="spinbutton"],[role="switch"],[role="tab"],[role="textbox"],[role="option"]';
      const readable = actionable + ',h1,h2,h3,h4,h5,h6,p,img,table,th,td,li,article';
      const nodes = Array.from(document.querySelectorAll(${interactiveOnly ? "actionable" : "readable"}));
      const roleFor = (element) => {
        const explicit = (element.getAttribute('role') || '').trim();
        if (explicit) return explicit;
        const tag = element.tagName.toLowerCase();
        if (tag === 'a') return 'link';
        if (tag === 'button') return 'button';
        if (tag === 'textarea') return 'textbox';
        if (tag === 'select') return 'combobox';
        if (tag === 'option') return 'option';
        if (tag === 'img') return 'img';
        if (/^h[1-6]$/.test(tag)) return 'heading';
        if (tag === 'p') return 'paragraph';
        if (tag === 'table') return 'table';
        if (tag === 'th') return 'columnheader';
        if (tag === 'td') return 'cell';
        if (tag === 'li') return 'listitem';
        if (tag === 'article') return 'article';
        if (tag === 'input') {
          const type = (element.getAttribute('type') || 'text').toLowerCase();
          if (type === 'checkbox') return 'checkbox';
          if (type === 'radio') return 'radio';
          if (['button', 'submit', 'reset'].includes(type)) return 'button';
          if (type === 'range') return 'slider';
          return 'textbox';
        }
        return element.isContentEditable ? 'textbox' : tag;
      };
      const nameFor = (element) => {
        const labelledBy = (element.getAttribute('aria-labelledby') || '').trim();
        const labelled = labelledBy.split(/\\s+/).filter(Boolean)
          .map((id) => document.getElementById(id)?.textContent || '').join(' ').trim();
        return labelled || (element.getAttribute('aria-label') || '').trim()
          || (element.getAttribute('placeholder') || '').trim()
          || (element.getAttribute('alt') || '').trim()
          || (element.getAttribute('title') || '').trim()
          || (element.innerText || element.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 500);
      };
      const visible = (element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && Number(style.opacity || 1) !== 0
          && rect.width > 0 && rect.height > 0;
      };
      const result = [];
      for (const element of nodes) {
        if (result.length >= ${Math.max(0, limit)}) break;
        if (!visible(element)) continue;
        const role = roleFor(element);
        const name = nameFor(element);
        const value = 'value' in element && element.value != null
          ? String(element.value)
          : element.isContentEditable
            ? String(element.innerText || element.textContent || '')
            : undefined;
        if (!name && value == null && !${interactiveOnly}) continue;
        const domRef = ${JSON.stringify(token)} + '-' + (result.length + 1);
        refs.set(domRef, element);
        result.push({
          domRef,
          role,
          name,
          ...(value == null ? {} : { value }),
          ...((element.getAttribute('aria-description') || element.getAttribute('title')) ? {
            description: element.getAttribute('aria-description') || element.getAttribute('title')
          } : {}),
        });
      }
      return result;
    })()`;
    const result = await frame.executeJavaScript(code);
    return Array.isArray(result) ? result as FrameSnapshotElement[] : [];
  }

  private async typeIntoRef(
    ref: string | undefined,
    text: string,
    clear: boolean,
  ): Promise<Record<string, unknown>> {
    await this.callOnRef(ref, `function(clear){
      this.scrollIntoView({block:'center'});
      this.focus({preventScroll:true});
      if (!clear && 'selectionStart' in this && typeof this.setSelectionRange === 'function') {
        const end = String(this.value || '').length;
        this.setSelectionRange(end, end);
      } else if (!clear && this.isContentEditable) {
        const selection = this.ownerDocument.getSelection();
        const range = this.ownerDocument.createRange();
        range.selectNodeContents(this);
        range.collapse(false);
        selection.removeAllRanges();
        selection.addRange(range);
      }
    }`, [clear]);
    if (clear) {
      // Use the native input path instead of assigning value/textContent.
      // React-controlled inputs and contenteditable editors then receive the
      // same beforeinput/input events as real keyboard editing.
      const selectAllModifier = process.platform === "darwin" ? 4 : 2;
      await this.cdp("Input.dispatchKeyEvent", {
        type: "rawKeyDown", key: "a", code: "KeyA", modifiers: selectAllModifier,
      });
      await this.cdp("Input.dispatchKeyEvent", {
        type: "keyUp", key: "a", code: "KeyA", modifiers: selectAllModifier,
      });
      await this.cdp("Input.dispatchKeyEvent", {
        type: "rawKeyDown", key: "Backspace", code: "Backspace",
      });
      await this.cdp("Input.dispatchKeyEvent", {
        type: "keyUp", key: "Backspace", code: "Backspace",
      });
    }
    await this.cdp("Input.insertText", { text });
    const observed = await this.callOnRef(ref, `function(){
      return new Promise((resolve) => {
        requestAnimationFrame(() => {
          const value = 'value' in this
            ? String(this.value ?? '')
            : String(this.innerText ?? this.textContent ?? '');
          resolve({
            value,
            tag: String(this.tagName || '').toLowerCase(),
            content_editable: Boolean(this.isContentEditable),
          });
        });
      });
    }`);
    const value = String(observed?.value ?? "");
    const verified = clear ? value === text : value.endsWith(text);
    return {
      typed: true,
      verified,
      observed_value: value,
      requested_text: text,
      clear,
      element: {
        tag: String(observed?.tag ?? ""),
        content_editable: Boolean(observed?.content_editable),
      },
      page: this.state(),
    };
  }

  private async selectRef(ref: string | undefined, value: string): Promise<void> {
    await this.callOnRef(ref, `function(value){
      this.value = value;
      this.dispatchEvent(new Event('input',{bubbles:true}));
      this.dispatchEvent(new Event('change',{bubbles:true}));
    }`, [value]);
  }

  private async downloadRef(ref?: string): Promise<DownloadResult> {
    if (this.pendingDownload) throw new Error("已有网页文件正在下载");
    this.lastError = "";
    this.transfer = {
      direction: "download",
      status: "starting",
      name: "",
      receivedBytes: 0,
      totalBytes: 0,
      percent: 0,
    };
    this.emitState();
    const result = new Promise<DownloadResult>((resolve, reject) => {
      const timer = setTimeout(() => {
        const pending = this.pendingDownload;
        if (!pending) return;
        pending.item?.cancel();
        this.pendingDownload = null;
        this.failTransfer("网页未在规定时间内完成下载");
        reject(new Error("网页未在规定时间内完成下载"));
      }, 120_000);
      this.pendingDownload = {
        partition: this.partition,
        resolve,
        reject,
        timer,
      };
    });
    try {
      await this.nativeClickRef(ref);
    } catch (error) {
      this.rejectPendingDownload(error instanceof Error ? error : new Error(String(error)));
    }
    return result;
  }

  private async captureDownload(item: DownloadItem): Promise<void> {
    const pending = this.pendingDownload;
    if (!pending || pending.partition !== this.partition) return;
    pending.item = item;
    const name = safeFileName(item.getFilename() || "download");
    const totalBytes = Math.max(0, item.getTotalBytes());
    if (totalBytes > MAX_TRANSFER_BYTES) {
      item.cancel();
      this.rejectPendingDownload(new Error("网页下载文件不能超过 10 MB"));
      return;
    }
    const directory = path.join(app.getPath("temp"), "xiaomei-browser-downloads");
    // DownloadItem.setSavePath must run in the synchronous will-download turn.
    mkdirSync(directory, { recursive: true });
    const tempPath = path.join(directory, `${randomUUID()}-${name}`);
    item.setSavePath(tempPath);
    this.transfer = {
      direction: "download",
      status: "transferring",
      name,
      receivedBytes: 0,
      totalBytes,
      percent: 0,
    };
    this.emitState();
    item.on("updated", (_event, state) => {
      if (state === "interrupted") {
        this.rejectPendingDownload(new Error("网页文件下载中断"));
        return;
      }
      const receivedBytes = Math.max(0, item.getReceivedBytes());
      if (receivedBytes > MAX_TRANSFER_BYTES) {
        item.cancel();
        this.rejectPendingDownload(new Error("网页下载文件不能超过 10 MB"));
        return;
      }
      this.transfer = {
        direction: "download",
        status: "transferring",
        name,
        receivedBytes,
        totalBytes,
        percent: totalBytes > 0 ? Math.min(100, Math.round(receivedBytes * 100 / totalBytes)) : 0,
      };
      this.emitState();
    });
    item.once("done", async (_event, state) => {
      if (state !== "completed") {
        await fs.rm(tempPath, { force: true }).catch(() => undefined);
        this.rejectPendingDownload(new Error(`网页文件下载失败：${state}`));
        return;
      }
      try {
        const data = await fs.readFile(tempPath);
        if (!data.length || data.length > MAX_TRANSFER_BYTES) {
          throw new Error("网页下载文件为空或超过 10 MB");
        }
        const current = this.pendingDownload;
        if (!current) return;
        clearTimeout(current.timer);
        this.pendingDownload = null;
        this.transfer = {
          direction: "download",
          status: "completed",
          name,
          receivedBytes: data.length,
          totalBytes: data.length,
          percent: 100,
        };
        this.emitState();
        current.resolve({
          name,
          mime_type: item.getMimeType() || "application/octet-stream",
          size: data.length,
          data_base64: data.toString("base64"),
        });
      } catch (error) {
        this.rejectPendingDownload(error instanceof Error ? error : new Error(String(error)));
      } finally {
        await fs.rm(tempPath, { force: true }).catch(() => undefined);
      }
    });
  }

  private rejectPendingDownload(error: Error): void {
    const pending = this.pendingDownload;
    if (!pending) return;
    clearTimeout(pending.timer);
    this.pendingDownload = null;
    this.failTransfer(error.message);
    pending.reject(error);
  }

  private failTransfer(message: string): void {
    if (this.transfer) this.transfer = { ...this.transfer, status: "failed" };
    this.lastError = message;
    this.emitState();
  }

  private async uploadRef(command: BrowserCommand): Promise<Record<string, unknown>> {
    this.throwIfCancelled(command.commandId);
    this.lastError = "";
    const encoded = String(command.dataBase64 || "");
    const data = Buffer.from(encoded, "base64");
    if (!encoded || !data.length || data.length > MAX_TRANSFER_BYTES) {
      throw new Error("待上传文件为空或超过 10 MB");
    }
    const name = safeFileName(command.name || "upload.bin");
    const directory = path.join(app.getPath("temp"), "xiaomei-browser-uploads");
    await fs.mkdir(directory, { recursive: true });
    const tempPath = path.join(directory, `${randomUUID()}-${name}`);
    await fs.writeFile(tempPath, data, { flag: "wx" });
    this.uploadTempPaths.add(tempPath);
    this.transfer = {
      direction: "upload",
      status: "starting",
      name,
      receivedBytes: 0,
      totalBytes: data.length,
      percent: 0,
    };
    this.emitState();
    try {
      let backendNodeId = this.pendingFileChooserBackendNodeId || 0;
      this.pendingFileChooserBackendNodeId = null;
      if (!backendNodeId && command.ref && await this.isFileInputRef(command.ref)) {
        backendNodeId = this.backendNodeId(command.ref);
      } else if (!backendNodeId && command.ref) {
        backendNodeId = await this.captureFileChooser(
          () => this.nativeClickRef(command.ref),
          1_500,
        ) || 0;
      } else {
        const inputs = backendNodeId ? [] : await this.discoverFileInputs();
        if (!inputs.length) {
          if (!backendNodeId) {
            throw new Error("页面中没有找到文件上传控件；请为 upload 提供上传按钮或 role=file 控件的 ref");
          }
        }
        if (inputs.length > 1) {
          throw new Error("页面存在多个文件上传控件；请重新读取页面并为 upload 指定 role=file 的 ref");
        }
        if (inputs.length === 1) backendNodeId = inputs[0].backendDOMNodeId;
      }
      if (!backendNodeId) {
        const inputs = await this.discoverFileInputs();
        if (inputs.length === 1) backendNodeId = inputs[0].backendDOMNodeId;
      }
      if (!backendNodeId) {
        throw new Error("上传入口未打开文件选择器，也没有创建文件上传控件");
      }
      this.throwIfCancelled(command.commandId);
      await this.cdp("DOM.setFileInputFiles", {
        files: [tempPath],
        backendNodeId,
      });
      this.transfer = { ...this.transfer, status: "completed" };
      this.emitState();
      return {
        uploaded: true,
        name,
        mime_type: command.mimeType || "application/octet-stream",
        size: data.length,
      };
    } catch (error) {
      await fs.rm(tempPath, { force: true }).catch(() => undefined);
      this.uploadTempPaths.delete(tempPath);
      this.failTransfer(error instanceof Error ? error.message : String(error));
      throw error;
    }
  }
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, fallback: T): Promise<T> {
  return new Promise<T>((resolve) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      resolve(fallback);
    }, Math.max(1, timeoutMs));
    promise.then((value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(value);
    }).catch(() => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(fallback);
    });
  });
}

function delay(timeoutMs: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, timeoutMs)));
}

function safeFileName(input: string): string {
  const normalized = path.basename(String(input || "download"))
    .replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_")
    .trim();
  return normalized.slice(0, 180) || "download";
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
