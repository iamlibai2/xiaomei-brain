import { promises as fs } from "fs";
import path from "path";
import { app } from "electron";
import { IdentityVault, type IdentityVaultStatus } from "./identity-vault";
import { LocalAIRuntimeManager, type LocalAIServiceStatus } from "./local-ai-runtime-manager";
import { discoverLocalAgents, type LocalAgentInfo } from "./local-agent-discovery";
import { RuntimeManager, type RuntimeReadiness } from "./runtime-manager";
import { SetupManager, type FirstRunSetupStatus, type InferenceVariant } from "./setup-manager";
import {
  resolveBootstrapState,
  type BootstrapPhase,
  type BootstrapStep,
} from "./bootstrap-state";

interface BootstrapRecord {
  schemaVersion: 1;
  startedAt: string;
  completedAt?: string;
  initialAgentId?: string;
  inferenceVariant?: InferenceVariant;
  setupMode?: "quick" | "custom";
  optionalServices?: string[];
  optionalServicesCompleted?: boolean;
}

export interface BootstrapStatus {
  phase: BootstrapPhase;
  step: BootstrapStep;
  managedSetup: boolean;
  legacyReady: boolean;
  identity: IdentityVaultStatus;
  runtime: RuntimeReadiness;
  setup: FirstRunSetupStatus;
  embedding?: LocalAIServiceStatus;
  agents: LocalAgentInfo[];
  initialAgentId: string;
  startedAt: string;
  completedAt: string;
  preview: boolean;
  setupMode: "quick" | "custom" | "";
  optionalServices: string[];
}

const DEVELOPMENT_SETUP: FirstRunSetupStatus = {
  requiredReady: true,
  inference: {
    ready: true,
    variant: "unknown",
    torchVersion: "development",
    cudaAvailable: false,
  },
  ffmpeg: { ready: false, path: "" },
  gpu: { detected: false, name: "" },
};

export class BootstrapManager {
  private readonly statePath: string;
  private startupPromise: Promise<void> | null = null;
  private previewStep: BootstrapStep;
  private previewMode: "quick" | "custom" = "custom";

  constructor(
    private readonly runtime: RuntimeManager,
    private readonly setupManager: SetupManager,
    private readonly localAI: LocalAIRuntimeManager,
    private readonly identities: IdentityVault,
    stateDirectory = app.getPath("userData"),
  ) {
    this.statePath = path.join(stateDirectory, "bootstrap-state.json");
    const requestedPreview = String(process.env.XIAOMEI_BOOTSTRAP_PREVIEW || "").toLowerCase();
    this.previewStep = (["welcome", "runtime", "inference", "embedding", "optional_services", "agent", "model"] as BootstrapStep[])
      .includes(requestedPreview as BootstrapStep)
      ? requestedPreview as BootstrapStep
      : "welcome";
  }

  private get previewEnabled(): boolean {
    return !app.isPackaged && Boolean(process.env.XIAOMEI_BOOTSTRAP_PREVIEW);
  }

  start(): void {
    if (this.previewEnabled) return;
    if (!this.startupPromise) {
      this.startupPromise = this.restoreExistingInstallation().catch((error) => {
        console.error("[bootstrap] existing installation restore failed", error);
      });
    }
  }

  async status(): Promise<BootstrapStatus> {
    if (this.previewEnabled) return this.previewStatus();
    const record = await this.readRecord();
    const identity = this.identities.status();
    const managedSetup = app.isPackaged;
    // Unlock must be immediately available. Runtime extraction and model
    // startup continue in the background and are evaluated after unlock.
    if (identity.exists && !identity.unlocked) {
      const agents = await discoverLocalAgents();
      const completedOrLegacy = Boolean(record?.completedAt) || !record?.startedAt;
      if (completedOrLegacy) return {
        phase: completedOrLegacy ? "ready_locked" : "setup_incomplete",
        step: completedOrLegacy ? "complete" : "identity",
        managedSetup,
        legacyReady: !record?.startedAt,
        identity,
        runtime: await this.runtime.readiness(),
        setup: DEVELOPMENT_SETUP,
        agents,
        initialAgentId: record?.initialAgentId || agents[0]?.agentId || "xiaomei",
        startedAt: record?.startedAt || "",
        completedAt: record?.completedAt || "",
        preview: false,
        setupMode: record?.setupMode || "",
        optionalServices: record?.optionalServices || [],
      };
    }
    if (this.startupPromise) await this.startupPromise;
    const runtime = await this.runtime.readiness();
    let setup = DEVELOPMENT_SETUP;
    let embedding: LocalAIServiceStatus | undefined;
    if (runtime.ready && managedSetup) {
      setup = await this.setupManager.status();
      if (setup.requiredReady) {
        const cached = await this.localAI.cachedSnapshot();
        const cachedEmbedding = cached?.services.find((item) => item.id === "embedding");
        const snapshot = cachedEmbedding?.model_present ? cached : await this.localAI.snapshot();
        embedding = snapshot?.services.find((item) => item.id === "embedding");
      }
    }
    const agents = await discoverLocalAgents();
    const resolution = resolveBootstrapState({
      identityExists: identity.exists,
      identityUnlocked: identity.unlocked,
      runtimeReady: runtime.ready,
      inferenceReady: setup.inference.ready,
      embeddingModelPresent: Boolean(embedding?.model_present) || !managedSetup,
      agentCount: agents.length,
      setupStarted: Boolean(record?.startedAt),
      setupCompleted: Boolean(record?.completedAt),
      managedSetup,
      setupMode: record?.setupMode,
      optionalServicesCompleted: record?.optionalServicesCompleted,
    });
    return {
      ...resolution,
      managedSetup,
      identity,
      runtime,
      setup,
      embedding,
      agents,
      initialAgentId: record?.initialAgentId || agents[0]?.agentId || "xiaomei",
      startedAt: record?.startedAt || "",
      completedAt: record?.completedAt || "",
      preview: false,
      setupMode: record?.setupMode || "",
      optionalServices: record?.optionalServices || [],
    };
  }

  async begin(): Promise<BootstrapStatus> {
    if (this.previewEnabled) return this.previewStatus();
    const current = await this.readRecord();
    if (!current) {
      await this.writeRecord({ schemaVersion: 1, startedAt: new Date().toISOString() });
    }
    return this.status();
  }

  async prepareRuntime(): Promise<BootstrapStatus> {
    if (this.previewEnabled) {
      this.previewStep = "inference";
      return this.previewStatus();
    }
    await this.runtime.warmup();
    return this.status();
  }

  async selectMode(mode: "quick" | "custom"): Promise<BootstrapStatus> {
    if (this.previewEnabled) {
      this.previewMode = mode;
      this.previewStep = "runtime";
      return this.previewStatus();
    }
    const current = await this.ensureRecord();
    await this.writeRecord({ ...current, setupMode: mode });
    return this.status();
  }

  async prepareQuick(): Promise<BootstrapStatus> {
    if (this.previewEnabled) {
      // Keep the simulated preparation visible long enough to verify the
      // quick-start experience instead of flashing straight to registration.
      await new Promise((resolve) => setTimeout(resolve, 1_800));
      this.previewStep = "identity";
      return this.previewStatus();
    }
    let current = await this.status();
    if (current.setupMode !== "quick") throw new Error("Quick setup is not selected");
    if (!current.runtime.ready) {
      await this.runtime.warmup();
      current = await this.status();
    }
    if (!current.setup.inference.ready) {
      // Quick setup deliberately chooses the compact CPU baseline. CUDA is a
      // large optional acceleration path and remains available in custom setup
      // or later from Local AI settings.
      const variant: InferenceVariant = "cpu";
      await this.rememberOptions(variant);
      await this.setupManager.installInference(variant);
      current = await this.status();
    }
    if (!current.embedding?.model_present) {
      const variant: InferenceVariant = current.setup.inference.variant === "cuda" ? "cuda" : "cpu";
      await this.localAI.selectDevice("embedding", variant);
      await this.localAI.control("embedding", "download", variant);
      while (true) {
        await new Promise((resolve) => setTimeout(resolve, 3_000));
        const embedding = (await this.localAI.snapshot()).services.find((item) => item.id === "embedding");
        if (embedding?.model_present) break;
        if (embedding?.state === "download_error" || embedding?.state === "error") {
          throw new Error(embedding.error || "Embedding model download failed");
        }
      }
      await this.localAI.control("embedding", "start", variant);
    }
    return this.status();
  }

  async completeOptionalServices(services: string[]): Promise<BootstrapStatus> {
    const allowed = new Set(["ffmpeg", "stt", "tts_voxcpm", "face", "voiceprint"]);
    const selected = [...new Set(services.filter((item) => allowed.has(item)))];
    if (this.previewEnabled) {
      this.previewStep = "agent";
      return this.previewStatus(this.previewMode, selected);
    }
    const pending = await this.ensureRecord();
    await this.writeRecord({
      ...pending,
      optionalServices: selected,
      optionalServicesCompleted: false,
    });
    const setup = await this.setupManager.status();
    for (const service of selected) {
      if (service === "ffmpeg") {
        if (!setup.ffmpeg.ready) await this.setupManager.installFfmpeg();
        continue;
      }
      let state = (await this.localAI.snapshot()).services.find((item) => item.id === service);
      if (!state?.installed) {
        await this.setupManager.installOptionalService(service);
        state = (await this.localAI.snapshot()).services.find((item) => item.id === service);
      }
      if (state?.downloadable && !state.model_present) {
        this.setupManager.reportProgress(service, "downloading", 0, `正在下载 ${state.name} 模型`);
        await this.localAI.control(service, "download", state.selected_device);
        while (true) {
          await new Promise((resolve) => setTimeout(resolve, 3_000));
          state = (await this.localAI.snapshot()).services.find((item) => item.id === service);
          if (state?.model_present) {
            this.setupManager.reportProgress(service, "complete", 100, `${state.name} 已准备好`);
            break;
          }
          if (state?.state === "download_error" || state?.state === "error") {
            throw new Error(state.error || `${service} model download failed`);
          }
          this.setupManager.reportProgress(
            service,
            "downloading",
            state?.download_progress || 0,
            `正在下载 ${state?.name || service} 模型`,
          );
        }
      }
    }
    const current = await this.ensureRecord();
    await this.writeRecord({
      ...current,
      optionalServices: selected,
      optionalServicesCompleted: true,
    });
    return this.status();
  }

  async rememberOptions(variant: InferenceVariant): Promise<void> {
    if (this.previewEnabled) return;
    const current = await this.ensureRecord();
    await this.writeRecord({ ...current, inferenceVariant: variant });
  }

  async provisionInitialAgent(options?: { name?: string; description?: string }): Promise<BootstrapStatus> {
    if (this.previewEnabled) {
      this.previewStep = "model";
      return this.previewStatus();
    }
    const existing = await discoverLocalAgents();
    let agentId = existing[0]?.agentId || "";
    if (!agentId) {
      const custom = this.previewMode === "custom" || (await this.readRecord())?.setupMode === "custom";
      const name = options?.name?.trim() || "小美";
      const description = options?.description?.trim() || "本地 AI Agent";
      const created = await this.runtime.createAgent(name, description, custom ? "" : "xiaomei");
      if (!created.ok || !created.agentId) throw new Error(created.message || "Unable to create initial Agent");
      agentId = created.agentId;
    }

    const current = await this.ensureRecord();
    await this.writeRecord({ ...current, initialAgentId: agentId });
    return this.status();
  }

  async complete(initialAgentId = ""): Promise<BootstrapStatus> {
    if (this.previewEnabled) {
      this.previewStep = "complete";
      return this.previewStatus();
    }
    const current = await this.ensureRecord();
    await this.writeRecord({
      ...current,
      initialAgentId: initialAgentId || current.initialAgentId,
      completedAt: new Date().toISOString(),
    });
    return this.status();
  }

  async advancePreview(): Promise<BootstrapStatus> {
    if (!this.previewEnabled) throw new Error("Bootstrap preview is not enabled");
    const next: Partial<Record<BootstrapStep, BootstrapStep>> = {
      identity: "agent",
      runtime: "inference",
      inference: "embedding",
      embedding: this.previewMode === "custom" ? "optional_services" : "identity",
      optional_services: "identity",
      agent: "model",
      model: "complete",
    };
    this.previewStep = next[this.previewStep] || "complete";
    return this.previewStatus();
  }

  private previewStatus(mode = this.previewMode, optionalServices: string[] = []): BootstrapStatus {
    return {
      phase: "setup_incomplete",
      step: this.previewStep,
      managedSetup: true,
      legacyReady: false,
      preview: true,
      setupMode: mode,
      optionalServices,
      identity: {
        exists: true,
        unlocked: true,
        displayName: "初始化预览",
        subject: "bootstrap-preview",
        activeSubject: "bootstrap-preview",
        accounts: [],
      },
      runtime: { ready: this.previewStep !== "runtime", source: "bundled" },
      setup: {
        requiredReady: this.previewStep !== "inference",
        inference: {
          ready: this.previewStep !== "inference",
          variant: "cpu",
          torchVersion: "preview",
          cudaAvailable: true,
        },
        ffmpeg: { ready: false, path: "" },
        gpu: { detected: true, name: "NVIDIA GPU（预览）" },
      },
      agents: [],
      initialAgentId: "xiaomei",
      startedAt: new Date().toISOString(),
      completedAt: this.previewStep === "complete" ? new Date().toISOString() : "",
    };
  }

  private async ensureRecord(): Promise<BootstrapRecord> {
    return await this.readRecord() || {
      schemaVersion: 1,
      startedAt: new Date().toISOString(),
    };
  }

  private async restoreExistingInstallation(): Promise<void> {
    const record = await this.readRecord();
    const identity = this.identities.status();
    const agents = await discoverLocalAgents();
    // A pristine installation must stay untouched until the person chooses
    // setup options. Existing installations and upgrades restore quietly.
    if (!record?.completedAt && (!identity.exists || agents.length === 0)) return;
    await this.runtime.warmup();
    const services = await this.localAI.snapshot();
    if (services.services.some((item) => item.id === "embedding" && item.model_present)) {
      void this.localAI.ensureEmbedding().catch((error) => {
        console.error("[bootstrap] embedding restore failed", error);
      });
    }
  }

  private async readRecord(): Promise<BootstrapRecord | null> {
    try {
      const value = JSON.parse(await fs.readFile(this.statePath, "utf8")) as Partial<BootstrapRecord>;
      if (value.schemaVersion !== 1 || typeof value.startedAt !== "string") return null;
      return value as BootstrapRecord;
    } catch {
      return null;
    }
  }

  private async writeRecord(record: BootstrapRecord): Promise<void> {
    await fs.mkdir(path.dirname(this.statePath), { recursive: true });
    const temporary = `${this.statePath}.${process.pid}.tmp`;
    await fs.writeFile(temporary, JSON.stringify(record, null, 2), "utf8");
    await fs.rename(temporary, this.statePath);
  }
}
