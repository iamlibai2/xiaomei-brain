const assert = require("node:assert/strict");
const test = require("node:test");

const { resolveBootstrapState } = require("../dist/main/bootstrap-state.js");

function facts(overrides = {}) {
  return {
    identityExists: false,
    identityUnlocked: false,
    runtimeReady: false,
    inferenceReady: false,
    embeddingModelPresent: false,
    agentCount: 0,
    setupStarted: false,
    setupCompleted: false,
    managedSetup: true,
    setupMode: "custom",
    optionalServicesCompleted: true,
    ...overrides,
  };
}

test("a pristine installation starts with setup mode selection", () => {
  assert.deepEqual(resolveBootstrapState(facts({ setupMode: undefined })), {
    phase: "first_run",
    step: "welcome",
    legacyReady: false,
  });
});

test("quick setup prepares core components before identity", () => {
  const base = facts({ setupMode: "quick", optionalServicesCompleted: false });
  assert.equal(resolveBootstrapState(base).step, "runtime");
  assert.equal(resolveBootstrapState({ ...base, runtimeReady: true }).step, "inference");
  assert.equal(resolveBootstrapState({ ...base, runtimeReady: true, inferenceReady: true }).step, "embedding");
  assert.equal(resolveBootstrapState({
    ...base,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
  }).step, "identity");
});

test("custom setup includes optional local services", () => {
  const base = facts({
    optionalServicesCompleted: false,
  });
  assert.equal(resolveBootstrapState(base).step, "runtime");
  assert.equal(resolveBootstrapState({
    ...base,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
  }).step, "optional_services");
  assert.equal(resolveBootstrapState({
    ...base,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    optionalServicesCompleted: true,
  }).step, "identity");
});

test("an interrupted setup resumes at the first missing component", () => {
  const base = facts({
    setupStarted: true,
  });
  assert.equal(resolveBootstrapState(base).step, "runtime");
  assert.equal(resolveBootstrapState({ ...base, runtimeReady: true }).step, "inference");
  assert.equal(resolveBootstrapState({
    ...base,
    runtimeReady: true,
    inferenceReady: true,
  }).step, "embedding");
  assert.equal(resolveBootstrapState({
    ...base,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    identityExists: true,
    identityUnlocked: true,
  }).step, "agent");
  assert.equal(resolveBootstrapState({
    ...base,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    identityExists: true,
    identityUnlocked: true,
    agentCount: 1,
  }).step, "model");
});

test("an existing pre-bootstrap installation opens normally", () => {
  assert.deepEqual(resolveBootstrapState(facts({
    setupMode: undefined,
    identityExists: true,
    identityUnlocked: true,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    agentCount: 2,
  })), {
    phase: "ready",
    step: "complete",
    legacyReady: true,
  });
});

test("a pre-bootstrap account using only remote Agents opens normally", () => {
  assert.deepEqual(resolveBootstrapState(facts({
    setupMode: undefined,
    identityExists: true,
    identityUnlocked: true,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    agentCount: 0,
  })), {
    phase: "ready",
    step: "complete",
    legacyReady: true,
  });
});

test("a pre-bootstrap remote-only installation repairs host components without onboarding", () => {
  assert.deepEqual(resolveBootstrapState(facts({
    setupMode: undefined,
    identityExists: true,
    identityUnlocked: true,
    agentCount: 0,
  })), {
    phase: "repair_required",
    step: "runtime",
    legacyReady: false,
  });
});

test("a pre-bootstrap Agent installation repairs only missing host components", () => {
  const existing = facts({
    setupMode: undefined,
    identityExists: true,
    identityUnlocked: true,
    agentCount: 2,
  });
  assert.deepEqual(resolveBootstrapState(existing), {
    phase: "repair_required",
    step: "runtime",
    legacyReady: false,
  });
  assert.equal(resolveBootstrapState({ ...existing, runtimeReady: true }).step, "inference");
  assert.equal(resolveBootstrapState({
    ...existing,
    runtimeReady: true,
    inferenceReady: true,
  }).step, "embedding");
  assert.deepEqual(resolveBootstrapState({
    ...existing,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    setupStarted: true,
  }), {
    phase: "ready",
    step: "complete",
    legacyReady: true,
  });
});

test("an interrupted new installation is never mistaken for a legacy installation", () => {
  assert.equal(resolveBootstrapState(facts({
    setupStarted: true,
    setupMode: "quick",
    identityExists: true,
    identityUnlocked: true,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    agentCount: 1,
  })).step, "model");
});

test("a completed installation can be locked without becoming incomplete", () => {
  assert.equal(resolveBootstrapState(facts({
    identityExists: true,
    identityUnlocked: false,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    setupCompleted: true,
  })).phase, "ready_locked");
});

test("a completed installation repairs a missing account without touching Agents", () => {
  assert.deepEqual(resolveBootstrapState(facts({
    identityExists: false,
    identityUnlocked: false,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    agentCount: 2,
    setupCompleted: true,
  })), {
    phase: "repair_required",
    step: "identity",
    legacyReady: false,
  });
});

test("a locked pre-bootstrap installation remains a normal locked installation", () => {
  assert.deepEqual(resolveBootstrapState(facts({
    setupMode: undefined,
    identityExists: true,
    identityUnlocked: false,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    agentCount: 2,
  })), {
    phase: "ready_locked",
    step: "complete",
    legacyReady: true,
  });
});

test("missing required components enter repair but stopped Agents do not", () => {
  const completed = facts({
    identityExists: true,
    identityUnlocked: true,
    runtimeReady: true,
    inferenceReady: true,
    embeddingModelPresent: true,
    setupCompleted: true,
  });
  assert.equal(resolveBootstrapState({ ...completed, runtimeReady: false }).phase, "repair_required");
  assert.equal(resolveBootstrapState({ ...completed, embeddingModelPresent: false }).step, "embedding");
  assert.equal(resolveBootstrapState({ ...completed, agentCount: 0 }).phase, "ready");
});

test("development does not require packaged inference components", () => {
  assert.equal(resolveBootstrapState(facts({
    setupMode: undefined,
    identityExists: true,
    identityUnlocked: true,
    runtimeReady: true,
    agentCount: 1,
    managedSetup: false,
  })).phase, "ready");
});
