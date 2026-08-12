export type BootstrapPhase =
  | "first_run"
  | "setup_incomplete"
  | "repair_required"
  | "ready_locked"
  | "ready";

export type BootstrapStep =
  | "welcome"
  | "identity"
  | "runtime"
  | "inference"
  | "embedding"
  | "optional_services"
  | "agent"
  | "model"
  | "complete";

export interface BootstrapFacts {
  identityExists: boolean;
  identityUnlocked: boolean;
  runtimeReady: boolean;
  inferenceReady: boolean;
  embeddingModelPresent: boolean;
  agentCount: number;
  setupStarted: boolean;
  setupCompleted: boolean;
  managedSetup: boolean;
  setupMode?: "quick" | "custom";
  optionalServicesCompleted?: boolean;
}

export interface BootstrapResolution {
  phase: BootstrapPhase;
  step: BootstrapStep;
  legacyReady: boolean;
}

/**
 * Resolve application startup from observable facts only.
 *
 * A completed installation is repaired only when a required local component
 * disappears. A stopped or deleted Agent is normal user-managed state and does
 * not turn an everyday launch back into first-run setup.
 */
export function resolveBootstrapState(facts: BootstrapFacts): BootstrapResolution {
  const requiredInferenceReady = !facts.managedSetup || facts.inferenceReady;
  const requiredEmbeddingReady = !facts.managedSetup || facts.embeddingModelPresent;
  const requiredRuntimeReady = facts.runtimeReady && requiredInferenceReady && requiredEmbeddingReady;

  if (facts.setupCompleted) {
    if (!facts.identityExists) return { phase: "repair_required", step: "identity", legacyReady: false };
    if (!facts.runtimeReady) return { phase: "repair_required", step: "runtime", legacyReady: false };
    if (!requiredInferenceReady) return { phase: "repair_required", step: "inference", legacyReady: false };
    if (!requiredEmbeddingReady) return { phase: "repair_required", step: "embedding", legacyReady: false };
    return {
      phase: facts.identityUnlocked ? "ready" : "ready_locked",
      step: "complete",
      legacyReady: false,
    };
  }

  // An existing installation predating Bootstrap has no marker. A local
  // account is sufficient evidence: remote-only users may intentionally have
  // no local Agent directory at all.
  const legacyReady = !facts.setupMode
    && facts.identityExists
    && requiredRuntimeReady;
  if (legacyReady) {
    return {
      phase: facts.identityUnlocked ? "ready" : "ready_locked",
      step: "complete",
      legacyReady: true,
    };
  }

  // A pre-Bootstrap installation may have an account, local Agent data, or
  // both while lacking a newly packaged host component. Repair only the
  // missing layer; never send that person through new-install onboarding.
  const legacyInstallation = !facts.setupMode
    && (facts.identityExists || facts.agentCount > 0);
  if (legacyInstallation) {
    if (!facts.runtimeReady) return { phase: "repair_required", step: "runtime", legacyReady: false };
    if (!requiredInferenceReady) return { phase: "repair_required", step: "inference", legacyReady: false };
    if (!requiredEmbeddingReady) return { phase: "repair_required", step: "embedding", legacyReady: false };
    if (!facts.identityExists) {
      return { phase: "setup_incomplete", step: "identity", legacyReady: false };
    }
  }

  if (!facts.setupMode) {
    return { phase: "first_run", step: "welcome", legacyReady: false };
  }

  if (!facts.runtimeReady) {
    return { phase: "setup_incomplete", step: "runtime", legacyReady: false };
  }
  if (!requiredInferenceReady) {
    return { phase: "setup_incomplete", step: "inference", legacyReady: false };
  }
  if (!requiredEmbeddingReady) {
    return { phase: "setup_incomplete", step: "embedding", legacyReady: false };
  }
  if (facts.setupMode === "custom" && !facts.optionalServicesCompleted) {
    return { phase: "setup_incomplete", step: "optional_services", legacyReady: false };
  }
  if (!facts.identityExists) {
    return { phase: "first_run", step: "identity", legacyReady: false };
  }
  if (!facts.identityUnlocked) {
    return { phase: "setup_incomplete", step: "identity", legacyReady: false };
  }
  if (facts.agentCount === 0) {
    return { phase: "setup_incomplete", step: "agent", legacyReady: false };
  }
  return { phase: "setup_incomplete", step: "model", legacyReady: false };
}
